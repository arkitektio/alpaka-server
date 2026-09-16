"""Cross-organization isolation for the GraphQL surface.

Every root field that reads or deletes tenant-owned data must be scoped to the
request's organization. These tests seed data as ``static_org`` and then ask for
it as ``other_org``, which must never see it — the previous resolvers did bare
``objects.get(id=...)`` and handed it over.
"""

import pytest
from asgiref.sync import sync_to_async

from authentikate.models import Client, Organization, User
from kammer import models as kammer_models
from llm import models as llm_models
from vector import models as vector_models


@sync_to_async
def seed_static_org():
    """Create one room, provider, model and collection owned by ``static_org``."""
    org = Organization.objects.get(slug="static_org")
    user = User.objects.get(sub="1", iss="static_issuer")
    client = Client.objects.get(client_id="oinsoins")

    room = kammer_models.Room.objects.for_write().create(title="Private room", organization=org, creator=user)
    agent = kammer_models.Agent.objects.for_write().create(room=room, client=client, user=user)
    message = kammer_models.Message.objects.for_write().create(room=room, agent=agent, text="a secret")

    provider = llm_models.Provider.objects.for_write().create(name="Secret provider", organization=org, api_key="sk-do-not-leak", additional_config={"api_key": "sk-nested", "region": "eu"})
    model = llm_models.LLMModel.objects.for_write().create(provider=provider, model_id="secret-model", label="Secret", features=["embedding"])
    collection = vector_models.ChromaCollection.objects.for_write().create(name="secret-docs", embedder=model, organization=org)

    return {
        "room": room,
        "message": message,
        "provider": provider,
        "model": model,
        "collection": collection,
    }


# --- list fields ------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,query",
    [
        ("rooms", "{ rooms { id } }"),
        ("providers", "{ providers { id } }"),
        ("llmModels", "{ llmModels { id } }"),
        ("chromaCollections", "{ chromaCollections { id } }"),
    ],
)
async def test_list_fields_do_not_span_organizations(aexecute, other_org_context, field, query):
    """A list field returns the caller's organization's rows and nothing else."""
    await seed_static_org()

    mine = await aexecute(query)
    assert mine.data, mine.errors
    assert len(mine.data[field]) == 1

    theirs = await aexecute(query, context=other_org_context)
    assert theirs.data, theirs.errors
    assert theirs.data[field] == []


# --- singular fetches -------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,field,query",
    [
        ("room", "room", "query($id: ID!) { room(id: $id) { id } }"),
        ("provider", "provider", "query($id: ID!) { provider(id: $id) { id } }"),
        ("model", "llmModel", "query($id: ID!) { llmModel(id: $id) { id } }"),
        ("collection", "chromaCollection", "query($id: ID!) { chromaCollection(id: $id) { id } }"),
    ],
)
async def test_singular_fetches_refuse_other_organizations(aexecute, other_org_context, key, field, query):
    """Fetching another organization's row by ID fails instead of returning it."""
    seeded = await seed_static_org()
    variables = {"id": str(seeded[key].id)}

    mine = await aexecute(query, variables)
    assert mine.data, mine.errors
    assert mine.data[field]["id"] == variables["id"]

    theirs = await aexecute(query, variables, context=other_org_context)
    assert theirs.errors, f"{field} handed a row to another organization"


# --- deletes ----------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delete_room_refuses_other_organizations(aexecute, other_org_context):
    """A room cannot be deleted from outside its organization."""
    seeded = await seed_static_org()
    query = "mutation($input: DeleteRoomInput!) { deleteRoom(input: $input) }"

    result = await aexecute(query, {"input": {"id": str(seeded["room"].id)}}, context=other_org_context)

    assert result.errors
    assert await kammer_models.Room.all_objects.filter(id=seeded["room"].id).aexists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delete_provider_refuses_other_organizations(aexecute, other_org_context):
    """A provider cannot be deleted from outside its organization."""
    seeded = await seed_static_org()
    query = "mutation($input: DeleteProviderInput!) { deleteProvider(input: $input) }"

    result = await aexecute(query, {"input": {"id": str(seeded["provider"].id)}}, context=other_org_context)

    assert result.errors
    assert await llm_models.Provider.all_objects.filter(id=seeded["provider"].id).aexists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_send_refuses_another_organizations_room(aexecute, other_org_context):
    """A message cannot be posted into another organization's room."""
    seeded = await seed_static_org()
    query = "mutation($input: SendMessageInput!) { send(input: $input) { id } }"

    result = await aexecute(
        query,
        {"input": {"room": str(seeded["room"].id), "agentId": "intruder", "text": "hello"}},
        context=other_org_context,
    )

    assert result.errors
    assert await kammer_models.Message.all_objects.filter(room=seeded["room"]).acount() == 1


