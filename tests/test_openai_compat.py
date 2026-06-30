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
