"""``descriptors`` on alpaka's types: what an object says about itself, from its structure's declaration.

One declaration (``alpaka_server.service``) feeds the manifest, the signals and this field, so the
tests hold the three to each other: the field answers what a signal about the object carries, in
the keys the manifest declares. The descriptors are stored, so a port's ``requires`` is a filter on
the list query, and what a save cannot see (structures attached, agents joining, a provider's
kind) is restored by whoever writes it. And the agent's one action does one organization's share
of the work.
"""

import pytest
from asgiref.sync import sync_to_async
from django.core.management import call_command

from alpaka_server.hook_agent import agent
from alpaka_server.service import service
from authentikate.models import Client, Organization, User
from embeddings import engine
from embeddings.healer import stale_queryset
from kammer import models as kammer_models
from llm import models as llm_models
from tests.test_decide import faketypesafe, typesafe, typesafe_url  # noqa: F401  the fixtures
from tests.test_signals import intake  # noqa: F401  the fixture
from vector import models as vector_models

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

DESCRIBED = """
    query Described($room: ID!, $message: ID!, $reply: ID!, $model: ID!, $provider: ID!, $collection: ID!) {
        room(id: $room) { descriptors }
        message(id: $message) { descriptors }
        reply: message(id: $reply) { descriptors }
        llmModel(id: $model) { descriptors }
        provider(id: $provider) { descriptors }
        chromaCollection(id: $collection) { descriptors }
        llmModels { id descriptors }
    }
"""

CREATE_ROOM = "mutation ($input: CreateRoomInput!) { createRoom(input: $input) { id } }"
SEND = "mutation ($input: SendMessageInput!) { send(input: $input) { id } }"
START = "mutation ($input: StartMessageInput!) { startMessage(input: $input) { id } }"
FINISH = "mutation ($input: FinishMessageInput!) { finishMessage(input: $input) { id } }"


def _structures(*pairs: tuple[str, int]) -> list[dict]:
    return [{"identifier": identifier, "object": obj} for identifier, obj in pairs]


# Test fixtures name their organization on the row: ``all_objects``, there being no request to scope by.
@sync_to_async
def _rows(slug: str = "static_org") -> dict:
    """A room with a message and a reply, an Ollama provider with a model, and a collection, all owned by ``slug``.

    No GraphQL here: creating an Ollama provider lists its models from a server the stack does not run.
    """
    org, _ = Organization.objects.get_or_create(slug=slug)
    user = User.objects.get(sub="1", iss="static_issuer")
    client = Client.objects.get(client_id="oinsoins")

    room = kammer_models.Room.all_objects.create(title="Segment nuclei", description="Find cell nuclei", organization=org, creator=user)
    speaker = kammer_models.Agent.all_objects.create(room=room, client=client, user=user)
    message = kammer_models.Message.all_objects.create(room=room, agent=speaker, text="How many nuclei?")
    reply = kammer_models.Message.all_objects.create(room=room, agent=speaker, text="Forty-two", is_reply_to=message)

    provider = llm_models.Provider.all_objects.create(name="Described provider", organization=org, kind="ollama", api_key="sk-do-not-leak")
    model = llm_models.LLMModel.all_objects.create(provider=provider, model_id="nomic-embed-text", label="Described", features=["chat", "embedding"], input_modalities=["text", "image"], output_modalities=["text"])
    collection = vector_models.ChromaCollection.all_objects.create(name="papers", description="Papers about nuclei", embedder=model, organization=org)
    return {"room": room, "message": message, "reply": reply, "provider": provider, "model": model, "collection": collection}


async def _converse(aexecute) -> dict[str, str]:
    """A room about two images and a dataset, a message posted about two datasets and a reply to it, by two agents: as the mutations write them."""
    created = await aexecute(CREATE_ROOM, {"input": {"title": "Segment nuclei", "talkingAbout": _structures(("@mikro/image", 1), ("@mikro/arraydataset", 2), ("@mikro/image", 3))}})
    assert not created.errors, created.errors
    room = created.data["createRoom"]["id"]
    sent = await aexecute(SEND, {"input": {"room": room, "agentId": "segmenter", "text": "Masks for both", "attachStructures": _structures(("@mikro/arraydataset", 7), ("@mikro/arraydataset", 8))}})
    assert not sent.errors, sent.errors
    message = sent.data["send"]["id"]
    replied = await aexecute(SEND, {"input": {"room": room, "agentId": "reviewer", "text": "Thanks", "parent": message}})
    assert not replied.errors, replied.errors
    return {"room": room, "message": message, "reply": replied.data["send"]["id"]}


