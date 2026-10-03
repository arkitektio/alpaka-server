"""``descriptors`` on alpaka's types: what an object says about itself, from its structure's declaration.

One declaration (``alpaka_server.service``) feeds the manifest, the signals and this field, so the
tests hold the three to each other: the field answers what a signal about the object carries, in
the keys the manifest declares. And the agent's one action does one organization's share of the work.
"""

import pytest
from asgiref.sync import sync_to_async

from alpaka_server.service import agent, service
from authentikate.models import Client, Organization, User
from embeddings import engine
from embeddings.healer import stale_queryset
from kammer import models as kammer_models
from llm import models as llm_models
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


# Test fixtures name their organization on the row: ``all_objects``, there being no request to scope by.
@sync_to_async
def _seed(slug: str = "static_org") -> dict:
    """A room with a message and a reply, a provider with a model, and a collection, all owned by ``slug``."""
    org, _ = Organization.objects.get_or_create(slug=slug)
    user = User.objects.get(sub="1", iss="static_issuer")
    client = Client.objects.get(client_id="oinsoins")

    room = kammer_models.Room.all_objects.create(title="Segment nuclei", description="Find cell nuclei", organization=org, creator=user)
    speaker = kammer_models.Agent.all_objects.create(room=room, client=client, user=user)
    message = kammer_models.Message.all_objects.create(room=room, agent=speaker, text="How many nuclei?")
    reply = kammer_models.Message.all_objects.create(room=room, agent=speaker, text="Forty-two", is_reply_to=message)

    provider = llm_models.Provider.all_objects.create(name="Described provider", organization=org, api_key="sk-do-not-leak")
    model = llm_models.LLMModel.all_objects.create(provider=provider, model_id="described-model", label="Described", features=["chat", "embedding"], input_modalities=["text", "image"], output_modalities=["text"])
    collection = vector_models.ChromaCollection.all_objects.create(name="papers", description="Papers about nuclei", embedder=model, organization=org)
    return {"room": room, "message": message, "reply": reply, "provider": provider, "model": model, "collection": collection}


async def test_an_object_answers_the_descriptors_its_structure_declares(aexecute, authenticated_context):
    seeded = await _seed()

    result = await aexecute(DESCRIBED, {key: str(seeded[key].pk) for key in ("room", "message", "reply", "model", "provider", "collection")})
    assert not result.errors, result.errors

    assert result.data["message"]["descriptors"] == {"@alpaka/from_agent": True, "@alpaka/is_reply": False}
    assert result.data["reply"]["descriptors"] == {"@alpaka/from_agent": True, "@alpaka/is_reply": True}
    described = {"@alpaka/features": ["chat", "embedding"], "@alpaka/input_modalities": ["text", "image"], "@alpaka/output_modalities": ["text"]}
    assert result.data["llmModel"]["descriptors"] == described
    assert {"id": str(seeded["model"].pk), "descriptors": described} in result.data["llmModels"]
    # A structure that declares no descriptors has none; a provider (it holds an API key) says nothing about itself.
    assert result.data["room"]["descriptors"] == {}
    assert result.data["chromaCollection"]["descriptors"] == {}
    assert result.data["provider"]["descriptors"] == {}

    declared = {s["identifier"]: [d["key"] for d in s["descriptors"]] for s in service.manifest()["structures"]}
    assert set(result.data["message"]["descriptors"]) == set(declared["@alpaka/message"])
    assert set(result.data["llmModel"]["descriptors"]) == set(declared["@alpaka/llmmodel"])


async def test_the_field_answers_what_the_signal_carried(intake, aexecute, authenticated_context):  # noqa: F811
    seeded = await _seed()

    (model_signal,) = await sync_to_async(intake.of)("@alpaka/llmmodel")
    messages = {received["json"]["object"]: received["json"] for received in await sync_to_async(intake.of)("@alpaka/message", count=2)}
    result = await aexecute(
        "query Signalled($model: ID!, $reply: ID!) { llmModel(id: $model) { descriptors } message(id: $reply) { descriptors } }",
        {"model": str(seeded["model"].pk), "reply": str(seeded["reply"].pk)},
    )
    assert not result.errors, result.errors
    assert result.data["llmModel"]["descriptors"] == model_signal["json"]["descriptors"] != {}
    assert result.data["message"]["descriptors"] == messages[str(seeded["reply"].pk)]["descriptors"] != {}


async def test_a_sweep_for_one_organization_claims_only_its_rows(authenticated_context):
    """Every organization has the agent and its own schedule: a run must not do another's work."""
    mine, theirs = await _seed(), await _seed("elsewhere")
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
