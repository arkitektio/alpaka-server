"""Tests for the new strawberry-django ``filter_type`` / ``order_type`` API on
the kammer Room and Message types (see ``kammer/filters.py``)."""

import datetime

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from authentikate.models import Client, Organization, User
from kammer import models


@sync_to_async
def seed():
    """Create a room with three messages whose ``created_at`` is strictly
    increasing, plus a structure the room is "talking about"."""
    org = Organization.objects.get(slug="static_org")
    user = User.objects.get(sub="1", iss="static_issuer")
    client = Client.objects.get(client_id="oinsoins")

    structure = models.Structure.objects.create(identifier="some/structure", object=42)

    room = models.Room.objects.create(title="Weather room", organization=org, creator=user)
    room.contextual_structures.add(structure)

    other_room = models.Room.objects.create(title="Cooking room", organization=org, creator=user)

    agent = models.Agent.objects.create(room=room, client=client, user=user)

    base = timezone.now()
    texts = ["hello world", "goodbye world", "hello again"]
    messages = []
    for i, text in enumerate(texts):
        message = models.Message.objects.create(room=room, agent=agent, text=text)
        # auto_now_add fixes created_at on insert; overwrite it so ordering is
        # deterministic regardless of how fast the inserts ran.
        models.Message.objects.filter(id=message.id).update(created_at=base + datetime.timedelta(seconds=i))
        messages.append(message)

    return {
        "org": org,
        "room": room,
        "other_room": other_room,
        "agent": agent,
        "structure": structure,
        "messages": messages,
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_message_filter_search(aexecute):
    """``search`` filters messages by a case-insensitive substring of ``text``."""
    await seed()

    query = """
        query Messages($filters: MessageFilter) {
            messages(filters: $filters) {
                id
                text
            }
        }
    """

    result = await aexecute(query, {"filters": {"search": "hello"}})

    assert result.data, result.errors
    texts = {m["text"] for m in result.data["messages"]}
    assert texts == {"hello world", "hello again"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_message_filter_ids(aexecute):
    """``ids`` restricts messages to the given primary keys."""
    data = await seed()
    wanted = [data["messages"][0], data["messages"][2]]

    query = """
        query Messages($filters: MessageFilter) {
            messages(filters: $filters) {
                id
            }
        }
    """

    result = await aexecute(query, {"filters": {"ids": [str(m.id) for m in wanted]}})

    assert result.data, result.errors
    returned = {m["id"] for m in result.data["messages"]}
    assert returned == {str(m.id) for m in wanted}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_message_order_created_at(aexecute):
    """``ordering`` exposes the ``order_type`` and sorts by ``created_at``."""
    data = await seed()
    ids_in_creation_order = [str(m.id) for m in data["messages"]]

    query = """
        query Messages($ordering: [MessageOrder!]) {
            messages(ordering: $ordering) {
                id
            }
        }
    """

    asc = await aexecute(query, {"ordering": [{"createdAt": "ASC"}]})
    assert asc.data, asc.errors
    assert [m["id"] for m in asc.data["messages"]] == ids_in_creation_order

    desc = await aexecute(query, {"ordering": [{"createdAt": "DESC"}]})
    assert desc.data, desc.errors
    assert [m["id"] for m in desc.data["messages"]] == list(reversed(ids_in_creation_order))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_message_filter_and_order_combined(aexecute):
    """Filtering and ordering compose in a single query."""
    await seed()

    query = """
        query Messages($filters: MessageFilter, $ordering: [MessageOrder!]) {
            messages(filters: $filters, ordering: $ordering) {
                text
            }
        }
    """

    result = await aexecute(
        query,
        {"filters": {"search": "hello"}, "ordering": [{"createdAt": "DESC"}]},
    )

    assert result.data, result.errors
    assert [m["text"] for m in result.data["messages"]] == ["hello again", "hello world"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_room_filter_search(aexecute):
    """``search`` filters rooms by a case-insensitive substring of ``title``."""
    await seed()

    query = """
        query Rooms($filters: RoomFilter) {
            rooms(filters: $filters) {
                title
            }
        }
    """

    result = await aexecute(query, {"filters": {"search": "weather"}})

    assert result.data, result.errors
    assert [r["title"] for r in result.data["rooms"]] == ["Weather room"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_room_filter_ids(aexecute):
    """``ids`` restricts rooms to the given primary keys."""
    data = await seed()

    query = """
        query Rooms($filters: RoomFilter) {
            rooms(filters: $filters) {
                id
            }
        }
    """

    result = await aexecute(query, {"filters": {"ids": [str(data["room"].id)]}})

    assert result.data, result.errors
    assert [r["id"] for r in result.data["rooms"]] == [str(data["room"].id)]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_room_filter_talking_about(aexecute):
    """``talkingAbout`` keeps only rooms whose contextual structures match the
    given identifier/object, returning none when the structure is unknown."""
    await seed()

    query = """
        query Rooms($filters: RoomFilter) {
            rooms(filters: $filters) {
                id
                title
            }
        }
    """

    match = await aexecute(
        query,
        {"filters": {"talkingAbout": {"identifier": "some/structure", "object": "42"}}},
    )
    assert match.data, match.errors
    assert [r["title"] for r in match.data["rooms"]] == ["Weather room"]

    miss = await aexecute(
        query,
        {"filters": {"talkingAbout": {"identifier": "unknown", "object": "1"}}},
    )
    assert miss.data is not None, miss.errors
    assert miss.data["rooms"] == []
