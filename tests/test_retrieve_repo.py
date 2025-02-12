import pytest
from bridge.models import Flavour, App, Release, GithubRepo
from django.contrib.auth import get_user_model
import typing
from bridge.repo.models import DeploymentsConfigFile
import yaml
from tests.utils import build_relative_dir
from rekuest_core.enums import PortKind
from bridge.repo.db import parse_config


@pytest.mark.asyncio
async def test_parse_deployments(db: typing.Any) -> None:
    with open(
        build_relative_dir("deployments/deployments.yaml"), "r"
    ) as deployment_file:
        deployment = yaml.safe_load(deployment_file)

    config = DeploymentsConfigFile(**deployment)

    assert len(config.deployments) == 3, "Should have one deployment"
    assert (
        config.deployments[0].flavour == "vanilla"
    ), "First deployment should be vanilla"
    assert config.deployments[2].flavour == "cuda", "Third deployment should be vanilla"

    third_deployment = config.deployments[2]

    assert third_deployment.inspection, "Should have an inspection"

    inspection = third_deployment.inspection

    assert inspection.definitions, "Should have definitions"

    definitions = inspection.definitions

    assert len(definitions) == 1, "Should have one definition"

    definition = definitions[0]

    assert (
        definition.name == "Print String"
    ), "First definition should be named Print String"

    assert definition.args, "Should have args"

    assert len(definition.args) == 1, "Should have one arg"

    arg = definition.args[0]

    assert arg.key == "input", "Arg should be named string"
    assert arg.kind == PortKind.STRING, "Arg should be an string"


@pytest.mark.asyncio
async def test_db_deployments(db: typing.Any) -> None:
    user, _ = await get_user_model().objects.aget_or_create(
        username="test", defaults=dict(email="test@gmail.com")
    )

    github_repo = await GithubRepo.objects.acreate(
        name="test",
        creator=user,
    )

    with open(
        build_relative_dir("deployments/deployments.yaml"), "r"
    ) as deployment_file:
        deployment = yaml.safe_load(deployment_file)

    config = DeploymentsConfigFile(**deployment)

    flavours = await parse_config(config, github_repo)

    assert len(flavours) == 3, "Should have three flavours"
