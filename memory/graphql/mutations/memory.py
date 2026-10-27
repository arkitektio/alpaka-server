"""Writing the assigner's memories.

A memory is found and replaced by its name: remembering under a name that exists rewrites it, so
an assistant updates what it knew rather than piling up near-duplicates.
"""

from kante.types import Info

from memory import inputs, models, types
from memory.owner import memory_owner


def remember(info: Info, input: inputs.MemoryInput) -> types.Memory:
    """Remember something about the person who assigned the task, replacing the memory of that name."""
    user, organization = memory_owner(info)
    memory, _ = models.Memory.objects.for_write().update_or_create(
        organization=organization,
        user=user,
        name=input.name.strip(),
        defaults=dict(description=input.description.strip(), content=input.content, kind=input.kind.value),
    )
    return memory


def forget(info: Info, input: inputs.ForgetInput) -> bool:
    """Forget the memory of that name; whether there was one."""
    user, organization = memory_owner(info)
    deleted, _ = models.Memory.objects.for_organization(organization).filter(user=user, name=input.name.strip()).delete()
    return deleted > 0
