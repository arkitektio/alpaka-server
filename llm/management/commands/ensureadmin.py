"""Ensure the superuser declared under ``django.admin`` exists and matches config.

Idempotent: creates the user on first boot and, on every later boot, re-asserts
the superuser/staff/active flags, the email and the password from config so
that a rotated config takes effect on redeploy. Does nothing (and exits 0)
when no ``django.admin`` block is configured.

    python manage.py ensureadmin
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from alpaka_server.configuration import AdminSettings


class Command(BaseCommand):
    help = "Create or update the superuser declared under django.admin in the config."

    def handle(self, *args, **options) -> None:
        raw = getattr(settings, "DJANGO_ADMIN", None)
        if not raw:
            self.stdout.write("No django.admin configured - skipping superuser provisioning.")
            return

        # Re-validate the config-sourced dict, as ensurepartners does.
        admin = AdminSettings(**raw)
        User = get_user_model()

        user, created = User.objects.get_or_create(
            username=admin.username,
            defaults={"email": admin.email or "", "is_staff": True, "is_superuser": True, "is_active": True},
        )
        if not created:
            if admin.email:
                user.email = admin.email
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
        # Config is the source of truth for the password, so a rotated
        # password lands on the next boot.
        user.set_password(admin.password)
        user.save()

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} superuser '{admin.username}'."))
