from django.apps import AppConfig


class LLMConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "llm"

    def ready(self):
        import alpaka_server.checks  # noqa: F401
        # Connect the organization post_save receiver that auto-provisions providers.
        from llm import signals  # noqa: F401
