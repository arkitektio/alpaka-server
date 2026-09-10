"""Usage accounting and budgets.

Every LLM call (GraphQL chat, REST chat/completions/embeddings, vector
embedding) writes a ``UsageRecord``; ``usageRecords``/``usageStats``/``budgets``
are organization-scoped; a spent hard ``Budget`` blocks calls with a 429
(REST) or a GraphQL error."""

import datetime as dt
from decimal import Decimal

import httpx
import litellm
import openai
import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async
from django.core.asgi import get_asgi_application
from openai import AsyncOpenAI

import importlib
import llm.views as views
import vector.embedding as vector_embedding
from authentikate.models import Organization, User
from llm import models as llm_models
from llm.enums import BudgetPeriod
from llm.usage import period_end, period_start

ASGI_APP = get_asgi_application()
# The package re-exports the ``chat`` resolver under the submodule's name, so
# attribute access would yield the function; import the module explicitly.
chat_mutation = importlib.import_module("llm.graphql.mutations.chat")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@sync_to_async
def seed(org_slug="static_org"):
    org = Organization.objects.get(slug=org_slug)
    provider = llm_models.Provider.objects.for_write().create(name="OpenAI", organization=org, kind="openai", api_key="sk-test", api_base="https://api.openai.com/v1")
    chat = llm_models.LLMModel.objects.for_write().create(provider=provider, model_id="gpt-4o-mini", label="GPT-4o mini", features=["chat"])
    embed = llm_models.LLMModel.objects.for_write().create(provider=provider, model_id="text-embedding-3-small", label="Embed", features=["embedding"])
    return {"org": org, "provider": provider, "chat": chat, "embed": embed}


@sync_to_async
def records(org):
    return list(llm_models.UsageRecord.objects.for_organization(org).order_by("id"))


@sync_to_async
def make_record(org, *, user=None, model=None, total_tokens=10, cost=None, endpoint="rest_chat", created_at=None):
    record = llm_models.UsageRecord.objects.for_write().create(
        organization=org, user=user, model=model, endpoint=endpoint,
        prompt_tokens=total_tokens, completion_tokens=0, total_tokens=total_tokens, cost=cost, latency_ms=100,
    )
    if created_at is not None:
        llm_models.UsageRecord.all_objects.filter(pk=record.pk).update(created_at=created_at)
    return record


@sync_to_async
def make_budget(org, **kwargs):
    return llm_models.Budget.objects.for_write().create(organization=org, **kwargs)


def _mock_litellm(monkeypatch, *, error=None):
    """Route the views' litellm calls through ``mock_response``."""
    orig_ac, orig_at, orig_ae = litellm.acompletion, litellm.atext_completion, litellm.aembedding

    def wrap(orig, mock_value):
        async def inner(**kw):
            if error is not None:
                raise error
            kw["mock_response"] = mock_value
            return await orig(**kw)

        return inner

    monkeypatch.setattr(views.litellm, "acompletion", wrap(orig_ac, "Hello world from mock"))
    monkeypatch.setattr(views.litellm, "atext_completion", wrap(orig_at, "Hello world from mock"))
    monkeypatch.setattr(views.litellm, "aembedding", wrap(orig_ae, [[0.1, 0.2, 0.3]]))


