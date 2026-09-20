# api/models.py
from alpaka_server.scoping import OrganizationScopedManager
from django.db import models
from embeddings.models import EmbeddedDescriptionMixin, embedding_indexes
from authentikate.models import User, Organization


class ChromaCollection(EmbeddedDescriptionMixin, models.Model):
    """A Chroma document collection's metadata row; embeds its name + description for ``search``.

    The collection's *documents* are embedded by its own LLM ``embedder`` and live in Chroma;
    this row's vector describes the collection itself.
    """

    name = models.CharField(max_length=100, help_text="The human-readable name of the collection, unique within its organization")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Optional: ownership or visibility
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    embedder = models.ForeignKey("llm.LLMModel", on_delete=models.CASCADE, related_name="embedder_for")
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        help_text="The organization this collection belongs to",
    )

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        unique_together = ("organization", "name")
        # The embedding healer's "any row not by the current model?" probe.
        indexes = [*embedding_indexes("chroma_collection")]

    def __str__(self):
        return self.name

    @property
    def chroma_name(self) -> str:
        """The name this collection is stored under in Chroma.

        Chroma's namespace is global while ``name`` is only unique within an
        organization, so the two cannot be the same string: two organizations
        each naming a collection "docs" would collide inside Chroma. The primary
        key is the one identifier that is already unique across tenants, so the
        Chroma-side name is derived from it and ``name`` stays the human label.
        """
        return f"alpaka-{self.organization_id}-{self.pk}"
