"""Typed decisions: the ``decide`` mutation and the systemone REST surface.

Run against a real Ollaya (a local decision-model runtime) and a fake of the
hosted TypeSafe API, both speaking the systemone wire protocol over real HTTP
(see ``tests/integration``). Nothing is patched: the provider rows point at the
containers, and the TypeSafe SDK talks to the in-process ASGI app.
"""

import json
import urllib.request
from decimal import Decimal

import httpx
import httpx2
import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async
from django.core.asgi import get_asgi_application
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy, Score, TypeSafeAPIError

from authentikate.models import Organization
from llm import models as llm_models

ASGI_APP = get_asgi_application()

#: The smallest Ollaya library model (mmBERT-base); cached across runs in the
#: `alpaka-test-ollaya` volume, so only the first run downloads it.
OLLAYA_MODEL = "laya:multilingual"
TYPESAFE_KEY = "ts-test-key"  # tests/integration/faketypesafe/app.py

TICKET = "Help! My payouts have been failing for 3 days and nobody answers."

DECIDE = """
mutation Decide($input: DecideInput!) {
  decide(input: $input) {
    model
    usage { promptTokens completionTokens totalTokens }
    answers {
      __typename
      ... on NoulAnswer { key noul }
      ... on ChoiceAnswer { key choice confidence probabilities { key probability } }
      ... on ScoreAnswer { key score confidence levels { level description probability } }
    }
  }
}
"""

CREATE_PROVIDER = """
mutation Create($input: ProviderInput!) {
  createProvider(input: $input) { id kind models { id modelId features } }
}
"""

TRIAGE = [
    {"noul": {"key": "urgent", "instructions": "Does this convey urgency?", "ifTrue": "Explicitly time-sensitive", "ifFalse": "No urgency expressed"}},
    {"choice": {"key": "department", "instructions": "Which team should handle this?", "options": [{"key": "billing", "description": "payments, payouts and invoices"}, {"key": "technical", "description": "bugs and outages of the product"}, {"key": "sales", "description": "buying a plan"}]}},
    {"score": {"key": "frustration", "instructions": "How frustrated is the customer?", "levels": ["Calm", "Frustrated", "Very angry"]}},
]


def _http(method: str, url: str, body=None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=900) as response:
        text = response.read().decode()
    return json.loads(text.strip().splitlines()[-1]) if text.strip() else {}


@pytest.fixture(scope="session")
def ollaya_url(backend_stack) -> str:
    """The test Ollaya, with the test model pulled (a no-op once it is cached)."""
    url = f"http://localhost:{backend_stack['ollaya']}"
    last = _http("POST", f"{url}/api/pull", {"model": OLLAYA_MODEL})
    assert last.get("status") == "success", last
    return url


@pytest.fixture(scope="session")
def typesafe_url(backend_stack) -> str:
    return f"http://localhost:{backend_stack['faketypesafe']}"


@pytest.fixture
def faketypesafe(typesafe_url):
    """Admin handle on the fake TypeSafe, reset around every test."""

    class Admin:
        def fail(self, status: int, times: int = 1) -> None:
            _http("POST", f"{typesafe_url}/_admin/fail", {"status": status, "times": times})

        def log(self) -> list:
            with urllib.request.urlopen(f"{typesafe_url}/_admin/log", timeout=5) as response:
                return json.loads(response.read())

    _http("POST", f"{typesafe_url}/_admin/reset", {})
    yield Admin()
    _http("POST", f"{typesafe_url}/_admin/reset", {})


async def create_provider(aexecute, kind: str, api_base: str, api_key=None, context=None) -> dict:
    result = await aexecute(CREATE_PROVIDER, {"input": {"kind": kind, "apiBase": api_base, "apiKey": api_key}}, context=context)
    assert result.errors is None, result.errors
    return result.data["createProvider"]


def model_id_of(provider: dict, name: str) -> str:
    return next(m["id"] for m in provider["models"] if m["modelId"] == name)


@sync_to_async
def usage_rows(org_slug="static_org", endpoint=None):
    rows = llm_models.UsageRecord.objects.for_organization(Organization.objects.get(slug=org_slug)).order_by("id")
    if endpoint:
        rows = rows.filter(endpoint=endpoint)
    return list(rows)


@pytest_asyncio.fixture
async def ollaya(aexecute, ollaya_url):
    return await create_provider(aexecute, "OLLAYA", ollaya_url)


