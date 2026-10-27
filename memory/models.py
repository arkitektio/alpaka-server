from alpaka_server.scoping import OrganizationScopedManager
from authentikate.models import Organization, User
from django.db import models
from embeddings.models import EmbeddedDescriptionMixin, embedding_indexes

from memory.enums import MemoryKind


class Memory(EmbeddedDescriptionMixin, models.Model):
    """One thing an assistant remembers about a person, in one organization.

    A person's memories are theirs: an app reaches them only for the person who assigned the task
    it runs (``memory.owner``), never for whoever logged the app in. ``name`` is what the memory is
    found and replaced by; ``description`` is the one line an assistant reads in the index it gets
    every turn, and ``content`` the whole of it, read when it is needed. Embeds all three, so a
    search finds a memory by what it says.
    """

    embedding_source_fields = ("name", "description", "content")

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, help_text="The organization the memory was made in")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memories", help_text="Whom the memory is about, and whose it is")
    name = models.CharField(max_length=200, help_text="A short slug the memory is found and replaced by, unique per person")
    description = models.CharField(max_length=500, help_text="One line saying what the memory holds: what an assistant reads in the index")
    kind = models.CharField(max_length=20, choices=[(kind.value, kind.value) for kind in MemoryKind], default=MemoryKind.USER.value)
    content = models.TextField(help_text="The memory itself")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        constraints = [models.UniqueConstraint(fields=["organization", "user", "name"], name="memory_unique_name")]
        # The embedding healer's "any row not by the current model?" probe.
        indexes = [*embedding_indexes("memory")]

    def __str__(self) -> str:
        return self.name
