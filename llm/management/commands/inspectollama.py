import yaml
import requests
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.conf import settings
from llm.models import Provider, LLMModel
from llm.logic import detect_features, detect_modalities
from llm.enums import ProviderKind

User = get_user_model()


class Command(BaseCommand):
    help = "Create an ollama provider and inspect all currently installed models"

    def add_arguments(self, parser):
        parser.add_argument("--url", type=str, default=settings.OLLAMA_URL, help="Ollama API URL (default: from settings.OLLAMA_URL)")
        parser.add_argument("--name", type=str, default="ollama", help="Provider name (default: ollama)")
        parser.add_argument("--force", action="store_true", help="Force recreation of provider if it already exists")

    def handle(self, *args, **options):
        ollama_url = options["url"]
        provider_name = options["name"]
        force = options["force"]

        self.stdout.write(f"Inspecting Ollama at: {ollama_url}")

        # Test connection to Ollama
        try:
            response = requests.get(f"{ollama_url}/api/tags", timeout=10)
            if response.status_code != 200:
                self.stdout.write(self.style.ERROR(f"Failed to connect to Ollama at {ollama_url}. Status: {response.status_code}"))
                return

            tags_data = response.json()
            models = tags_data.get("models", [])

            self.stdout.write(self.style.SUCCESS(f"Successfully connected to Ollama. Found {len(models)} models."))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to connect to Ollama: {str(e)}"))
            return

        # Create or get the provider
        try:
            if force:
                # Delete existing provider if force is True
                existing_providers = Provider.objects.filter(name=provider_name)
                if existing_providers.exists():
                    existing_providers.delete()
                    self.stdout.write(f"Deleted existing provider: {provider_name}")

            provider, created = Provider.objects.update_or_create(
                name=provider_name,
                defaults={
                    "description": f"Ollama LLM provider at {ollama_url}",
                    "api_base": ollama_url,
                    "api_key": None,  # Ollama doesn't require API key
                    "kind": ProviderKind.OLLAMA.value,  # Set the kind to OLLAMA
                },
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f"Created new provider: {provider.name}"))
            else:
                self.stdout.write(f"Using existing provider: {provider.name}")

            # Display provider info
            self.stdout.write(f"Provider kind: {provider.kind}")
            self.stdout.write(f"Provider API base: {provider.api_base}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to create provider: {str(e)}"))
            return

        # Refresh models for this provider (sync version)
        try:
            self.stdout.write("Refreshing models...")
            new_models = []

            # Get models from Ollama directly (sync version of the logic)
            response = requests.get(f"{ollama_url}/api/tags", timeout=10)
            if response.status_code != 200:
                raise Exception("Failed to get Ollama models")

            data = response.json()
            for model in data.get("models", []):
                model_id = model["name"]
                features = detect_features(model_id)
                input_modalities, output_modalities = detect_modalities(model_id)
                obj, created = LLMModel.objects.update_or_create(
                    provider=provider,
                    model_id=model_id,
                    defaults={
                        "label": f"Ollama - {model_id}",
                        "features": features,
                        "input_modalities": input_modalities,
                        "output_modalities": output_modalities,
                    },
                )
                new_models.append(obj)

            self.stdout.write(self.style.SUCCESS(f"Successfully refreshed {len(new_models)} models for provider {provider.name}"))

            # Display model information
            self.stdout.write("\nDiscovered models:")
            self.stdout.write("-" * 80)

            for model in new_models:
                features_str = ", ".join(model.get_features()) if model.get_features() else "No features"
                self.stdout.write(f"• {model.label}")
                self.stdout.write(f"  Model ID: {model.model_id}")
                self.stdout.write(f"  LLM String: {model.llm_string}")
                self.stdout.write(f"  Features: {features_str}")
                self.stdout.write(f"  Available: {model.is_available}")
                self.stdout.write("")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to refresh models: {str(e)}"))
            return

        # Get additional Ollama info
        try:
            # Try to get version info
            try:
                response = requests.get(f"{ollama_url}/api/version", timeout=5)
                if response.status_code == 200:
                    version_data = response.json()
                    self.stdout.write(f"Ollama Version: {version_data.get('version', 'Unknown')}")
            except:
                pass

            self.stdout.write("\nDetailed model information from Ollama:")
            self.stdout.write("-" * 80)

            response = requests.get(f"{ollama_url}/api/tags", timeout=10)
            tags_data = response.json()

            for model in tags_data.get("models", []):
                self.stdout.write(f"• {model.get('name', 'Unknown')}")
                if "modified_at" in model:
                    self.stdout.write(f"  Modified: {model['modified_at']}")
                if "size" in model:
                    size_gb = model["size"] / (1024**3)
                    self.stdout.write(f"  Size: {size_gb:.2f} GB")
                if "digest" in model:
                    self.stdout.write(f"  Digest: {model['digest'][:16]}...")
                self.stdout.write("")

        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Could not get additional Ollama info: {str(e)}"))

        self.stdout.write(self.style.SUCCESS("Ollama inspection completed successfully!"))