@pytest_asyncio.fixture
async def rest(authenticated_context, monkeypatch):
    """An OpenAI client against the in-process app, authenticated as the real
    seeded user/org, with model lookup returning the real seeded model."""
    data = await seed()
    request = authenticated_context.request

    async def fake_auth(http_request):
        return request.user, request.client, request.organization

    async def fake_lookup(*args, **kwargs):
        return data["chat"]

    monkeypatch.setattr(views, "authenticate_request", fake_auth)
    monkeypatch.setattr(views, "get_model_by_id_or_name", fake_lookup)
    monkeypatch.setattr(views, "get_default_model", fake_lookup)

    http_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=ASGI_APP), base_url="http://testserver")
    client = AsyncOpenAI(api_key="test", base_url="http://testserver/llm/v1", http_client=http_client)
    yield client, data
    await http_client.aclose()


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rest_chat_records_usage(rest, monkeypatch):
    client, data = rest
    _mock_litellm(monkeypatch)

    await client.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}])

    (record,) = await records(data["org"])
    assert record.endpoint == "rest_chat"
    assert record.status == "ok"
    assert record.total_tokens > 0
    assert record.model_id == data["chat"].id
    assert record.model_identifier == "gpt-4o-mini"
    assert record.llm_string == "openai/gpt-4o-mini"
    assert record.provider_kind == "openai"
    assert record.user_id is not None and record.client_id is not None
    assert record.latency_ms is not None
    assert record.cost is None or record.cost > 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rest_chat_streaming_records_usage_after_stream(rest, monkeypatch):
    client, data = rest
    _mock_litellm(monkeypatch)

    stream = await client.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}], stream=True)
    text = ""
    async for chunk in stream:
        assert chunk.object == "chat.completion.chunk"
        if chunk.choices and chunk.choices[0].delta.content:
            text += chunk.choices[0].delta.content
    assert text == "Hello world from mock"

    (record,) = await records(data["org"])
    assert record.endpoint == "rest_chat"
    assert record.status == "ok"
    assert record.total_tokens > 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rest_completion_and_embedding_record_usage(rest, monkeypatch):
    client, data = rest
    _mock_litellm(monkeypatch)

    await client.completions.create(model="x", prompt="hi")
    stream = await client.completions.create(model="x", prompt="hi", stream=True)
    async for _ in stream:
        pass
    await client.embeddings.create(model="x", input="hello")

    rows = await records(data["org"])
    assert [r.endpoint for r in rows] == ["rest_completion", "rest_completion", "rest_embedding"]
    # Embedding responses report total_tokens=0 next to a real prompt count.
    assert rows[2].prompt_tokens > 0 and rows[2].total_tokens == rows[2].prompt_tokens


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rest_error_records_error_row(rest, monkeypatch):
    client, data = rest
    _mock_litellm(monkeypatch, error=litellm.exceptions.APIError(status_code=403, message="nope", llm_provider="openai", model="gpt-4o-mini"))

    with pytest.raises(openai.PermissionDeniedError):
        await client.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}])

    (record,) = await records(data["org"])
    assert record.status == "error"
    assert record.error_type == "APIError"
    assert record.total_tokens == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graphql_chat_records_usage(aexecute, monkeypatch):
    data = await seed()
    orig = litellm.completion

    def fake_completion(**kw):
        kw["mock_response"] = "hi there"
        return orig(**kw)

    monkeypatch.setattr(chat_mutation.litellm, "completion", fake_completion)

    result = await aexecute(
        """
        mutation Chat($input: ChatInput!) { chat(input: $input) { choices { message { content } } usage { totalTokens } } }
        """,
        {"input": {"model": str(data["chat"].id), "messages": [{"role": "USER", "content": "hi"}]}},
    )
    assert result.data, result.errors
    assert result.data["chat"]["choices"][0]["message"]["content"] == "hi there"

    (record,) = await records(data["org"])
    assert record.endpoint == "graphql_chat"
    assert record.total_tokens == result.data["chat"]["usage"]["totalTokens"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_vector_embedding_records_usage(authenticated_context, monkeypatch):
    data = await seed()
    orig = litellm.aembedding

    async def fake_embedding(*args, **kw):
        kw["mock_response"] = [[0.1, 0.2]]
        return await orig(*args, **kw)

    monkeypatch.setattr(vector_embedding, "aembedding", fake_embedding)
    embedder = await sync_to_async(lambda: llm_models.LLMModel.objects.for_organization(data["org"]).select_related("provider").get(id=data["embed"].id))()

    vectors = await vector_embedding.aembed_texts(embedder, ["a"], user=authenticated_context.request.user, client=authenticated_context.request.client)
    assert len(vectors) == 1 and isinstance(vectors[0], list)

    (record,) = await records(data["org"])
    assert record.endpoint == "vector_embedding"
    assert record.user_id == authenticated_context.request.user.id
    assert record.prompt_tokens > 0


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_usage_records_and_stats_are_scoped_to_the_organization(aexecute, authenticated_context, other_org_context):
    data = await seed()
    other_org = other_org_context.request.organization
    await make_record(data["org"], total_tokens=10, cost=Decimal("0.5"))
    await make_record(data["org"], total_tokens=30, cost=Decimal("1.5"), endpoint="rest_embedding")
    await make_record(other_org, total_tokens=1000)

    query = """
        query { usageRecords { totalTokens endpoint } usageStats { count sum(field: TOTAL_TOKENS) cost: sum(field: COST) avg(field: LATENCY_MS) } }
    """
    mine = await aexecute(query)
    assert mine.data, mine.errors
    assert sorted(r["totalTokens"] for r in mine.data["usageRecords"]) == [10, 30]
    assert mine.data["usageStats"] == {"count": 2, "sum": 40.0, "cost": 2.0, "avg": 100.0}

    theirs = await aexecute(query, context=other_org_context)
    assert theirs.data, theirs.errors
    assert [r["totalTokens"] for r in theirs.data["usageRecords"]] == [1000]
    assert theirs.data["usageStats"]["count"] == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_usage_records_filters_and_series(aexecute, authenticated_context):
    data = await seed()
    user = authenticated_context.request.user
    yesterday = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    await make_record(data["org"], user=user, model=data["chat"], total_tokens=5, endpoint="graphql_chat")
    await make_record(data["org"], total_tokens=7, endpoint="rest_embedding", created_at=yesterday)

    result = await aexecute(
        """
        query($f: UsageRecordFilter, $since: DateTime!) {
            byEndpoint: usageRecords(filters: $f) { totalTokens }
            recent: usageRecords(filters: { createdAfter: $since }) { totalTokens }
            byModel: usageRecords(filters: { model: "%s" }) { totalTokens }
            usageStats { series(field: TOTAL_TOKENS, timestampField: CREATED_AT, by: DAY) { sum count } }
        }
        """ % data["chat"].id,
        {"f": {"endpoints": ["REST_EMBEDDING"]}, "since": (yesterday + dt.timedelta(hours=1)).isoformat()},
    )
    assert result.data, result.errors
    assert [r["totalTokens"] for r in result.data["byEndpoint"]] == [7]
    assert [r["totalTokens"] for r in result.data["recent"]] == [5]
    assert [r["totalTokens"] for r in result.data["byModel"]] == [5]
    assert sorted(b["sum"] for b in result.data["usageStats"]["series"]) == [5.0, 7.0]


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_budget_crud_and_status(aexecute, other_org_context):
    data = await seed()
    await make_record(data["org"], total_tokens=40, cost=Decimal("0.25"))

    created = await aexecute(
        """mutation($input: CreateBudgetInput!) { createBudget(input: $input) { id period limitTokens limitCost hard status { usedTokens usedCost remainingTokens exceeded } } }""",
        {"input": {"period": "MONTH", "limitTokens": 100, "limitCost": "1.0"}},
    )
    assert created.data, created.errors
    budget = created.data["createBudget"]
    assert budget["status"] == {"usedTokens": 40, "usedCost": "0.2500000000", "remainingTokens": 60, "exceeded": False}

    status = await aexecute("""query($id: ID!) { budgetStatus(id: $id) { usedTokens limitTokens exceeded } budgets { id } }""", {"id": budget["id"]})
    assert status.data, status.errors
    assert status.data["budgetStatus"] == {"usedTokens": 40, "limitTokens": 100, "exceeded": False}
    assert [b["id"] for b in status.data["budgets"]] == [budget["id"]]

    # Other organizations neither see nor can touch it.
    foreign = await aexecute("""query { budgets { id } }""", context=other_org_context)
    assert foreign.data == {"budgets": []}
    foreign_update = await aexecute("""mutation($id: ID!) { updateBudget(input: {id: $id, limitTokens: 1}) { id } }""", {"id": budget["id"]}, context=other_org_context)
    assert foreign_update.errors

    updated = await aexecute("""mutation($id: ID!) { updateBudget(input: {id: $id, limitTokens: 30, limitCost: null}) { limitTokens limitCost status { exceeded } } }""", {"id": budget["id"]})
    assert updated.data, updated.errors
    assert updated.data["updateBudget"] == {"limitTokens": 30, "limitCost": None, "status": {"exceeded": True}}

    deleted = await aexecute("""mutation($id: ID!) { deleteBudget(input: {id: $id}) }""", {"id": budget["id"]})
    assert deleted.data == {"deleteBudget": budget["id"]}, deleted.errors
    assert await sync_to_async(llm_models.Budget.objects.for_organization(data["org"]).count)() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_hard_budget_blocks_rest_with_429_and_no_upstream_call(rest, monkeypatch):
    client, data = rest
    await make_record(data["org"], total_tokens=50)
    await make_budget(data["org"], period="month", limit_tokens=50, hard=True)

    calls = []

    async def spy(**kw):
        calls.append(kw)
        raise AssertionError("upstream must not be called")

    monkeypatch.setattr(views.litellm, "acompletion", spy)

    with pytest.raises(openai.RateLimitError) as excinfo:
        await client.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}])
    assert excinfo.value.status_code == 429
    assert excinfo.value.body["type"] == "insufficient_quota"
    assert excinfo.value.body["code"] == "budget_exceeded"
    assert calls == []
    # A blocked call is not a usage record.
    assert len(await records(data["org"])) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_hard_budget_blocks_graphql_chat(aexecute, monkeypatch):
    data = await seed()
    await make_record(data["org"], total_tokens=5, cost=Decimal("2"))
    await make_budget(data["org"], period="day", limit_cost=Decimal("1"), hard=True)
    monkeypatch.setattr(chat_mutation.litellm, "completion", lambda **kw: pytest.fail("upstream must not be called"))

    result = await aexecute(
        """mutation Chat($input: ChatInput!) { chat(input: $input) { id } }""",
        {"input": {"model": str(data["chat"].id), "messages": [{"role": "USER", "content": "hi"}]}},
    )
    assert result.errors
    assert "Budget" in result.errors[0].message


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_soft_and_non_applicable_budgets_do_not_block(rest, monkeypatch):
    client, data = rest
    _mock_litellm(monkeypatch)
    other_user = await sync_to_async(User.objects.create)(username="someone_else", sub="77", iss="static_issuer")
    await make_record(data["org"], total_tokens=50)
    await make_budget(data["org"], period="month", limit_tokens=1, hard=False)  # soft: logs only
    await make_budget(data["org"], period="month", limit_tokens=1, hard=True, user=other_user)  # someone else's
    await make_budget(data["org"], period="month", limit_tokens=1, hard=True, model=data["embed"])  # another model's

    resp = await client.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == "Hello world from mock"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_budget_only_counts_the_current_period(rest, monkeypatch):
    client, data = rest
    _mock_litellm(monkeypatch)
    last_month = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40)
    await make_record(data["org"], total_tokens=500, created_at=last_month)
    await make_budget(data["org"], period="month", limit_tokens=100, hard=True)

    resp = await client.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == "Hello world from mock"


def test_period_boundaries():
    now = dt.datetime(2026, 9, 10, 15, 30, tzinfo=dt.timezone.utc)  # a Thursday
    assert period_start(BudgetPeriod.DAY, now) == dt.datetime(2026, 9, 10, tzinfo=dt.timezone.utc)
    assert period_end(BudgetPeriod.DAY, now) == dt.datetime(2026, 9, 11, tzinfo=dt.timezone.utc)
    assert period_start(BudgetPeriod.WEEK, now) == dt.datetime(2026, 9, 7, tzinfo=dt.timezone.utc)
    assert period_end(BudgetPeriod.WEEK, now) == dt.datetime(2026, 9, 14, tzinfo=dt.timezone.utc)
    assert period_start("month", now) == dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
    assert period_end("month", dt.datetime(2026, 12, 31, tzinfo=dt.timezone.utc)) == dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc)