async def test_an_object_answers_the_descriptors_its_structure_declares(aexecute, authenticated_context):
    rows = await _rows()
    conversation = await _converse(aexecute)

    result = await aexecute(DESCRIBED, {**conversation, **{key: str(rows[key].pk) for key in ("model", "provider", "collection")}})
    assert not result.errors, result.errors

    assert result.data["room"]["descriptors"] == {"@alpaka/contextual_structures": ["@mikro/arraydataset", "@mikro/image"], "@alpaka/n_agents": 2}
    assert result.data["message"]["descriptors"] == {"@alpaka/from_agent": True, "@alpaka/is_reply": False, "@alpaka/attached_structures": ["@mikro/arraydataset"]}
    assert result.data["reply"]["descriptors"] == {"@alpaka/from_agent": True, "@alpaka/is_reply": True, "@alpaka/attached_structures": []}
    described = {"@alpaka/features": ["chat", "embedding"], "@alpaka/input_modalities": ["text", "image"], "@alpaka/output_modalities": ["text"], "@alpaka/provider_kind": "ollama"}
    assert result.data["llmModel"]["descriptors"] == described
    assert {"id": str(rows["model"].pk), "descriptors": described} in result.data["llmModels"]
    # A provider (it holds an API key) says what kind it is, and nothing else.
    assert result.data["provider"]["descriptors"] == {"@alpaka/provider_kind": "ollama"}
    assert result.data["chromaCollection"]["descriptors"] == {"@alpaka/embedder": "nomic-embed-text"}

    declared = {s["identifier"]: [d["key"] for d in s["descriptors"]] for s in service.manifest()["structures"]}
    for field, identifier in (("room", "@alpaka/room"), ("message", "@alpaka/message"), ("llmModel", "@alpaka/llmmodel"), ("provider", "@alpaka/provider"), ("chromaCollection", "@alpaka/chromacollection")):
        assert set(result.data[field]["descriptors"]) == set(declared[identifier])


async def test_the_field_answers_what_the_signal_carried(intake, aexecute, authenticated_context):  # noqa: F811
    rows = await _rows()
    conversation = await _converse(aexecute)

    (model_signal,) = await sync_to_async(intake.of)("@alpaka/llmmodel")
    result = await aexecute(
        "query Signalled($model: ID!, $reply: ID!) { llmModel(id: $model) { descriptors } message(id: $reply) { descriptors } }",
        {"model": str(rows["model"].pk), "reply": str(rows["reply"].pk)},
    )
    assert not result.errors, result.errors
    assert result.data["llmModel"]["descriptors"] == model_signal["json"]["descriptors"] != {}
    messages = {received["json"]["object"]: received["json"] for received in await sync_to_async(intake.of)("@alpaka/message", count=4)}
    assert result.data["message"]["descriptors"] == messages[str(rows["reply"].pk)]["descriptors"] != {}

    # The room was announced at its commit, with what it is about (no agent had joined yet).
    rooms = {received["json"]["object"]: received["json"] for received in await sync_to_async(intake.of)("@alpaka/room", count=2)}
    assert rooms[conversation["room"]]["descriptors"] == {"@alpaka/contextual_structures": ["@mikro/arraydataset", "@mikro/image"], "@alpaka/n_agents": 0}


async def test_a_sent_message_is_announced_once_with_what_it_was_posted_about(intake, aexecute, authenticated_context):  # noqa: F811
    conversation = await _converse(aexecute)

    # Two messages sent, two signals: the structures attached after the insert are no second one.
    sent = await sync_to_async(intake.of)("@alpaka/message", count=3, timeout=1)
    assert sorted((received["json"]["kind"], received["json"]["object"]) for received in sent) == sorted([("CREATED", conversation["message"]), ("CREATED", conversation["reply"])])
    (created,) = [received["json"] for received in sent if received["json"]["object"] == conversation["message"]]
    assert created["descriptors"]["@alpaka/attached_structures"] == ["@mikro/arraydataset"]


