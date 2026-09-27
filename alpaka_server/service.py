"""alpaka as the hub's rekuest sees it: the actions it offers, the signals it emits (vendored ``rekuest_service``).

Like an arkitekt ``App``: one ``Service`` declaration, mounted by ``urls.py`` (``*service.urls``),
read by rekuest from the manifest. Nothing here loops: each run is one pass rekuest started, and
a lost run is followed by the next.
"""

from django.conf import settings

from kammer import models as kammer_models
from vector import models as vector_models
from embeddings import engine
from embeddings.healer import reembed_all
from llm import models as llm_models
from rekuest_service import Service, organization_of

service = Service("alpaka", description="LLM rooms and vector collections.")

# The models whose name + description are embedded (see ``embeddings.healer``).
_EMBEDDED_MODELS = (kammer_models.Room, vector_models.ChromaCollection)


# --- Signals ------------------------------------------------------------------------------
# What alpaka announces to the hub's rekuest. A streamed reply is saved token by token: it is
# announced once, when it is done (``is_streaming`` false) — never per delta.

service.model_signal(kammer_models.Room, "@alpaka/room", kinds=("CREATED", "DELETED"), organization=organization_of(), description="A room (a conversation) was created or deleted.")
service.model_signal(
    kammer_models.Message, "@alpaka/message", kinds=("CREATED", "UPDATED"), organization=organization_of("room.organization"),
    when=lambda message, kind: not message.is_streaming,
    descriptors=lambda message: {"@alpaka/from_agent": message.agent_id is not None, "@alpaka/is_reply": message.is_reply_to_id is not None},
    descriptor_keys=("@alpaka/from_agent", "@alpaka/is_reply"),
    description="A message was posted in a room (a streamed reply: once it finished).",
)
service.model_signal(
    llm_models.LLMModel, "@alpaka/llmmodel", kinds=("CREATED", "UPDATED"), organization=organization_of("provider.organization"),
    descriptors=lambda model: {"@alpaka/features": list(model.features or []), "@alpaka/input_modalities": list(model.input_modalities or []), "@alpaka/output_modalities": list(model.output_modalities or [])},
    descriptor_keys=("@alpaka/features", "@alpaka/input_modalities", "@alpaka/output_modalities"),
    description="A language model became available or changed (e.g. after a provider refresh).",
)
service.model_signal(vector_models.ChromaCollection, "@alpaka/chromacollection", kinds=("CREATED", "DELETED"), organization=organization_of(), description="A vector collection was created or deleted.")
# No descriptors: a provider row holds an API key, and nothing about it belongs in a signal.
service.model_signal(llm_models.Provider, "@alpaka/provider", kinds=("CREATED", "UPDATED"), organization=organization_of(), description="An LLM provider was added or changed.")


@service.action(
    interface="reembed_stale",
    name="Re-embed stale rows",
    description="Re-embed every row whose vector was produced by another embedding model, or by none.",
    # Scheduled only where embeddings are on; ``embeddings.sweep_interval`` is its cadence.
    default_interval=settings.EMBEDDINGS["SWEEP_INTERVAL"] if engine.enabled() else None,
)
def reembed_stale() -> dict:
    """One pass over every embedded model, in row-locked batches (N replicas may run it at once)."""
    return {"reembedded": reembed_all(_EMBEDDED_MODELS, max_batches=50)}
