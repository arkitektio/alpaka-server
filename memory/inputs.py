import strawberry

from memory.enums import MemoryKind


@strawberry.input(description="Something to remember about the person who assigned the task")
class MemoryInput:
    """A memory, written over the one of the same name if there is one."""

    name: str = strawberry.field(description="A short slug to find and replace the memory by: `prefers-tiff-exports`")
    description: str = strawberry.field(description="One line saying what the memory holds, read in the index every turn")
    content: str = strawberry.field(description="The memory itself")
    kind: MemoryKind = strawberry.field(default=MemoryKind.USER, description="What the memory is about")


@strawberry.input(description="A memory to forget")
class ForgetInput:
    """The memory to delete, by its name."""

    name: str