async def test_a_streamed_message_is_announced_once_finished_with_what_it_was_posted_about(intake, aexecute, authenticated_context):  # noqa: F811
    created = await aexecute(CREATE_ROOM, {"input": {"title": "Stream"}})
    assert not created.errors, created.errors
    started = await aexecute(START, {"input": {"room": created.data["createRoom"]["id"], "agentId": "writer", "text": "Hel"}})
    assert not started.errors, started.errors
    message = started.data["startMessage"]["id"]
    finished = await aexecute(FINISH, {"input": {"message": message, "text": "Hello", "attachStructures": _structures(("@mikro/image", 5))}})
    assert not finished.errors, finished.errors

    # Nothing while it was written; one UPDATED when it closed, carrying what it was posted about.
    (received,) = await sync_to_async(intake.of)("@alpaka/message", count=2, timeout=1)
    assert (received["json"]["kind"], received["json"]["object"]) == ("UPDATED", message)
    assert received["json"]["descriptors"]["@alpaka/attached_structures"] == ["@mikro/image"]
    assert (await kammer_models.Message.all_objects.aget(pk=message)).stored_descriptors["@alpaka/attached_structures"] == ["@mikro/image"]


REQUIRED = """
    query (
        $rooms: [DescriptorConstraintInput!]!, $messages: [DescriptorConstraintInput!]!, $models: [DescriptorConstraintInput!]!,
        $providers: [DescriptorConstraintInput!]!, $collections: [DescriptorConstraintInput!]!
    ) {
        rooms(filters: { requires: $rooms }) { id }
        messages(filters: { requires: $messages }) { id }
        llmModels(filters: { requires: $models }) { id }
        providers(filters: { requires: $providers }) { id }
        chromaCollections(filters: { requires: $collections }) { id }
    }
"""


async def _required(aexecute, *, rooms: list | None = None, messages: list | None = None, models: list | None = None, providers: list | None = None, collections: list | None = None) -> dict[str, set[str]]:
    variables = {"rooms": rooms or [], "messages": messages or [], "models": models or [], "providers": providers or [], "collections": collections or []}
    result = await aexecute(REQUIRED, variables)
    assert not result.errors, result.errors
    return {field: {row["id"] for row in found} for field, found in result.data.items()}


async def test_a_port_requires_is_answered_from_the_stored_descriptors(aexecute, authenticated_context, typesafe):  # noqa: F811
    rows = await _rows()
    conversation = await _converse(aexecute)
    local_model, local_provider = str(rows["model"].pk), str(rows["provider"].pk)
    hosted_models = {model["id"] for model in typesafe["models"]}

    # A privacy-sensitive action takes only a model that runs on the hub.
    local = [{"key": "@alpaka/provider_kind", "operator": "EQUALS", "value": "ollama"}]
    assert (await _required(aexecute, models=local))["llmModels"] == {local_model}
    assert (await _required(aexecute, models=[{"key": "@alpaka/provider_kind", "operator": "EQUALS", "value": "typesafe"}]))["llmModels"] == hosted_models
    on_the_hub = [{"key": "@alpaka/provider_kind", "operator": "IN", "value": ["ollama", "ollaya"]}]
    assert await _required(aexecute, models=on_the_hub, providers=on_the_hub) == {
        "rooms": {conversation["room"], str(rows["room"].pk)},
        "messages": {conversation["message"], conversation["reply"], str(rows["message"].pk), str(rows["reply"].pk)},
        "llmModels": {local_model},
        "providers": {local_provider},
        "chromaCollections": {str(rows["collection"].pk)},
    }

    # A message posted about a dataset; a room two agents take part in; a collection by its embedder.
    about_datasets = [{"key": "@alpaka/attached_structures", "operator": "CONTAINS", "value": "@mikro/arraydataset"}]
    assert (await _required(aexecute, messages=about_datasets))["messages"] == {conversation["message"]}
    assert (await _required(aexecute, rooms=[{"key": "@alpaka/n_agents", "operator": "GTE", "value": 2}]))["rooms"] == {conversation["room"]}
    assert (await _required(aexecute, rooms=[{"key": "@alpaka/contextual_structures", "operator": "CONTAINS", "value": "@mikro/image"}]))["rooms"] == {conversation["room"]}
    assert (await _required(aexecute, collections=[{"key": "@alpaka/embedder", "operator": "EQUALS", "value": "nomic-embed-text"}]))["chromaCollections"] == {str(rows["collection"].pk)}

    # A key alpaka does not declare is refused, not ignored.
    result = await aexecute(REQUIRED, {"rooms": [], "messages": [], "models": [{"key": "@alpaka/colour", "operator": "EQUALS", "value": "red"}], "providers": [], "collections": []})
    assert result.errors and "not a descriptor here" in result.errors[0].message


