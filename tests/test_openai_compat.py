"""Wire-compatibility tests for alpaka's OpenAI-compatible REST endpoints
(``llm/views.py``) against the installed ``openai`` client.

These drive the real Django ASGI app in-process through ``httpx.ASGITransport``
and parse the responses with the actual ``openai.AsyncOpenAI`` client, so they
fail if the client and our wire format ever drift (e.g. after an ``openai``
major bump). litellm's built-in ``mock_response`` produces authentic
OpenAI-shaped payloads, so no upstream provider, database, or auth is involved.

Needs Django configured (``DJANGO_SETTINGS_MODULE``) but no database; run with
``uv run pytest tests/test_openai_compat.py``.
"""

import copy
import types

import httpx
import litellm
import openai
import pytest
from django.core.asgi import get_asgi_application
from openai import AsyncOpenAI

import llm.views as views

# The Django ASGI application is process-wide and DB-free to build.
ASGI_APP = get_asgi_application()

FAKE_PROVIDER = types.SimpleNamespace(
    name="openrouter", kind="OPENROUTER",
    api_base="https://openrouter.ai/api/v1", api_key="sk-test",
)
FAKE_MODEL = types.SimpleNamespace(
    llm_string="openrouter/gpt-4", model_id="gpt-4",
    provider=FAKE_PROVIDER, is_available=True,
)


async def _fake_auth(request):
    user = types.SimpleNamespace(id=1)
    return (user, user, user)


async def _fake_model_lookup(*args, **kwargs):
    return FAKE_MODEL


async def _noop(*args, **kwargs):
    return None


def _mock_litellm(monkeypatch, *, text="Hello world from mock", error=None):
    """Patch the litellm entry points used by the views to return canned,
    OpenAI-shaped output via ``mock_response`` (or raise ``error``)."""
    orig_ac, orig_at, orig_ae = (
        litellm.acompletion, litellm.atext_completion, litellm.aembedding,
    )

    def wrap(orig, mock_value):
        async def inner(**kw):
            if error is not None:
                raise error
            kw["mock_response"] = mock_value
            return await orig(**kw)
        return inner

    monkeypatch.setattr(views.litellm, "acompletion", wrap(orig_ac, text))
    monkeypatch.setattr(views.litellm, "atext_completion", wrap(orig_at, text))
    monkeypatch.setattr(views.litellm, "aembedding", wrap(orig_ae, [[0.1, 0.2, 0.3]]))


@pytest.fixture
def client(monkeypatch):
    """An ``AsyncOpenAI`` client wired to the in-process Django ASGI app, with
    auth and model-lookup boundaries stubbed out."""
    monkeypatch.setattr(views, "authenticate_request", _fake_auth)
    monkeypatch.setattr(views, "get_model_by_id_or_name", _fake_model_lookup)
    monkeypatch.setattr(views, "get_default_model", _fake_model_lookup)
    # Usage accounting and budgets need the database; tests/test_usage.py
    # covers them with real rows.
    monkeypatch.setattr(views, "aenforce_budget", _noop)
    monkeypatch.setattr(views, "arecord_usage", _noop)
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ASGI_APP), base_url="http://testserver"
    )
    oai = AsyncOpenAI(api_key="test", base_url="http://testserver/llm/v1", http_client=http_client)
    yield oai


@pytest.mark.asyncio
async def test_chat_completion_non_streaming(client, monkeypatch):
    """A non-streamed chat completion parses into ``ChatCompletion``."""
    _mock_litellm(monkeypatch)
    resp = await client.chat.completions.create(
        model="x", messages=[{"role": "user", "content": "hi"}]
    )
    assert resp.object == "chat.completion"
    assert resp.choices[0].message.role == "assistant"
    assert resp.choices[0].message.content == "Hello world from mock"


@pytest.mark.asyncio
async def test_chat_completion_streaming(client, monkeypatch):
    """A streamed chat completion: every event parses into a
    ``ChatCompletionChunk``, the deltas reassemble, and ``[DONE]`` terminates the
    stream without the client raising."""
    _mock_litellm(monkeypatch)
    stream = await client.chat.completions.create(
        model="x", messages=[{"role": "user", "content": "hi"}], stream=True
    )
    chunks, text = 0, ""
    async for chunk in stream:
        assert chunk.object == "chat.completion.chunk"
        if chunk.choices and chunk.choices[0].delta.content:
            text += chunk.choices[0].delta.content
        chunks += 1
    assert chunks > 1  # genuinely chunked, not a single blob
    assert text == "Hello world from mock"


