import pytest
import typing
from bridge.models import GithubRepo
from django.contrib.auth import get_user_model


@pytest.fixture
def githup_repo(db: typing.Any) -> GithubRepo:
    user, _ = get_user_model().objects.get_or_create(
        username="test", defaults=dict(email="test@gmail.com")
    )

    repo = GithubRepo.objects.create(
        name="test",
        creator=user,
    )

    return repo