async def test_what_a_save_does_not_see_is_restored(aexecute, authenticated_context):
    rows = await _rows()
    room, provider = rows["room"], rows["provider"]

    @sync_to_async
    def stored(model: type, pk: int) -> dict:
        return model.all_objects.get(pk=pk).stored_descriptors

    # Attaching a structure to an existing room, and taking it off again.
    structure = await kammer_models.Structure.objects.acreate(identifier="@mikro/arraydataset", object=11)
    await sync_to_async(room.contextual_structures.add)(structure)
    assert (await stored(kammer_models.Room, room.pk))["@alpaka/contextual_structures"] == ["@mikro/arraydataset"]
    assert (await _required(aexecute, rooms=[{"key": "@alpaka/contextual_structures", "operator": "CONTAINS", "value": "@mikro/arraydataset"}]))["rooms"] == {str(room.pk)}
    await sync_to_async(room.contextual_structures.clear)()
    assert (await stored(kammer_models.Room, room.pk))["@alpaka/contextual_structures"] == []

    # From the structure's side too.
    await sync_to_async(structure.message_set.add)(rows["reply"])
    assert (await stored(kammer_models.Message, rows["reply"].pk))["@alpaka/attached_structures"] == ["@mikro/arraydataset"]

    # An agent joining and leaving.
    assert (await stored(kammer_models.Room, room.pk))["@alpaka/n_agents"] == 1
    user, client = authenticated_context.request.user, authenticated_context.request.client
    joined = await kammer_models.Agent.all_objects.acreate(room=room, client=client, user=user, name="second")
    assert (await stored(kammer_models.Room, room.pk))["@alpaka/n_agents"] == 2
    await joined.adelete()
    assert (await stored(kammer_models.Room, room.pk))["@alpaka/n_agents"] == 1

    # A provider saved as another kind: its models say so.
    provider.kind = "openai"
    await provider.asave(update_fields=["kind"])
    assert await stored(llm_models.Provider, provider.pk) == {"@alpaka/provider_kind": "openai"}
    assert (await stored(llm_models.LLMModel, rows["model"].pk))["@alpaka/provider_kind"] == "openai"

    # Deleting a room (its agents with it) is no error.
    await room.adelete()


async def test_the_setup_job_repairs_what_is_owed(authenticated_context):
    rows = await _rows()
    await llm_models.LLMModel.all_objects.filter(pk=rows["model"].pk).aupdate(stored_descriptors={})
    await kammer_models.Room.all_objects.filter(pk=rows["room"].pk).aupdate(stored_descriptors={})

    await sync_to_async(call_command)("restore_descriptors")

    assert (await llm_models.LLMModel.all_objects.aget(pk=rows["model"].pk)).stored_descriptors["@alpaka/provider_kind"] == "ollama"
    assert (await kammer_models.Room.all_objects.aget(pk=rows["room"].pk)).stored_descriptors == {"@alpaka/contextual_structures": [], "@alpaka/n_agents": 1}


async def test_a_sweep_for_one_organization_claims_only_its_rows(authenticated_context):
    """Every organization has the agent and its own schedule: a run must not do another's work."""
    mine, theirs = await _rows(), await _rows("elsewhere")
    embedded = ((kammer_models.Room, "room"), (vector_models.ChromaCollection, "collection"))
    for model, key in embedded:
        await model.all_objects.filter(pk__in=[mine[key].pk, theirs[key].pk]).aupdate(embedding=None, embedding_model="another-model")

    @sync_to_async
    def stale(organization: str | None) -> dict[str, set[int]]:
        """Which of the four seeded rows a sweep for ``organization`` would claim."""
        return {key: set(stale_queryset(model, organization).filter(pk__in=[mine[key].pk, theirs[key].pk]).values_list("pk", flat=True)) for model, key in embedded}

    assert await stale("elsewhere") == {"room": {theirs["room"].pk}, "collection": {theirs["collection"].pk}}
    assert await stale("static_org") == {"room": {mine["room"].pk}, "collection": {mine["collection"].pk}}
    assert await stale(None) == {key: {mine[key].pk, theirs[key].pk} for _, key in embedded}

    # The action itself, run for one organization: its room and its collection, nobody else's.
    assert await sync_to_async(agent.actions["reembed_stale"].function)(organization="elsewhere") == {"reembedded": 2}
    for model, key in embedded:
        healed = await model.all_objects.aget(pk=theirs[key].pk)
        assert healed.embedding is not None and healed.embedding_model == engine.model_id()
        untouched = await model.all_objects.aget(pk=mine[key].pk)
        assert untouched.embedding is None and untouched.embedding_model == "another-model"
    assert await stale(None) == {key: {mine[key].pk} for _, key in embedded}