@pytest.mark.asyncio
async def test_legacy_text_completion_streaming(client, monkeypatch):
    """The legacy ``/v1/completions`` endpoint streams ``text_completion``
    chunks the client can parse."""
    _mock_litellm(monkeypatch)
    stream = await client.completions.create(model="x", prompt="hi", stream=True)
    chunks = 0
    async for chunk in stream:
        assert chunk.object == "text_completion"
        chunks += 1
    assert chunks >= 1


@pytest.mark.asyncio
async def test_embeddings(client, monkeypatch):
    """Embeddings parse into ``CreateEmbeddingResponse``."""
    _mock_litellm(monkeypatch)
    emb = await client.embeddings.create(model="x", input="hello")
    assert emb.object == "list"
    assert len(emb.data) >= 1
    assert isinstance(emb.data[0].embedding, list)


@pytest.mark.asyncio
async def test_upstream_403_surfaces_as_typed_client_error(client, monkeypatch):
    """An upstream 403 (the reported Sakana case) flows through
    ``litellm_error_response`` and is raised by the client as the typed
    ``PermissionDeniedError`` with the verbose message intact."""
    err = litellm.exceptions.APIError(
        status_code=403,
        message="OpenrouterException - 403 Forbidden (Sakana AI)",
        llm_provider="openrouter",
        model="gpt-4",
    )
    _mock_litellm(monkeypatch, error=err)
    with pytest.raises(openai.PermissionDeniedError) as excinfo:
        await client.chat.completions.create(
            model="x", messages=[{"role": "user", "content": "hi"}]
        )
    assert excinfo.value.status_code == 403
    assert "openrouter" in str(excinfo.value)
    assert "Sakana AI" in str(excinfo.value)


@pytest.mark.asyncio
async def test_upstream_403_streaming_fails_before_first_byte(client, monkeypatch):
    """With ``stream=True`` the upstream call is awaited before the SSE
    response is constructed, so a pre-stream failure surfaces as a real HTTP
    status the client raises on — not a 200 whose body carries an error frame."""
    err = litellm.exceptions.APIError(
        status_code=403,
        message="OpenrouterException - 403 Forbidden (Sakana AI)",
        llm_provider="openrouter",
        model="gpt-4",
    )
    _mock_litellm(monkeypatch, error=err)
    with pytest.raises(openai.PermissionDeniedError):
        await client.chat.completions.create(
            model="x", messages=[{"role": "user", "content": "hi"}], stream=True
        )


@pytest.mark.asyncio
async def test_sdk_params_pass_through_but_reserved_keys_do_not(client, monkeypatch):
    """Body params we never enumerated (``seed``) reach litellm verbatim, while
    routing/credential keys smuggled via ``extra_body`` are dropped in favor of
    the resolved provider's own."""
    seen = {}
    orig = litellm.acompletion

    async def spy(**kw):
        seen.update(kw)
        kw["mock_response"] = "ok"
        return await orig(**kw)

    monkeypatch.setattr(views.litellm, "acompletion", spy)
    await client.chat.completions.create(
        model="x",
        messages=[{"role": "user", "content": "hi"}],
        seed=7,
        extra_body={"api_base": "http://evil.example", "custom_llm_provider": "evil"},
    )
    assert seen["seed"] == 7
    assert seen["api_base"] == FAKE_PROVIDER.api_base
    assert seen["api_key"] == FAKE_PROVIDER.api_key
    assert "custom_llm_provider" not in seen


@pytest.mark.asyncio
async def test_custom_pricing_never_reaches_litellm(client, monkeypatch):
    """The harm, not just the mechanism.

    ``input_cost_per_token``/``output_cost_per_token`` make litellm call
    ``register_model``, which writes the *process-global* ``litellm.model_cost``
    map -- so a caller could zero its own recorded cost (defeating the cost budgets
    in ``llm.usage``) and re-price that model for every other organization sharing
    the worker. Asserting on the map survives any future refactor of the key set.
    """
    before = copy.deepcopy(litellm.model_cost.get("openrouter/gpt-4"))
    seen = {}
    orig = litellm.acompletion

    async def spy(**kw):
        seen.update(kw)
        kw["mock_response"] = "ok"
        return await orig(**kw)

    monkeypatch.setattr(views.litellm, "acompletion", spy)
    await client.chat.completions.create(
        model="x",
        messages=[{"role": "user", "content": "hi"}],
        extra_body={"input_cost_per_token": 0, "output_cost_per_token": 0},
    )

    assert "input_cost_per_token" not in seen and "output_cost_per_token" not in seen
    assert litellm.model_cost.get("openrouter/gpt-4") == before


