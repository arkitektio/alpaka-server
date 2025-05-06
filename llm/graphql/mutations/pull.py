import strawberry
from typing import Optional
import aiohttp
from kante.types import Info


@strawberry.type
class OllamaPullResult:
    status: str  # e.g., "success", "already exists", etc.
    detail: Optional[str] = None


@strawberry.input
class PullInput:
    """Input for pulling a model from Ollama."""

    model_name: str


async def pull(info: Info, input: PullInput) -> OllamaPullResult:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("http://ollama:11434/api/pull", json={"name": input.model_name}) as res:
                if res.status == 200:
                    return OllamaPullResult(status="success")
                elif res.status == 409:
                    return OllamaPullResult(status="already exists")
                else:
                    data = await res.json()
                    return OllamaPullResult(status="error", detail=data.get("error", f"HTTP {res.status}"))
    except Exception as e:
        return OllamaPullResult(status="exception", detail=str(e))
