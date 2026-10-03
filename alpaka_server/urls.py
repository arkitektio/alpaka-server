"""URL configuration for the alpaka service.

Every route goes through kante's ``dynamicpath`` so it honours the
``MY_SCRIPT_NAME`` prefix; the GraphQL endpoint itself is mounted by
``kante.router`` in asgi.py.
"""

from django.contrib import admin
from kante.path import dynamicpath
from django.urls import include

from health_check.views import MainView
from django.views.decorators.csrf import csrf_exempt
from rekuest_service.views import answers_challenge
from alpaka_server.hook_agent import agent as hook_agent
from alpaka_server.service import service as rekuest_service

urlpatterns = [
    dynamicpath("admin/", admin.site.urls),
    dynamicpath("llm/", include("llm.urls")),
    dynamicpath("ht", answers_challenge(csrf_exempt(MainView.as_view())), name="health_check"),
    # What this service hosts and emits, read by the hub's rekuest (internal network only).
    *rekuest_service.urls,
    # This process's hook agent: the hub's rekuest POSTs it Assigns (internal network only). Not the service's.
    *hook_agent.urls,
]