@pytest.mark.parametrize("key,value", [
    ("mock_response", "free lunch"),
    ("num_retries", 50),
    ("fallbacks", [{"model": "someone/elses-model"}]),
    ("model_list", [{"model_name": "x"}]),
    ("caching", True),
    ("headers", {"x-smuggled": "1"}),
])
@pytest.mark.asyncio
async def test_litellm_control_params_are_not_forwarded(client, monkeypatch, key, value):
    """litellm accepts ~190 control kwargs; the tunnel forwards request params only."""
    seen = {}
    orig = litellm.acompletion

    async def spy(**kw):
        seen.update(kw)
        kw["mock_response"] = "ok"
        return await orig(**kw)

    monkeypatch.setattr(views.litellm, "acompletion", spy)
    await client.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}], extra_body={key: value})
    assert key not in seen


def test_the_reserved_key_set_has_not_drifted():
    """``all_litellm_params`` and ``OPENAI_CHAT_COMPLETION_PARAMS`` are litellm
    internals: a version bump can move a key between them silently."""
    forwarded = {"tools", "tool_choice", "response_format", "stream_options", "seed",
                 "logprobs", "max_completion_tokens", "parallel_tool_calls", "reasoning_effort"}
    assert forwarded & views.RESERVED_LITELLM_KEYS == set()

    blocked = {"api_key", "api_base", "base_url", "api_version", "extra_headers",
               "default_headers", "headers", "organization", "deployment_id", "max_retries",
               "input_cost_per_token", "output_cost_per_token", "mock_response",
               "fallbacks", "model_list", "caching", "num_retries"}
    assert blocked <= views.RESERVED_LITELLM_KEYS


@pytest.mark.asyncio
async def test_tool_calling_still_tunnels(client, monkeypatch):
    """The reserved set must not cost the tunnel its actual job."""
    seen = {}
    orig = litellm.acompletion

    async def spy(**kw):
        seen.update(kw)
        kw["mock_response"] = "ok"
        return await orig(**kw)

    monkeypatch.setattr(views.litellm, "acompletion", spy)
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {}}}}]
    await client.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}], tools=tools, tool_choice="auto")
    assert seen["tools"] == tools and seen["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_a_mid_stream_error_still_terminates_with_done(monkeypatch):
    """The status line is already 200 by then, so the error frame is all the client
    gets -- and without the sentinel a client looping until ``[DONE]`` hangs."""
    monkeypatch.setattr(views, "authenticate_request", _fake_auth)
    monkeypatch.setattr(views, "get_model_by_id_or_name", _fake_model_lookup)
    monkeypatch.setattr(views, "get_default_model", _fake_model_lookup)
    monkeypatch.setattr(views, "aenforce_budget", _noop)
    monkeypatch.setattr(views, "arecord_usage", _noop)

    class _Exploding:
        def __init__(self):
            self.sent = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.sent:
                raise RuntimeError("upstream died mid-stream")
            self.sent = True
            return types.SimpleNamespace(model_dump=lambda: {"id": "c", "choices": [{"index": 0, "delta": {"content": "hi"}}]})

    async def spy(**kw):
        return _Exploding()

    monkeypatch.setattr(views.litellm, "acompletion", spy)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ASGI_APP), base_url="http://testserver") as http:
        response = await http.post(
            "/llm/v1/chat/completions",
            json={"model": "x", "messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers={"Authorization": "Bearer test"},
        )
    frames = [line for line in response.text.splitlines() if line.startswith("data: ")]
    assert "upstream died mid-stream" in frames[-2]
    assert frames[-1] == "data: [DONE]"


@pytest.mark.asyncio
async def test_a_non_object_body_is_a_400_not_a_500(monkeypatch):
    monkeypatch.setattr(views, "authenticate_request", _fake_auth)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ASGI_APP), base_url="http://testserver") as http:
        # ``null`` parses fine and then reached ``"messages" not in payload`` as a
        # TypeError -- Django's HTML 500, not an OpenAI-shaped error body. Sent as
        # raw content because httpx reads ``json=None`` as "no body at all".
        response = await http.post(
            "/llm/v1/chat/completions",
            content=b"null",
            headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


@pytest.mark.asyncio
async def test_streamed_completions_ask_the_upstream_for_usage(client, monkeypatch):
    """Without ``include_usage`` a streamed ``/v1/completions`` can only ever be
    counted with a tiktoken estimate, so cost budgets under-count it."""
    seen = {}
    orig = litellm.atext_completion

    async def spy(**kw):
        seen.update(kw)
        kw["mock_response"] = "hello"
        return await orig(**kw)

    monkeypatch.setattr(views.litellm, "atext_completion", spy)
    stream = await client.completions.create(model="x", prompt="hi", stream=True)
    async for _ in stream:
        pass
    assert seen["stream_options"] == {"include_usage": True}
    assert seen["drop_params"] is True
