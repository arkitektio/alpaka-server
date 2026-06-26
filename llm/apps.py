from django.apps import AppConfig


class LLMConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "llm"

    def ready(self):
        # Connect the organization post_save receiver that auto-provisions providers.
        from llm import signals  # noqa: F401