# --- credential exposure ----------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_provider_api_key_is_not_exposed(aexecute):
    """The Provider type has no field that returns the raw credential."""
    from alpaka_server.schema import schema

    provider_type = schema.as_str().split("type Provider {")[1].split("}")[0]
    assert "apiKey" not in provider_type
    assert "hasApiKey" in provider_type

    await seed_static_org()
    result = await aexecute("{ providers { hasApiKey additionalConfig } }")

    assert result.data, result.errors
    provider = result.data["providers"][0]
    assert provider["hasApiKey"] is True
    # Secret-looking keys are masked; ordinary settings come through untouched.
    assert provider["additionalConfig"]["api_key"] == "**********"
    assert provider["additionalConfig"]["region"] == "eu"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_room_stats_is_scoped(aexecute, other_org_context):
    """``roomStats`` counts only the caller's organization's rooms."""
    await seed_static_org()
    query = "{ roomStats { count } }"

    mine = await aexecute(query)
    assert mine.data, mine.errors
    assert mine.data["roomStats"]["count"] == 1

    theirs = await aexecute(query, context=other_org_context)
    assert theirs.data, theirs.errors
    assert theirs.data["roomStats"]["count"] == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_messages_do_not_span_organizations(aexecute, other_org_context):
    """``messages`` returns only messages in the caller's organization's rooms."""
    await seed_static_org()
    query = "{ messages { id text } }"

    mine = await aexecute(query)
    assert mine.data, mine.errors
    assert [m["text"] for m in mine.data["messages"]] == ["a secret"]

    theirs = await aexecute(query, context=other_org_context)
    assert theirs.data, theirs.errors
    assert theirs.data["messages"] == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_message_by_id_refuses_other_organizations(aexecute, other_org_context):
    """A message cannot be fetched by ID from outside its organization."""
    seeded = await seed_static_org()
    query = "query($id: ID!) { message(id: $id) { id } }"
    variables = {"id": str(seeded["message"].id)}

    mine = await aexecute(query, variables)
    assert mine.data, mine.errors

    theirs = await aexecute(query, variables, context=other_org_context)
    assert theirs.errors or theirs.data.get("message") is None, "message handed a row to another organization"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_provider_does_not_persist_the_redaction_mask(aexecute):
    """Writing a config read back from the API keeps the live credential."""
    seeded = await seed_static_org()

    read = await aexecute("{ providers { additionalConfig } }")
    assert read.data, read.errors
    config = read.data["providers"][0]["additionalConfig"]
    assert config["api_key"] == "**********"

    # Edit one harmless field and write the whole object back, mask included.
    config["region"] = "us"
    result = await aexecute(
        "mutation($input: UpdateProviderInput!) { updateProvider(input: $input) { hasApiKey additionalConfig } }",
        {"input": {"id": str(seeded["provider"].id), "additionalConfig": config}},
    )

    assert result.data, result.errors
    assert result.data["updateProvider"]["additionalConfig"]["region"] == "us"

    provider = await llm_models.Provider.all_objects.aget(id=seeded["provider"].id)
    assert provider.additional_config["api_key"] == "sk-nested"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_provider_refuses_other_organizations(aexecute, other_org_context):
    """A provider cannot be updated from outside its organization."""
    seeded = await seed_static_org()

    result = await aexecute(
        "mutation($input: UpdateProviderInput!) { updateProvider(input: $input) { id } }",
        {"input": {"id": str(seeded["provider"].id), "apiKey": "stolen"}},
        context=other_org_context,
    )

    assert result.errors
    provider = await llm_models.Provider.all_objects.aget(id=seeded["provider"].id)
    assert provider.api_key == "sk-do-not-leak"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_pagination_applies(aexecute):
    """``pagination`` is honoured by the hand-rolled list resolvers."""
    org = await sync_to_async(Organization.objects.get)(slug="static_org")
    await sync_to_async(llm_models.Provider.objects.for_write().create)(name="P1", organization=org)
    await sync_to_async(llm_models.Provider.objects.for_write().create)(name="P2", organization=org)
    await sync_to_async(llm_models.Provider.objects.for_write().create)(name="P3", organization=org)

    query = """
        query($pagination: OffsetPaginationInput) {
            providers(ordering: [{name: ASC}], pagination: $pagination) { name }
        }
    """

    page = await aexecute(query, {"pagination": {"offset": 1, "limit": 1}})
    assert page.data, page.errors
    assert [p["name"] for p in page.data["providers"]] == ["P2"]

    unpaged = await aexecute(query, {})
    assert unpaged.data, unpaged.errors
    assert [p["name"] for p in unpaged.data["providers"]] == ["P1", "P2", "P3"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_federation_entities_do_not_leak_across_organizations(aexecute, other_org_context):
    """``_entities`` must not resolve another organization's row.

    Federated types carry ``@key(fields: "id")``, and ``_entities`` resolves by
    ``__typename`` + ``id`` without going through the singular resolvers or
    ``get_queryset`` — so it is a second door that needs its own guard.
    """
    seeded = await seed_static_org()
    query = """
        query($reps: [_Any!]!) {
            _entities(representations: $reps) {
                ... on Room { id title }
                ... on Message { id text }
                ... on Agent { id name }
            }
        }
    """
    reps = [
        {"__typename": "Room", "id": str(seeded["room"].id)},
        {"__typename": "Message", "id": str(seeded["message"].id)},
    ]

    # Own organization: the entities resolve, contents included.
    mine = await aexecute(query, {"reps": reps})
    assert mine.data, mine.errors
    assert mine.data["_entities"][0]["title"] == "Private room"
    assert mine.data["_entities"][1]["text"] == "a secret"

    # Another organization: no contents come back.
    theirs = await aexecute(query, {"reps": reps}, context=other_org_context)
    leaked = [e for e in (theirs.data or {}).get("_entities") or [] if e and (e.get("title") or e.get("text"))]
    assert not leaked, f"_entities handed rows to another organization: {leaked}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_room_lists_its_agents(aexecute):
    """``Room.agents`` resolves through the reverse FK (regression: ``agent_set`` mismatch)."""
    seeded = await seed_static_org()
    query = "query($id: ID!) { room(id: $id) { id agents { id room { id } } } }"

    result = await aexecute(query, {"id": str(seeded["room"].id)})
    assert result.data, result.errors
    agents = result.data["room"]["agents"]
    assert [a["room"]["id"] for a in agents] == [str(seeded["room"].id)]
    assert len(agents) == 1
