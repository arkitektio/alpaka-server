from .settings import *  # noqa
from .settings import AUTHENTIKATE, DATABASES
import logging

# Real Postgres from tests/integration/docker-compose.yaml (spun up by the
# `backend_stack` session fixture). A real DB is required because the harness
# runs sync ORM code from async tests and disables migrations (below).
DATABASES["default"] = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "testdb",
    "USER": "test",
    "PASSWORD": "test",
    "HOST": "localhost",
    "PORT": "5555",
}
AUTHENTIKATE = {
    **AUTHENTIKATE,
    "static_tokens": {
        "test": {"sub": "1"},
        # A non-privileged user in a different organization, for cross-tenant
        # scoping/permission tests. roles must be set explicitly: StaticToken
        # defaults roles to ["admin"], which would let this user do anything and
        # defeat the cross-org denial tests.
        "othertest": {"sub": "9", "active_org": "other_org", "roles": []},
    },
}


# Disable migrations for faster tests
class DisableMigrations:
    """Disable migrations during testing for faster test execution."""

    def __contains__(self, item: str) -> bool:
        """Check if item is in migration modules."""
        return True

    def __getitem__(self, item: str) -> None:
        """Get migration module for item."""
        return None


MIGRATION_MODULES = DisableMigrations()

# Disable logging during tests to reduce noise
logging.disable(logging.CRITICAL)

# Enable database access from async code in tests
DATABASE_ROUTERS = []

# Use in-memory channel layer for tests instead of Redis
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
