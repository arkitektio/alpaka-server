"""Signal handlers wiring auto-provisioning into organization creation.

alpaka's organizations are created lazily by the *authentikate* package during
token auth (``Organization.objects.get_or_create(slug=...)``), so we cannot edit
that code path. Instead we hook it here with a ``post_save`` receiver — mirroring
lok's ``karakter.signals.ensure_default_roles_for_org``.
"""

import logging

from authentikate.models import Organization
from django.db.models.signals import post_save
from django.dispatch import receiver

from llm.logic import auto_configure_provider_partners

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Organization)
def auto_configure_providers_for_org(sender, instance, created, **kwargs):
    """Provision providers from auto-config partners when an organization is created."""
    if not created:
        return
    try:
        auto_configure_provider_partners(instance)
    except Exception:
        # Never let provider provisioning break organization creation / auth.
        logger.exception("Failed to auto-configure providers for organization '%s'", instance)
