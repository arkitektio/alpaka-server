"""Embedding calls routed through the model's own provider.

Every embedding request used to be sent to ``settings.OLLAMA_URL`` regardless of
which provider the embedder belonged to, so any OpenAI/OpenRouter embedder was
silently pointed at Ollama. Routing goes through the model's provider here, the
same way ``llm.graphql.mutations.chat`` already routes completions.
"""

from typing import List, Optional, Sequence

from asgiref.sync import sync_to_async
from authentikate.models import Client, Organization, User
from litellm import aembedding

from llm.enums import UsageEndpoint
from llm.errors import wrap_llm_errors
from llm.models import LLMModel
from llm.usage import aenforce_budget, atrack_usage

#: Ceiling on a single embedding call. Alpaka is a gateway in front of upstreams
#: it does not control, so an unbounded wait would hold a worker indefinitely.
EMBEDDING_TIMEOUT_SECONDS = 120


@sync_to_async
def _organization_of(embedder: LLMModel) -> Organization:
    # Callers select_related the provider; the organization may still need a
    # query, which cannot run on the event loop.
    return embedder.provider.organization


async def aembed_texts(embedder: LLMModel, texts: Sequence[str], *, user: Optional[User] = None, client: Optional[Client] = None) -> List[List[float]]:
    """Embed ``texts`` with ``embedder``, using that model's provider credentials.

    The call is budget-checked and recorded against the embedder's organization;
    pass ``user``/``client`` so the record says who triggered it.
    """
    organization = await _organization_of(embedder)
    await aenforce_budget(organization, user, embedder)

    async with atrack_usage(organization=organization, user=user, client=client, model=embedder, endpoint=UsageEndpoint.VECTOR_EMBEDDING) as track:
        with wrap_llm_errors(embedder):
            response = await aembedding(
                embedder.llm_string,
                list(texts),
                api_base=embedder.provider.api_base,
                api_key=embedder.provider.api_key,
                timeout=EMBEDDING_TIMEOUT_SECONDS,
            )
        track.set(response, call_type="embedding")

    return [item["embedding"] for item in response.data]
