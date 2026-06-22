import pytest


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_room(aexecute, authenticated_context):
    assert authenticated_context.request.organization is not None, "Organization should be set"

    query = """
        mutation {
            createRoom(input: {title: "mytitle"}) {
                id
                title
            }
        }
    """

    sub = await aexecute(query)

    assert sub.data, sub.errors
    assert sub.data["createRoom"]["id"] is not None
    assert sub.data["createRoom"]["title"] == "mytitle"
