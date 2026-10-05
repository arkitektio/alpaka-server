"""alpaka as a service of the hub: what exists here (``arkitekt_service.service``).

Two separate declarations, read by rekuest from the service's manifest (``*service.urls`` in
``urls.py``) and catalogued hub-wide:

* the **structures** alpaka hosts, and the descriptors of their objects. The GraphQL types answer
  ``descriptors`` from the same declarations (``alpaka_server.descriptors``);
* the **signals** it emits: which saves and deletes are announced, with no emit in the mutations.
  Users' triggers are checked against the kinds and descriptor keys declared here.

Hosting announces nothing by itself: a structure with no signal below is hosted silently.

That is all a service is. What can be *done* in this process is not declared here: that is an
agent's to say (``alpaka_server.hook_agent``), a different thing with its own configuration.
"""


from kammer import models as kammer_models
from vector import models as vector_models
from llm import models as llm_models
from arkitekt_service.service import Descriptor, Service, organization_of

service = Service("alpaka", description="LLM rooms and vector collections.")


# --- Structures: what alpaka hosts ----------------------------------------------------

room = service.structure(
    kammer_models.Room,
    "@alpaka/room",
    description="A room: a conversation between users and agents.",
)
message = service.structure(
    kammer_models.Message,
    "@alpaka/message",
    descriptors=(
        Descriptor("@alpaka/from_agent", "BOOL", "Whether an agent posted it"),
        Descriptor("@alpaka/is_reply", "BOOL", "Whether it replies to another message"),
    ),
    describe=lambda message: {"@alpaka/from_agent": message.agent_id is not None, "@alpaka/is_reply": message.is_reply_to_id is not None},
    description="A message an agent posted in a room.",
)
llmmodel = service.structure(
    llm_models.LLMModel,
    "@alpaka/llmmodel",
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
)
chromacollection = service.structure(
    vector_models.ChromaCollection,
    "@alpaka/chromacollection",
    description="A vector collection: documents searchable by meaning.",
)
# No descriptors: a provider row holds an API key, and nothing about it belongs in a signal.
provider = service.structure(
    llm_models.Provider,
    "@alpaka/provider",
    description="A provider of language models, as configured by an organization.",
)


# --- Signals: what alpaka announces ----------------------------------------------------
# A streamed reply is saved token by token: it is announced once, when it is done
# (``is_streaming`` false) — never per delta.

CREATED_UPDATED = ("CREATED", "UPDATED")
CREATED_DELETED = ("CREATED", "DELETED")
org = organization_of()

service.model_signal(
    room,
    kinds=CREATED_DELETED,
    organization=org,
    description="A room (a conversation) was created or deleted.",
)
service.model_signal(
    message,
    kinds=CREATED_UPDATED,
    organization=organization_of("room.organization"),
    when=lambda message, kind: not message.is_streaming,
    description="A message was posted in a room (a streamed reply: once it finished).",
)
service.model_signal(
    llmmodel,
    kinds=CREATED_UPDATED,
    organization=organization_of("provider.organization"),
    description="A language model became available or changed (e.g. after a provider refresh).",
)
service.model_signal(
    chromacollection,
    kinds=CREATED_DELETED,
    organization=org,
    description="A vector collection was created or deleted.",
)
service.model_signal(
    provider,
    kinds=CREATED_UPDATED,
    organization=org,
    description="An LLM provider was added or changed.",
)
