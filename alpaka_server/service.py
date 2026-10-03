"""alpaka as the hub's rekuest sees it (vendored ``rekuest_service``): the service, and its HookAgent.

Two declarations, read by rekuest from one manifest and mounted by ``urls.py`` (``*service.urls``):

* the **service** says what exists: the structures alpaka hosts, the descriptors of their objects,
  and — every save and delete being announced, with no emit in the mutations — the signals it
  emits. Hub-wide; users' triggers are checked against the kinds and descriptor keys declared here,
  and the GraphQL types answer ``descriptors`` from the same declarations (``alpaka_server.descriptors``);
* its **agent** says what can be done: the actions rekuest runs here. Every organization has the
  agent and its own schedules, so an action does one organization's share of the work.

Nothing here loops: each run is one pass rekuest started, and a lost run is followed by the next.
"""

from django.conf import settings

from kammer import models as kammer_models
from vector import models as vector_models
from embeddings import engine
from embeddings.healer import reembed_all
from llm import models as llm_models
from rekuest_service import Descriptor, HookAgent, Service, organization_of

service = Service("alpaka", description="LLM rooms and vector collections.")

# The models whose name + description are embedded (see ``embeddings.healer``).
_EMBEDDED_MODELS = (kammer_models.Room, vector_models.ChromaCollection)


# --- Structures ---------------------------------------------------------------------------
# What alpaka hosts, and announces to the hub's rekuest. A streamed reply is saved token by
# token: it is announced once, when it is done (``is_streaming`` false) — never per delta.

CREATED_UPDATED = ("CREATED", "UPDATED")
CREATED_DELETED = ("CREATED", "DELETED")
org = organization_of()

service.structure(
    kammer_models.Room,
    "@alpaka/room",
    kinds=CREATED_DELETED,
    organization=org,
    description="A room: a conversation between users and agents.",
    signal_description="A room (a conversation) was created or deleted.",
)
service.structure(
    kammer_models.Message,
    "@alpaka/message",
    kinds=CREATED_UPDATED,
    organization=organization_of("room.organization"),
    when=lambda message, kind: not message.is_streaming,
    descriptors=(
        Descriptor("@alpaka/from_agent", "BOOL", "Whether an agent posted it"),
        Descriptor("@alpaka/is_reply", "BOOL", "Whether it replies to another message"),
    ),
    describe=lambda message: {"@alpaka/from_agent": message.agent_id is not None, "@alpaka/is_reply": message.is_reply_to_id is not None},
    description="A message an agent posted in a room.",
    signal_description="A message was posted in a room (a streamed reply: once it finished).",
)
service.structure(
    llm_models.LLMModel,
    "@alpaka/llmmodel",
    kinds=CREATED_UPDATED,
    organization=organization_of("provider.organization"),
    descriptors=(
        Descriptor("@alpaka/features", "LIST", "What it can do (chat, embedding, ...)"),
        Descriptor("@alpaka/input_modalities", "LIST", "The modalities it accepts as input"),
        Descriptor("@alpaka/output_modalities", "LIST", "The modalities it produces as output"),
    ),
    describe=lambda model: {
        "@alpaka/features": list(model.features or []),
        "@alpaka/input_modalities": list(model.input_modalities or []),
        "@alpaka/output_modalities": list(model.output_modalities or []),
    },
    description="A language model reachable through one of the organization's providers.",
    signal_description="A language model became available or changed (e.g. after a provider refresh).",
)
service.structure(
    vector_models.ChromaCollection,
    "@alpaka/chromacollection",
    kinds=CREATED_DELETED,
    organization=org,
    description="A vector collection: documents searchable by meaning.",
    signal_description="A vector collection was created or deleted.",
)
# No descriptors: a provider row holds an API key, and nothing about it belongs in a signal.
service.structure(
    llm_models.Provider,
    "@alpaka/provider",
    kinds=CREATED_UPDATED,
    organization=org,
    description="A provider of language models, as configured by an organization.",
    signal_description="An LLM provider was added or changed.",
)


# --- The HookAgent ------------------------------------------------------------------------

agent = HookAgent(service)


@agent.action(
    interface="reembed_stale",
    name="Re-embed stale rows",
    description="Re-embed every row of the organization whose vector was produced by another embedding model, or by none.",
    # Scheduled only where embeddings are on; ``embeddings.sweep_interval`` is its cadence.
    default_interval=settings.EMBEDDINGS["SWEEP_INTERVAL"] if engine.enabled() else None,
)
def reembed_stale(organization: str) -> dict:
    """One pass over the organization's embedded rows, in row-locked batches (N replicas may run it at once)."""
    return {"reembedded": reembed_all(_EMBEDDED_MODELS, max_batches=50, organization=organization)}