@pytest_asyncio.fixture
async def typesafe(aexecute, typesafe_url, faketypesafe):
    return await create_provider(aexecute, "TYPESAFE", typesafe_url, TYPESAFE_KEY)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_decision_providers_list_their_models_as_decision_only(ollaya, typesafe):
    assert ollaya["kind"] == "OLLAYA"
    assert {m["modelId"] for m in ollaya["models"]} >= {OLLAYA_MODEL}
    assert {m["modelId"] for m in typesafe["models"]} == {"jev-1.13.0", "jev-latest"}
    for model in ollaya["models"] + typesafe["models"]:
        assert model["features"] == ["DECISION"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_pull_into_ollaya_registers_the_model(aexecute, ollaya):
    result = await aexecute(
        "mutation Pull($input: PullInput!) { pull(input: $input) { status detail } }",
        {"input": {"modelName": OLLAYA_MODEL, "provider": ollaya["id"]}},
    )
    assert result.errors is None, result.errors
    assert result.data["pull"] == {"status": "success", "detail": None}

    unknown = await aexecute(
        "mutation Pull($input: PullInput!) { pull(input: $input) { status detail } }",
        {"input": {"modelName": "no-such-model:latest", "provider": ollaya["id"]}},
    )
    assert unknown.data["pull"]["status"] == "error"


# ---------------------------------------------------------------------------
# decide over GraphQL
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_decide_on_a_real_ollaya_model(aexecute, ollaya):
    result = await aexecute(DECIDE, {"input": {"model": model_id_of(ollaya, OLLAYA_MODEL), "state": TICKET, "questions": TRIAGE}})
    assert result.errors is None, result.errors
    decision = result.data["decide"]

    assert decision["model"] == OLLAYA_MODEL
    urgent, department, frustration = decision["answers"]
    assert (urgent["__typename"], urgent["key"]) == ("NoulAnswer", "urgent")
    assert 0 <= urgent["noul"] <= 1
    assert (department["__typename"], department["choice"]) == ("ChoiceAnswer", "billing")
    assert [p["key"] for p in department["probabilities"]] == ["billing", "technical", "sales"]
    assert sum(p["probability"] for p in department["probabilities"]) == pytest.approx(1, abs=0.01)
    assert frustration["__typename"] == "ScoreAnswer"
    assert [(level["level"], level["description"]) for level in frustration["levels"]] == [(0, "Calm"), (1, "Frustrated"), (2, "Very angry")]
    assert 0 <= frustration["score"] <= 2

    (row,) = await usage_rows(endpoint="graphql_decide")
    assert row.status == "ok"
    assert row.provider_kind == "ollaya"
    assert row.prompt_tokens == decision["usage"]["promptTokens"] > 0
    assert row.cost == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_decide_accepts_a_json_object_as_state(aexecute, ollaya):
    state = {"subject": "Invoice 2026-114", "body": "Please pay the attached invoice."}
    question = [{"choice": {"key": "topic", "instructions": "What is this email about?", "options": [{"key": "billing"}, {"key": "other"}]}}]
    result = await aexecute(DECIDE, {"input": {"model": model_id_of(ollaya, OLLAYA_MODEL), "state": state, "questions": question}})
    assert result.errors is None, result.errors
    assert result.data["decide"]["answers"][0]["choice"] == "billing"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_decide_on_typesafe_forwards_the_key_and_prices_input_tokens(aexecute, typesafe, faketypesafe):
    result = await aexecute(DECIDE, {"input": {"model": model_id_of(typesafe, "jev-latest"), "state": TICKET, "questions": TRIAGE}})
    assert result.errors is None, result.errors
    decision = result.data["decide"]
    assert decision["model"] == "jev-1.13.0"  # the alias resolved upstream
    assert [a["key"] for a in decision["answers"]] == ["urgent", "department", "frustration"]

    (call,) = faketypesafe.log()
    assert call["authorization"] == f"Bearer {TYPESAFE_KEY}"
    assert call["body"]["model"] == "jev-latest"
    assert call["body"]["questions"]["urgent"] == {"type": "noul", "instructions": "Does this convey urgency?", "criteria": {"true": "Explicitly time-sensitive", "false": "No urgency expressed"}}
    assert call["body"]["questions"]["frustration"]["criteria"] == ["Calm", "Frustrated", "Very angry"]

    (row,) = await usage_rows(endpoint="graphql_decide")
    assert row.provider_kind == "typesafe"
    assert row.cost == Decimal("0.042") * row.prompt_tokens / Decimal(1_000_000)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_overloaded_upstream_is_retried(aexecute, typesafe, faketypesafe):
    faketypesafe.fail(529, times=2)
    result = await aexecute(DECIDE, {"input": {"model": model_id_of(typesafe, "jev-1.13.0"), "state": TICKET, "questions": TRIAGE[:1]}})
    assert result.errors is None, result.errors
    assert len(faketypesafe.log()) == 3


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_backend_refusal_is_the_error_and_is_recorded(aexecute, typesafe, faketypesafe):
    # Two to ten levels is TypeSafe's limit, not alpaka's: the backend decides.
    question = [{"score": {"key": "urgency", "instructions": "How urgent?", "levels": ["Only level"]}}]
    result = await aexecute(DECIDE, {"input": {"model": model_id_of(typesafe, "jev-1.13.0"), "state": TICKET, "questions": question}})
    assert result.errors
    message = result.errors[0].message
    assert "422" in message and "2 to 10 levels" in message

    (row,) = await usage_rows(endpoint="graphql_decide")
    assert row.status == "error"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_duplicate_question_keys_are_rejected_before_any_call(aexecute, typesafe, faketypesafe):
    questions = [{"noul": {"key": "same", "instructions": "a?"}}, {"noul": {"key": "same", "instructions": "b?"}}]
    result = await aexecute(DECIDE, {"input": {"model": model_id_of(typesafe, "jev-1.13.0"), "state": TICKET, "questions": questions}})
    assert result.errors and "used twice" in result.errors[0].message
    assert faketypesafe.log() == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_question_must_be_exactly_one_kind(aexecute, typesafe):
    both = [{"noul": {"key": "a", "instructions": "a?"}, "score": {"key": "b", "instructions": "b?", "levels": ["x", "y"]}}]
    result = await aexecute(DECIDE, {"input": {"model": model_id_of(typesafe, "jev-1.13.0"), "state": TICKET, "questions": both}})
    assert result.errors


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_decide_without_a_model_uses_the_default_decision_model(aexecute, typesafe):
    missing = await aexecute(DECIDE, {"input": {"state": TICKET, "questions": TRIAGE[:1]}})
    assert missing.errors and "decision" in missing.errors[0].message

    used = await aexecute(
        "mutation Use($input: UseModelForInput!) { useModelFor(input: $input) { kind } }",
        {"input": {"model": model_id_of(typesafe, "jev-1.13.0"), "kind": "DECISION"}},
    )
    assert used.errors is None, used.errors
    result = await aexecute(DECIDE, {"input": {"state": TICKET, "questions": TRIAGE[:1]}})
    assert result.errors is None, result.errors
    assert result.data["decide"]["model"] == "jev-1.13.0"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_models_stay_on_their_side_of_chat_and_decide(aexecute, typesafe):
    org = await sync_to_async(Organization.objects.get)(slug="static_org")
    provider = await llm_models.Provider.objects.for_write().acreate(name="OpenAI", organization=org, kind="openai", api_key="sk-test", api_base="https://api.openai.com/v1")
    chat_model = await llm_models.LLMModel.objects.for_write().acreate(provider=provider, model_id="gpt-4o-mini", label="GPT-4o mini", features=["chat"])

    refused = await aexecute(DECIDE, {"input": {"model": str(chat_model.id), "state": TICKET, "questions": TRIAGE[:1]}})
    assert refused.errors and "not a decision model" in refused.errors[0].message

    chat = await aexecute(
        "mutation Chat($input: ChatInput!) { chat(input: $input) { id } }",
        {"input": {"model": model_id_of(typesafe, "jev-1.13.0"), "messages": [{"role": "USER", "content": "hi"}]}},
    )
    assert chat.errors and "is a decision model" in chat.errors[0].message


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_spent_budget_blocks_decide(aexecute, typesafe, faketypesafe):
    org = await sync_to_async(Organization.objects.get)(slug="static_org")
    await llm_models.Budget.objects.for_write().acreate(organization=org, limit_tokens=0, hard=True)
    result = await aexecute(DECIDE, {"input": {"model": model_id_of(typesafe, "jev-1.13.0"), "state": TICKET, "questions": TRIAGE[:1]}})
    assert result.errors and "Budget" in result.errors[0].message
    assert faketypesafe.log() == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_another_organization_cannot_decide_with_this_organizations_model(aexecute, typesafe, other_org_context, faketypesafe):
    result = await aexecute(DECIDE, {"input": {"model": model_id_of(typesafe, "jev-1.13.0"), "state": TICKET, "questions": TRIAGE[:1]}}, context=other_org_context)
    assert result.errors
    assert faketypesafe.log() == []


# ---------------------------------------------------------------------------
# The systemone REST surface, through the TypeSafe SDK
# ---------------------------------------------------------------------------


def sdk_client(**kwargs) -> AsyncTypeSafeClient:
    """The stock TypeSafe SDK, pointed at alpaka with an alpaka token as its key."""
    return AsyncTypeSafeClient(api_key="test", base_url="http://testserver/llm/systemone", transport=httpx2.ASGITransport(app=ASGI_APP), **kwargs)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_typesafe_sdk_works_against_alpaka(ollaya, typesafe, faketypesafe):
    async with sdk_client() as client:
        listed = await client.models.list()
        assert {m.name for m in listed.models} >= {OLLAYA_MODEL, "jev-1.13.0", "jev-latest"}

        result = await client.system_one(
            TICKET,
            {
                "urgent": Noul(instructions="Does this convey urgency?"),
                "department": Choice(instructions="Which team should handle this?", criteria={"billing": "payments and payouts", "technical": "bugs", "sales": "buying"}),
                "frustration": Score(instructions="How frustrated is the customer?", criteria=["Calm", "Frustrated", "Very angry"]),
            },
            model=OLLAYA_MODEL,
        )
    assert result.choices["department"].choice == "billing"
    assert 0 <= result.nouls["urgent"].noul <= 1
    assert list(result.scores["frustration"].legend.values()) == ["Calm", "Frustrated", "Very angry"]

    (row,) = await usage_rows(endpoint="rest_decide")
    assert row.provider_kind == "ollaya"
    assert faketypesafe.log() == []  # the Ollaya model was used, not TypeSafe


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_rest_surface_hides_upstream_credentials_and_relays_refusals(typesafe, faketypesafe):
    async with sdk_client(retry=RetryPolicy(max_retries=0)) as client:
        await client.system_one(TICKET, {"urgent": Noul(instructions="Urgent?")}, model="jev-1.13.0")
        with pytest.raises(TypeSafeAPIError) as refused:
            await client.system_one(TICKET, {"urgency": Score(instructions="How urgent?", criteria=["Only level"])}, model="jev-1.13.0")
        with pytest.raises(TypeSafeAPIError) as unknown:
            await client.system_one(TICKET, {"urgent": Noul(instructions="Urgent?")}, model="no-such-model")

    assert refused.value.status == 422
    assert "2 to 10 levels" in str(refused.value)
    assert unknown.value.status == 404
    # alpaka's token went to alpaka; the organization's TypeSafe key went upstream.
    assert {call["authorization"] for call in faketypesafe.log()} == {f"Bearer {TYPESAFE_KEY}"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_spent_budget_answers_402_so_the_sdk_does_not_retry(typesafe, faketypesafe):
    org = await sync_to_async(Organization.objects.get)(slug="static_org")
    await llm_models.Budget.objects.for_write().acreate(organization=org, limit_tokens=0, hard=True)
    async with sdk_client() as client:
        with pytest.raises(TypeSafeAPIError) as refused:
            await client.system_one(TICKET, {"urgent": Noul(instructions="Urgent?")}, model="jev-1.13.0")
    assert refused.value.status == 402
    assert faketypesafe.log() == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_openai_routes_neither_list_nor_call_decision_models(typesafe):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ASGI_APP), base_url="http://testserver", headers={"Authorization": "Bearer test"}) as http:
        listed = await http.get("/llm/v1/models")
        assert listed.status_code == 200
        assert not [m for m in listed.json()["data"] if m["root"].startswith("jev")]

        chat = await http.post("/llm/v1/chat/completions", json={"model": "jev-1.13.0", "messages": [{"role": "user", "content": "hi"}]})
        assert chat.status_code == 400
        assert chat.json()["error"]["code"] == "model_not_generative"
