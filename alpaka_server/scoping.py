"""Organization scoping for tenant-owned models.

Alpaka is multi-tenant: every room, provider, model and collection belongs to
one organization, and the request's organization arrives on
``info.context.request.organization``. Nothing structural enforces that a query
respects it, so a single forgotten ``organization`` filter is a cross-tenant
leak — and the GraphQL resolvers were full of bare ``objects.get(id=...)``.

This module removes the unsafe spelling. ``Model.objects`` has no default
queryset at all, so ``Model.objects.filter(...)`` raises instead of quietly
returning every organization's rows. The only way to get a queryset is to name
an organization.

Ported from kraph's ``evidence.managers`` (same stack, same problem), with a
``field`` hook so models that reach their organization through a relation —
``LLMModel`` via ``provider__organization`` — can use the same manager.
"""

from typing import TYPE_CHECKING, Any

from django.db import models

if TYPE_CHECKING:
    from authentikate.models import Organization


class UnscopedAccess(RuntimeError):
    """Raised when a tenant-owned model is queried without naming an organization."""


class OrganizationScopedManager(models.Manager):  # type: ignore[type-arg]
    """A manager with no usable default queryset.

    Every read has to go through :meth:`for_organization`, which is the whole
    point: there is no spelling of "just get me the rows" that silently spans
    tenants. Django's own internals (cascade deletion, reverse FK descriptors,
    the admin, the migration executor) do not use this manager — the models set
    ``base_manager_name``/``default_manager_name`` to ``all_objects`` so the
    framework keeps working while application code stays fenced in.

    ``field`` is the lookup path from this model to its organization. It is
    ``"organization"`` for models that own the FK directly and
    ``"provider__organization"`` for :class:`llm.models.LLMModel`, which reaches
    it through its provider.
    """

    def __init__(self, field: str = "organization") -> None:
        """Bind the manager to the lookup path that reaches the organization."""
        super().__init__()
        self.field = field

    def get_queryset(self) -> models.QuerySet[Any]:
        """Refuse to produce an unscoped queryset."""
        raise UnscopedAccess(
            f"{self.model.__name__}.objects has no default queryset because it is "
            f"organization-scoped. Use {self.model.__name__}.objects.for_organization(org).\n"
            f"If you genuinely need to cross organizations — a migration, a management "
            f"command, a test fixture — use {self.model.__name__}.all_objects and leave a "
            f"comment saying why."
        )

    def for_organization(self, organization: "Organization | int") -> models.QuerySet[Any]:
        """The only supported entry point for reading tenant-owned rows."""
        return super().get_queryset().filter(**{self.field: organization})

    def for_write(self) -> models.QuerySet[Any]:
        """An unfiltered queryset, for writes only.

        A write names its organization on the row it is creating — directly for
        the models that own the FK, or through ``provider`` for
        :class:`llm.models.LLMModel` — so filtering the queryset first would add
        nothing. Reads must go through :meth:`for_organization`; this exists so
        the write sites do not have to reach for ``all_objects``, which would
        make an accidental unscoped *read* indistinguishable from a legitimate
        write at a glance.
        """
        return super().get_queryset()
