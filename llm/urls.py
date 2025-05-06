from django.urls import path
from .views import models_view, generate_view, chat_view

x = 1
urlpatterns = [
    path("models/", models_view),
    path("generate/", generate_view),
    path("chat/", chat_view),
]
