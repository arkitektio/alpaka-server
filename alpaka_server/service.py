"""alpaka as a service of the hub: the models and the code behind what its contract says it hosts.

What exists here (the structures, the descriptors of their objects, the signals and their kinds)
is declared once, as data, in ``alpaka_server.contract`` (``hosts``), so that a hub knows it from the
image. This module only binds it: each structure to its model and to what computes its
descriptors, each signal to the saves and deletes that send it. A structure the contract does not
declare cannot be bound, and one it declares that nothing binds here stops the service at its
start. The GraphQL types answer ``descriptors`` from the same binding (``alpaka_server.descriptors``).

Hosting announces nothing by itself: a structure with no signal below is hosted silently.

That is all a service is. What can be *done* in this process is not declared here: that is an
agent's to say (``alpaka_server.hook_agent``), a different thing with its own configuration.
"""


from kammer import models as kammer_models
from vector import models as vector_models
from llm import models as llm_models
from arkitekt_service.service import Service, organization_of

from alpaka_server.contract import contract

service = Service("alpaka", hosts=contract.description.hosts, description="LLM rooms and vector collections.")


# --- Structures: what alpaka hosts ----------------------------------------------------

room = service.structure(kammer_models.Room, "@alpaka/room")
message = service.structure(
    kammer_models.Message,
    "@alpaka/message",
    describe=lambda message: {"@alpaka/from_agent": message.agent_id is not None, "@alpaka/is_reply": message.is_reply_to_id is not None},
)
llmmodel = service.structure(
    llm_models.LLMModel,
    "@alpaka/llmmodel",
    describe=lambda model: {
        "@alpaka/features": list(model.features or []),
        "@alpaka/input_modalities": list(model.input_modalities or []),
        "@alpaka/output_modalities": list(model.output_modalities or []),
    },
)
chromacollection = service.structure(vector_models.ChromaCollection, "@alpaka/chromacollection")
# No descriptors: a provider row holds an API key, and nothing about it belongs in a signal.
provider = service.structure(llm_models.Provider, "@alpaka/provider")


# --- Signals: what alpaka announces ----------------------------------------------------
# A streamed reply is saved token by token: it is announced once, when it is done
# (``is_streaming`` false) — never per delta.

org = organization_of()

service.model_signal(room, organization=org)
service.model_signal(message, organization=organization_of("room.organization"), when=lambda message, kind: not message.is_streaming)
service.model_signal(llmmodel, organization=organization_of("provider.organization"))
service.model_signal(chromacollection, organization=org)
service.model_signal(provider, organization=org)
