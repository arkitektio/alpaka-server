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
from alpaka_server.service import service as rekuest_service

urlpatterns = [
    dynamicpath("admin/", admin.site.urls),
    dynamicpath("llm/", include("llm.urls")),
    dynamicpath("ht", csrf_exempt(MainView.as_view()), name="health_check"),
    # The hub's rekuest runs this service's periodic work through here (internal network only).
    *rekuest_service.urls,
]
