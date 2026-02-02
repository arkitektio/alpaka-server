from django.urls import path, re_path
from .views import (
    # OpenAI-compatible endpoints
    openai_models_view,
    openai_model_detail_view,
    openai_chat_completions_view,
    openai_completions_view,
    openai_embeddings_view,
    # Legacy endpoints (for backward compatibility)
    models_view,
    generate_view,
    chat_view,
)

urlpatterns = [
    # OpenAI-compatible API routes (v1)
    path("v1/models", openai_models_view, name="openai_models"),
    path("v1/models/", openai_models_view, name="openai_models_slash"),
    re_path(r"^v1/models/(?P<model_id>.+)$", openai_model_detail_view, name="openai_model_detail"),
    path("v1/chat/completions", openai_chat_completions_view, name="openai_chat_completions"),
    path("v1/chat/completions/", openai_chat_completions_view, name="openai_chat_completions_slash"),
    path("v1/completions", openai_completions_view, name="openai_completions"),
    path("v1/completions/", openai_completions_view, name="openai_completions_slash"),
    path("v1/embeddings", openai_embeddings_view, name="openai_embeddings"),
    path("v1/embeddings/", openai_embeddings_view, name="openai_embeddings_slash"),
    # Legacy Ollama-style endpoints (kept for backward compatibility)
    path("models/", models_view, name="legacy_models"),
    path("generate/", generate_view, name="legacy_generate"),
    path("chat/", chat_view, name="legacy_chat"),
]
