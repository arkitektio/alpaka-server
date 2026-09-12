"""Register an Ollama server as a provider for an organization and list its models.

    python manage.py inspectollama --organization <slug> [--url http://ollama:11434] [--name ollama] [--force]

Model discovery is delegated to :func:`llm.logic.arefresh_provider_models`, the
same code path the ``refreshProvider`` mutation uses, so the command cannot
drift from it.
"""

import asyncio

from authentikate.models import Organization
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from llm.enums import ProviderKind
from llm.logic import arefresh_provider_models
from llm.models import Provider


class Command(BaseCommand):
    help = "Create an Ollama provider for an organization and inspect its installed models"

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True, help="Slug of the authentikate Organization that owns the provider")
        parser.add_argument("--url", type=str, default=settings.OLLAMA_URL, help="Ollama API URL (default: from settings.OLLAMA_URL)")
        parser.add_argument("--name", type=str, default="ollama", help="Provider name (default: ollama)")
        parser.add_argument("--force", action="store_true", help="Delete and recreate the provider if it already exists")

    def handle(self, *args, **options):
        slug = options["organization"]
        ollama_url = options["url"]
        provider_name = options["name"]

        try:
            organization = Organization.objects.get(slug=slug)
        except Organization.DoesNotExist:
            known = list(Organization.objects.values_list("slug", flat=True))
            raise CommandError(f"No organization with slug {slug!r}. Known organizations: {known}")

        self.stdout.write(f"Inspecting Ollama at {ollama_url} for organization {organization.slug!r}")

        if options["force"]:
            # A management command runs outside any request, so it has no
            # request organization to scope to; the filter is explicit instead.
            deleted, _ = Provider.all_objects.filter(organization=organization, name=provider_name).delete()
            if deleted:
                self.stdout.write(f"Deleted existing provider: {provider_name}")

        provider, created = Provider.objects.for_write().update_or_create(
            organization=organization,
            name=provider_name,
            defaults={
                "description": f"Ollama LLM provider at {ollama_url}",
                "api_base": ollama_url,
                "api_key": None,  # Ollama doesn't require an API key
                "kind": ProviderKind.OLLAMA.value,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Using existing'} provider: {provider.name}"))

        try:
            # No event loop is running inside a management command, and the
            # refresh already uses the async ORM + aiohttp.
            models = asyncio.run(arefresh_provider_models(provider))
        except Exception as exc:
            raise CommandError(f"Failed to refresh models from {ollama_url}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Refreshed {len(models)} models for provider {provider.name}"))
        self.stdout.write("-" * 80)
        for model in models:
            features = ", ".join(model.get_features()) or "No features"
            self.stdout.write(f"• {model.label}")
            self.stdout.write(f"  Model ID:   {model.model_id}")
            self.stdout.write(f"  LLM string: {model.llm_string}")
            self.stdout.write(f"  Features:   {features}")
