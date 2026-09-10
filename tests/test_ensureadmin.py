"""``manage.py ensureadmin`` provisions the ``django.admin`` superuser idempotently.

run.sh has called this command since v1, but it never existed, so the configured
superuser was silently never created."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

User = get_user_model()


@pytest.mark.django_db(transaction=True)
def test_ensureadmin_creates_then_updates(settings):
    settings.DJANGO_ADMIN = {"username": "root", "password": "pw-1", "email": "r@x.io"}
    call_command("ensureadmin")

    user = User.objects.get(username="root")
    assert user.is_superuser and user.is_staff and user.is_active
    assert user.email == "r@x.io"
    assert user.check_password("pw-1")

    # A rotated password (and a demoted flag) is re-asserted on the next boot.
    user.is_superuser = False
    user.save()
    settings.DJANGO_ADMIN = {"username": "root", "password": "pw-2"}
    call_command("ensureadmin")

    assert User.objects.filter(username="root").count() == 1
    user.refresh_from_db()
    assert user.is_superuser
    assert user.check_password("pw-2")
    assert user.email == "r@x.io"  # not blanked when config omits it


@pytest.mark.django_db(transaction=True)
def test_ensureadmin_is_a_noop_without_config(settings):
    settings.DJANGO_ADMIN = None
    call_command("ensureadmin")
    assert not User.objects.filter(is_superuser=True).exists()
