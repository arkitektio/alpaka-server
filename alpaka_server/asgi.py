"""
ASGI config for the alpaka service.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/asgi/
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "alpaka_server.settings")
from django.core.asgi import get_asgi_application

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()


from .schema import schema  # noqa: E402
from kammer.consumers import MessageStreamConsumer  # noqa: E402
from kante.path import re_dynamicpath  # noqa: E402
from kante.router import router  # noqa: E402


application = router(
    schema=schema,
    django_asgi_app=django_asgi_app,
    schema_path="schema",
    additional_websocket_urlpatterns=[
        # Streaming replies into rooms, one frame per token, without a GraphQL
        # mutation per delta (see kammer.consumers for the protocol).
        re_dynamicpath(r"^kammer/stream/?$", MessageStreamConsumer.as_asgi()),
    ],
)
