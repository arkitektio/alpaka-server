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
            async with session.post(
                "http://ollama:11434/api/pull", 
                json={"name": input.model_name}
            ) as res:
                if res.status != 200:
                    try:
                        data = await res.json()
                        return OllamaPullResult(status="error", detail=data.get("error", f"HTTP {res.status}"))
                    except:
                        return OllamaPullResult(status="error", detail=f"HTTP {res.status}")

                # Process the streaming response
                async for line in res.content:
                    if not line:
                        continue
                    decoded = line.decode("utf-8").strip()
                    if decoded:
                        # You could log this or parse it with json.loads(decoded) if needed
                        print(decoded)
                        if '"status":"success"' in decoded:
                            return OllamaPullResult(status="success")
                
                # If the stream ends but "success" wasn't seen
                return OllamaPullResult(status="incomplete", detail="Pull stream ended without success message.")
                
    except Exception as e:
        return OllamaPullResult(status="exception", detail=str(e))