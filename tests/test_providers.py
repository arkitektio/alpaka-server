"""Creating providers: which kinds need an endpoint, and how their models are listed."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from asgiref.sync import sync_to_async

from llm import models as llm_models
from llm.graphql.mutations.provider import _resolve_api_base
from llm.logic import strip_routing_prefix

CREATE_PROVIDER = """
mutation Create($input: ProviderInput!) {
  createProvider(input: $input) { id kind apiBase models { id modelId } }
}
"""

#: Three models served one per page, so listing has to follow ``after_id``.
ANTHROPIC_MODELS = ["claude-a", "claude-b", "claude-c"]
ANTHROPIC_KEY = "sk-ant-test"


class _AnthropicModels(BaseHTTPRequestHandler):
    """Anthropic's ``GET /v1/models``: key header, one model per page, ``has_more``/``last_id``."""

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path != "/v1/models":
            self.send_error(404)
            return
        if self.headers.get("x-api-key") != ANTHROPIC_KEY:
            self._json(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
            return
        after = parse_qs(url.query).get("after_id", [None])[0]
        start = ANTHROPIC_MODELS.index(after) + 1 if after else 0
        page = ANTHROPIC_MODELS[start : start + 1]
        has_more = start + 1 < len(ANTHROPIC_MODELS)
        self._json(200, {"data": [{"id": model_id, "type": "model"} for model_id in page], "has_more": has_more, "last_id": page[-1] if page else None})

    def _json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def anthropic_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AnthropicModels)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_hosted_kinds_need_no_endpoint() -> None:
    """A hosted API is stored without an endpoint, so litellm uses its own."""
    assert _resolve_api_base("anthropic", None) is None
    assert _resolve_api_base("openai", None) is None
    assert _resolve_api_base("anthropic", "https://proxy.example") == "https://proxy.example"
    assert _resolve_api_base("openrouter", None) == "https://openrouter.ai/api/v1"


def test_routing_prefix_is_stripped_once() -> None:
    assert strip_routing_prefix("anthropic/claude-a", "anthropic") == "claude-a"
    assert strip_routing_prefix("claude-a", "anthropic") == "claude-a"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["AZURE", "CUSTOM"])
async def test_kinds_without_a_shared_endpoint_still_need_one(aexecute, kind: str) -> None:
    result = await aexecute(CREATE_PROVIDER, {"input": {"kind": kind, "apiKey": "key"}})
    assert result.errors is not None
    assert "Supply apiBase explicitly" in result.errors[0].message


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_anthropic_lists_every_page_and_routes_once(aexecute, anthropic_url: str) -> None:
    result = await aexecute(CREATE_PROVIDER, {"input": {"kind": "ANTHROPIC", "apiKey": ANTHROPIC_KEY, "apiBase": anthropic_url}})
    assert result.errors is None, result.errors

    provider = result.data["createProvider"]
    assert sorted(model["modelId"] for model in provider["models"]) == ANTHROPIC_MODELS

    # A test reads the row back outside any request, so across organizations.
    model = await sync_to_async(llm_models.LLMModel.all_objects.select_related("provider").get)(id=provider["models"][0]["id"])
    assert model.llm_string == f"anthropic/{model.model_id}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_rejected_anthropic_key_fails_creation(aexecute, anthropic_url: str) -> None:
    result = await aexecute(CREATE_PROVIDER, {"input": {"kind": "ANTHROPIC", "apiKey": "wrong", "apiBase": anthropic_url}})
    assert result.errors is not None
    assert "401" in result.errors[0].message
