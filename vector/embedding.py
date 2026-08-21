"""Embedding calls routed through the model's own provider.

Every embedding request used to be sent to ``settings.OLLAMA_URL`` regardless of
which provider the embedder belonged to, so any OpenAI/OpenRouter embedder was
silently pointed at Ollama. Routing goes through the model's provider here, the
same way ``llm.graphql.mutations.chat`` already routes completions.
"""

from typing import List, Sequence

from litellm import aembedding

from llm.errors import wrap_llm_errors
from llm.models import LLMModel

#: Ceiling on a single embedding call. Alpaka is a gateway in front of upstreams
#: it does not control, so an unbounded wait would hold a worker indefinitely.
EMBEDDING_TIMEOUT_SECONDS = 120


async def aembed_texts(embedder: LLMModel, texts: Sequence[str]) -> List[List[float]]:
    """Embed ``texts`` with ``embedder``, using that model's provider credentials."""
    with wrap_llm_errors(embedder):
        response = await aembedding(
            embedder.llm_string,
            list(texts),
            api_base=embedder.provider.api_base,
            api_key=embedder.provider.api_key,
            timeout=EMBEDDING_TIMEOUT_SECONDS,
        )

    return [item["embedding"] for item in response.data]
