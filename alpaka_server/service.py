"""alpaka as a service of the hub: the models and the code behind what its contract says it hosts.

What exists here (the structures, the descriptors of their objects, the signals and their kinds)
is declared once, as data, in ``alpaka_server.contract`` (``hosts``), so that a hub knows it from the
image. This module only binds it: each structure to its model and to what computes its
descriptors, each signal to the saves and deletes that send it. A structure the contract does not
declare cannot be bound, and one it declares that nothing binds here stops the service at its
start. Each described row stores its descriptors on every save (``stored_descriptors``): the
GraphQL types answer ``descriptors`` from there, and a list filter's ``requires`` reads it in SQL.
What a save of the row cannot see is restored below, by the writes that change it.

Hosting announces nothing by itself: a structure with no signal below is hosted silently.

That is all a service is. What can be *done* in this process is not declared here: that is an
agent's to say (``alpaka_server.hook_agent``), a different thing with its own configuration.
"""


from typing import Literal

from arkitekt_service.collaborations import items as collaboration_items
from arkitekt_service.service import Service, organization_of
from django.db.models import Model
from django.db.models.signals import m2m_changed, post_delete, post_save

from alpaka_server import descriptors
from alpaka_server.contract import contract
from kammer import models as kammer_models
from llm import models as llm_models
from vector import models as vector_models

service = Service("alpaka", hosts=contract.description.hosts, description="LLM rooms and vector collections.")


# --- Collaborations: what an object needs to be seen, put in a collaboration along with it ------------------
# What is part of a room (its agents, its messages) is in a collaboration with it by itself. These
# name the rest: the structure references its messages were posted about. Only rooms and messages
# are put in one (``alpaka_server.schema.SHAREABLE``): a provider holds an API key, and
# its models and the collections they embed are the organization's to call, on its credentials.


def _room_needs(room: kammer_models.Room) -> list[kammer_models.Structure]:
    """The structures a room's messages were posted about."""
    return list(kammer_models.Structure.objects.filter(message__room=room).distinct())


def _message_needs(message: kammer_models.Message) -> list[Model]:
    """The agent that posted a message, the agents it is addressed to, and the structures it was posted about."""
    return [message.agent, *message.targets.all(), *message.attached_structures.all()]


# --- Structures: what alpaka hosts ----------------------------------------------------

room = service.structure(kammer_models.Room, "@alpaka/room", describe=descriptors.room_descriptors, depends=_room_needs)
message = service.structure(kammer_models.Message, "@alpaka/message", describe=descriptors.message_descriptors, depends=_message_needs)
llmmodel = service.structure(llm_models.LLMModel, "@alpaka/llmmodel", describe=descriptors.llm_model_descriptors)
chromacollection = service.structure(vector_models.ChromaCollection, "@alpaka/chromacollection", describe=descriptors.collection_descriptors)
# Only its kind: a provider row holds an API key, and nothing else about it belongs in a signal.
provider = service.structure(llm_models.Provider, "@alpaka/provider", describe=descriptors.provider_descriptors)


# --- Restores: what a save of the described row does not see --------------------------
# Each restore of a row created in the transaction still open announces nothing: its CREATED
# reads the stored value at the commit. A mutation that writes a row and then what describes it
# (``send``, ``createRoom``) is one transaction, so its CREATED carries both.

M2mAction = Literal["pre_add", "post_add", "pre_remove", "post_remove", "pre_clear", "post_clear"]


def _restore_attached(sender: type[Model], instance: Model, action: M2mAction, reverse: bool, model: type[Model], pk_set: set[int] | None, **_: object) -> None:
    """The structures a room is about or a message was posted about changed: restore the described side."""
    if not action.startswith("post_"):
        return
    if not reverse:
        service.restore(instance)
    elif pk_set:  # written from a structure's side: ``model`` is the room or message
        service.restore(model._base_manager.filter(pk__in=pk_set))


m2m_changed.connect(_restore_attached, sender=kammer_models.Room.contextual_structures.through, weak=False, dispatch_uid="alpaka:room:contextual_structures")
m2m_changed.connect(_restore_attached, sender=kammer_models.Message.attached_structures.through, weak=False, dispatch_uid="alpaka:message:attached_structures")


def _restore_room_of(sender: type[kammer_models.Agent], instance: kammer_models.Agent, created: bool = True, **_: object) -> None:
    """An agent joined or left a room: restore what the room counts. A queryset, so a room being deleted is no error."""
    if created:
        service.restore(kammer_models.Room.all_objects.filter(pk=instance.room_id))


post_save.connect(_restore_room_of, sender=kammer_models.Agent, weak=False, dispatch_uid="alpaka:agent:room-saved")
post_delete.connect(_restore_room_of, sender=kammer_models.Agent, weak=False, dispatch_uid="alpaka:agent:room-deleted")


def _restore_models_of(sender: type[llm_models.Provider], instance: llm_models.Provider, created: bool = False, raw: bool = False, **_: object) -> None:
    """A provider was saved, its kind perhaps changed (``createProvider`` upserts by name): restore its models."""
    if not created and not raw:
        service.restore(llm_models.LLMModel.all_objects.filter(provider=instance).select_related("provider"))


post_save.connect(_restore_models_of, sender=llm_models.Provider, weak=False, dispatch_uid="alpaka:provider:models")


# A message is its room's, not part of the agent that posted it: a message put in a collaboration
# brings its agent, and the agent's other messages in the room stay out.
service.not_part_of(kammer_models.Message, "agent")


def _bring_attached(sender: type[Model], instance: Model, action: M2mAction, reverse: bool, model: type[Model], pk_set: set[int] | None, **_: object) -> None:
    """Structures attached to a message (``send``, ``finishMessage``) come into the collaborations of its room, and its own."""
    if action != "post_add":
        return
    messages = kammer_models.Message.all_objects.filter(pk__in=pk_set or ()) if reverse else kammer_models.Message.all_objects.filter(pk=instance.pk)
    for posted in messages.select_related("room"):
        collaboration_items.refresh(posted)
        collaboration_items.refresh(posted.room)


m2m_changed.connect(_bring_attached, sender=kammer_models.Message.attached_structures.through, weak=False, dispatch_uid="alpaka:message:collaborations")


# --- Signals: what alpaka announces ----------------------------------------------------
# A streamed reply is saved token by token: it is announced once, when it is done
# (``is_streaming`` false) — never per delta.

org = organization_of()

service.model_signal(room, organization=org)
service.model_signal(message, organization=organization_of("room.organization"), when=lambda message, kind: not message.is_streaming)
service.model_signal(llmmodel, organization=organization_of("provider.organization"))
service.model_signal(chromacollection, organization=org)
service.model_signal(provider, organization=org)
