"""Whose memories a request reaches: only the assigner of the task it is made for.

An app is logged in by someone, but runs tasks for whoever assigned them. Its own login must never
open anybody's memories, its installer's included: the only way in is the provenance token of the
task the app is running (``rath``'s task header, verified by authentikate and bound to the app that
presents it). The token names the human at the root of the task's tree (``rcb``), the same however
deep the task was delegated, and the organization the task runs in (``org``).

Nothing crosses organizations: the task's organization (its identifier, ``"<iss>#<org>"``) must be
the one the app's login acts in. rekuest only lets a member of an organization start a task tree
in it, so the assigner it signs for is one; a person blocked here is refused all the same.

A ``sub`` is only unique per issuer, and ``rcb`` is a bare sub: it is a member of the task's
organization, so it is resolved with *that organization's* issuer -- never the issuer of whatever
token the app logged in with. No resolver takes a user or an organization: this is the only way
to name them.
"""

import re

from arkitekt_service.collaborations.guests import guest_of
from authentikate.models import Membership, Organization, User
from kante.types import Info

_NOT_IN_USERNAME = re.compile(r"[^\w.@+-]")


class MemoryNeedsTask(PermissionError):
    """Raised for a request that carries no task: memories are reached only from a task."""


class MemoryOrganizationMismatch(PermissionError):
    """Raised when the task runs in another organization than the request, or names none."""


class MemoryAssignerBlocked(PermissionError):
    """Raised when the task's assigner is blocked in the organization."""


def memory_owner(info: Info) -> tuple[User, Organization]:
    """The person whose memories this request reaches, and the organization they are kept in."""
    request = info.context.request
    if guest_of(info) is not None:
        raise MemoryNeedsTask("A guest of the organization keeps no memories here")
    try:
        provenance = request.get_extension("provenance")
    except ValueError:
        provenance = None
    if provenance is None:
        raise MemoryNeedsTask("Memories are reached only from a task: send the task's provenance token")

    organization = request.organization
    if provenance.org is None or organization is None or provenance.org != organization.identifier:
        raise MemoryOrganizationMismatch("The task runs in another organization than this request")

    user = _assigner(request.user, provenance.rcb, organization.issuer)
    if Membership.objects.filter(user=user, organization=organization, blocked=True).exists():
        raise MemoryAssignerBlocked("The task's assigner is blocked in this organization")
    return user, organization


def _assigner(caller: User | None, sub: str, issuer: str) -> User:
    """The user ``sub`` of ``issuer`` names: the caller itself for a task it assigned, else that user.

    An assigner who never called alpaka themselves has no row yet; the signed token is what
    vouches for them, so the row is made here (authentikate fills in the profile on their own
    first request).
    """
    if caller is not None and caller.sub == sub and caller.iss == issuer:
        return caller
    user, _ = User.objects.get_or_create(
        sub=sub,
        iss=issuer,
        defaults={"username": _NOT_IN_USERNAME.sub("-", f"{issuer}_{sub}")[:150]},
    )
    return user
