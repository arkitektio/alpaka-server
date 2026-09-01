"""Auth-path tests for the OpenAI-compatible REST endpoints, through the REAL
``llm.views.authenticate_request``.

The wire-compat suite (``test_openai_compat.py``) stubs authentication out
wholesale, which is how a missing ``await`` on the async
``authenticate_header_or_none`` shipped: the truthy coroutine passed the guard,
expansion blew up, and every production request 401'd while tests stayed green.
These tests keep the auth boundary honest — the no-header case asserts the
*exact* early-return message (the coroutine bug 401'd too, but through the
expansion branch with a different message), and un-awaited coroutines are
escalated to errors.

The static-token test needs the database (token expansion get-or-creates the
user/org/client); the rest are DB-free.
"""

import httpx
import pytest
from django.core.asgi import get_asgi_application

ASGI_APP = get_asgi_application()

pytestmark = pytest.mark.filterwarnings(
    "error:coroutine.*was never awaited:RuntimeWarning"
)


@pytest.fixture
def http_client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ASGI_APP), base_url="http://testserver"
    )


@pytest.mark.asyncio
async def test_missing_header_is_401_with_early_return_message(http_client):
    resp = await http_client.get("/llm/v1/models")
    assert resp.status_code == 401
    assert (
        "Missing or invalid authentication token" in resp.json()["error"]["message"]
    )
    assert resp.json()["error"]["type"] == "authentication_error"


@pytest.mark.asyncio
async def test_garbage_bearer_is_401(http_client):
    resp = await http_client.get(
        "/llm/v1/models", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_chat_completions_without_auth_is_401(http_client):
    resp = await http_client.post(
        "/llm/v1/chat/completions",
        json={"model": "x", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_static_token_authenticates_models_endpoint(http_client, backend_stack):
    """The settings_test static token ``test`` traverses the real header parse,
    token validation and DB expansion, and reaches the endpoint proper."""
    resp = await http_client.get(
        "/llm/v1/models", headers={"Authorization": "Bearer test"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
