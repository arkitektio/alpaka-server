from django.conf import settings
from django.core.management.base import BaseCommand

from alpaka_server.configuration import ProviderPartnerConfigModel
from llm.models import ProviderPartner


class Command(BaseCommand):
    help = "Import provider partners from the validated config. Run before organizations are created."

    def handle(self, *args, **options):
        # Re-validate the config-sourced list (settings stores plain dicts).
        config = ProviderPartnerConfigModel(partners=settings.PROVIDER_PARTNERS)

        for partner in config.partners:
            filter_config_data = partner.filter_config.model_dump() if partner.filter_config else {}

            provider_partner, created = ProviderPartner.objects.update_or_create(
                identifier=partner.identifier,
                defaults={
                    "name": partner.name,
                    "kind": partner.kind,
                    "description": partner.description,
                    "short_description": partner.short_description,
                    "logo_url": partner.logo_url,
                    "api_key": partner.api_key,
                    "api_base": partner.api_base,
                    "additional_config": partner.additional_config,
                    "auto_configure": partner.auto_configure,
                    "filter_config": filter_config_data,
                },
            )

            verb = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{verb} ProviderPartner: {provider_partner.identifier}"))
            if partner.auto_configure:
                self.stdout.write(self.style.WARNING("  -> Auto-configure enabled: a Provider will be created for every new organization"))
            if filter_config_data:
                self.stdout.write(self.style.SUCCESS(f"  -> Filter config: {filter_config_data}"))
