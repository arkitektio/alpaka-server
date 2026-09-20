import asyncio
import contextlib
import os
import time

import psycopg
import pytest
import pytest_asyncio
from dokker import testing

from authentikate.models import Client, Membership, Organization, User
from django.contrib.contenttypes.management import create_contenttypes
from django.db.models.signals import post_migrate
from kante.context import HttpContext, UniversalRequest, WsContext
from strawberry.http.temporal_response import TemporalResponse


@pytest.fixture(scope="session")
def backend_stack():
    docker_compose_path = os.path.join(os.path.dirname(__file__), "integration", "docker-compose.yaml")

    with testing(docker_compose_path) as e:
        e.inspect()

        e.down()

        e.up()

        # Compose only waits for postgres' container to *start*, not for it to
        # accept connections, so poll until it answers before pytest-django
        # configures the test DB against it.
        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(
                    dbname="testdb",
                    user="test",
                    password="test",
                    host="localhost",
                    port=5555,
                    connect_timeout=1,
                ) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 1")
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)

        # The suite builds its schema with run-syncdb (migrations disabled), so the
        # `vector` extension migrations never run here -- but CREATE TABLE for the
        # embedding columns (Room / ChromaCollection.embedding) needs the type to exist.
        # Install it into template1 so the test database pytest-django creates from it
        # inherits it, and into testdb itself for anything connecting directly.
        for dbname in ("template1", "testdb"):
            with psycopg.connect(dbname=dbname, user="test", password="test", host="localhost", port=5555, autocommit=True) as connection:
                connection.execute("CREATE EXTENSION IF NOT EXISTS vector")

        yield


@pytest.fixture(scope="session", autouse=True)
def embedding_model_warm():
    """Load the embedding model once per session, outside any test's DB transaction.

    Every save of a Room / ChromaCollection embeds its text, so the first one would otherwise
    pay the model load (a one-time download into the Hugging Face cache on a cold box) inside
    a test.
    """
    from embeddings import engine

    engine.warm_up()
    yield


@pytest.fixture(scope="session")
def django_db_modify_db_settings(backend_stack):
    """Start the backend services before pytest-django configures the test DB."""
    yield


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    # Every transaction=True test teardown flushes the DB and re-fires
    # post_migrate, which rebuilds all contenttypes and permissions from the
    # model registry (~1s per test). The rows never change between tests, so
    # snapshot them once and swap the rebuild for a bulk re-insert with the
    # original pks (keeps guardian FKs and the ContentType pk cache valid).
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    with django_db_blocker.unblock():
        contenttypes = list(ContentType.objects.all())
        permissions = list(Permission.objects.all())

    post_migrate.disconnect(dispatch_uid="django.contrib.auth.management.create_permissions")
    post_migrate.disconnect(create_contenttypes)

    def restore_contenttypes_and_permissions(sender, **kwargs):
        # post_migrate fires once per app config on flush; restore once.
        if getattr(sender, "label", None) != "contenttypes":
            return
        ContentType.objects.bulk_create(contenttypes, ignore_conflicts=True)
        Permission.objects.bulk_create(permissions, ignore_conflicts=True)

    post_migrate.connect(
        restore_contenttypes_and_permissions,
        dispatch_uid="tests.restore_contenttypes_and_permissions",
    )
    yield

    # The async tests run sync ORM code in asgiref's executor threads, whose
    # connections outlive the tests and block dropping the test database
    # ("database is being accessed by other users"). Kill them before
    # pytest-django's teardown drops the database.
    from django.db import connections

    with django_db_blocker.unblock():
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        connections.close_all()


