import pytest
from bridge.models import Flavour, App, Release, GithubRepo, Deployment
from django.contrib.auth import get_user_model
import typing


@pytest.mark.asyncio
@pytest.mark.docker
async def test_up_setup(db: typing.Any) -> None:
    user, _ = await get_user_model().objects.aget_or_create(
        username="test", defaults=dict(email="test@gmail.com")
    )

    github_repo = await GithubRepo.objects.acreate(
        name="test",
        creator=user,
    )

    app = await App.objects.acreate(
        identifier="test",
    )

    release = await Release.objects.acreate(
        version="test",
        app=app,
    )

    # Creating two different flavours, of which one has a selector
    # Should just create one container

    cuda_flavour = await Flavour.objects.acreate(
        release=release,
        name="cuda",
        repo=github_repo,
        image="hello-world",
        selectors=[
            {
                "type": "cuda",
            }
        ],
    )

    vanilla_flavour = await Flavour.objects.acreate(
        release=release,
        name="vanilla",
        repo=github_repo,
        image="hello-world",
        selectors=[],
    )
