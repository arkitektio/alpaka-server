import pytest
from django.contrib.auth import get_user_model
from alpaka_server.schema import schema

from kante.context import HttpContext

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_github_repo(db, authenticated_context: HttpContext):
    
    assert authenticated_context.request.organization is not None, "Organization should be set"

    query = """
        mutation {
            createRoom(input: {title: "mytitle"}) {
                id
                title
            }
        }
    """

    sub = await schema.execute(
        query,
        context_value=authenticated_context,
    )

    assert sub.data, sub.errors

    assert sub.data["createRoom"]["id"] is not None
    assert sub.data["createRoom"]["title"] == "mytitle"
