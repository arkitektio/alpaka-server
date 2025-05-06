import json
import aiohttp
from django.http import JsonResponse, StreamingHttpResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from authentikate.utils import authenticate_header_or_none
from authentikate.expand import aexpand_user_from_token, aexpand_client_from_token
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


OLLAMA_URL = settings.OLLAMA_URL

# JWT authentication placeholder
async def authenticate_request(request: HttpRequest) -> bool:
    logger.error("Registering agent", exc_info=True)
    token = authenticate_header_or_none(request.headers)
    if not token:
        raise ValueError("Invalid token")

    user = await aexpand_user_from_token(token)
    client = await aexpand_client_from_token(token)
    return user, client

@csrf_exempt
async def models_view(request: HttpRequest):
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)

    user, client = await authenticate_request(request)
    if not user or not client:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OLLAMA_URL}/api/tags") as res:
            data = await res.json()
            return JsonResponse(data)

@csrf_exempt
async def generate_view(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    if not await authenticate_request(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    stream = payload.get("stream", False)

    if stream:
        async def stream_response():
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{OLLAMA_URL}/api/generate", json=payload) as res:
                    async for line in res.content:
                        if line.startswith(b"data: "):
                            yield line[6:] + b"\n"

        return StreamingHttpResponse(stream_response(), content_type="text/event-stream")

    else:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{OLLAMA_URL}/api/generate", json=payload) as res:
                data = await res.json()
                return JsonResponse(data)

@csrf_exempt
async def chat_view(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    if not await authenticate_request(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{OLLAMA_URL}/api/chat", json=payload) as res:
            data = await res.json()
            return JsonResponse(data)