@pytest.fixture(scope="function")
def authenticated_context(db, backend_stack) -> HttpContext:
    # Match the identity the static "test" token resolves to (see settings_test
    # STATIC_TOKENS + authentikate's token expansion), so the org/user on this
    # context is the same one the schema's AuthentikateExtension authenticates as
    # at resolve time — otherwise organization-scoped queries see no data.
    user, _ = User.objects.get_or_create(
        sub="1", iss="static_issuer", defaults={"username": "static_issuer_1"}
    )
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug="static_org")
    membership, _ = Membership.objects.get_or_create(
        user=user,
        organization=org,
    )

    request = UniversalRequest(
        _extensions={"token": "test"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(
        request=request,
        response=TemporalResponse(),
        headers={"Authorization": "Bearer test"},
        type="http",
    )


@pytest.fixture(scope="function")
def other_org_context(db, backend_stack) -> HttpContext:
    """A context for a user in a different organization (static token "othertest")."""
    user, _ = User.objects.get_or_create(
        sub="9", iss="static_issuer", defaults={"username": "static_issuer_9"}
    )
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug="other_org")
    membership, _ = Membership.objects.get_or_create(
        user=user,
        organization=org,
    )

    request = UniversalRequest(
        _extensions={"token": "othertest"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(
        request=request,
        response=TemporalResponse(),
        headers={"Authorization": "Bearer othertest"},
        type="http",
    )


@pytest.fixture(scope="function")
def same_org_other_user_context(db, backend_stack) -> HttpContext:
    """A context for a *different* user in the same organization (static token "test2")."""
    user, _ = User.objects.get_or_create(sub="2", iss="static_issuer", defaults={"username": "static_issuer_2"})
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug="static_org")
    membership, _ = Membership.objects.get_or_create(user=user, organization=org)

    request = UniversalRequest(
        _extensions={"token": "test2"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(
        request=request,
        response=TemporalResponse(),
        headers={"Authorization": "Bearer test2"},
        type="http",
    )


@pytest_asyncio.fixture
async def ws_contexts(authenticated_context):
    """A factory for websocket contexts, for testing subscriptions in-process.

    Each context gets its own ``ChannelsConsumer`` bound to the in-memory
    channel layer, plus a pump task that feeds the layer's messages into the
    consumer's listen queues (what the real websocket handler would do). One
    consumer per subscriber, because ``listen_to_channel`` discards the group
    on exit and would silence a second subscriber sharing the consumer.
    """
    from channels.layers import get_channel_layer
    from strawberry.channels import ChannelsConsumer

    layer = get_channel_layer()
    # The in-memory layer is a process-wide singleton; drop state left behind
    # by earlier tests (and their event loops).
    await layer.flush()
    pumps = []

    async def make(token: str = "test") -> WsContext:
        consumer = ChannelsConsumer()
        consumer.channel_layer = layer
        consumer.channel_name = await layer.new_channel()

        async def pump():
            while True:
                await consumer.dispatch(await layer.receive(consumer.channel_name))

        pumps.append(asyncio.create_task(pump()))
        # The AuthentikateExtension authenticates a WsContext from
        # connection_params["token"] and fills in user/client/organization.
        return WsContext(
            request=UniversalRequest(_extensions={"token": token}),
            response=TemporalResponse(),
            connection_params={"token": token},
            consumer=consumer,
        )

    yield make

    for task in pumps:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.fixture(scope="function")
def simple_api_context(db, backend_stack) -> HttpContext:
    user, _ = User.objects.get_or_create(
        sub="1", iss="static_issuer", defaults={"username": "static_issuer_1"}
    )
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug="static_org")
    membership, _ = Membership.objects.get_or_create(
        user=user,
        organization=org,
    )

    request = UniversalRequest(
        _extensions={"token": "test"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(
        request=request,
        response=TemporalResponse(),
        headers={"Authorization": "Bearer test"},
        type="http",
    )


@pytest.fixture
def aexecute(authenticated_context):
    """Run a GraphQL document against the schema, defaulting to the authed context."""
    from alpaka_server.schema import schema

    async def _run(query, variables=None, context=None):
        return await schema.execute(
            query,
            variable_values=variables or {},
            context_value=context or authenticated_context,
        )

    return _run
