from enum import Enum

import strawberry


@strawberry.enum(description="What a memory is about")
class MemoryKind(str, Enum):
    """The kind of a memory, the way an assistant files what it learned about a person."""

    USER = "USER"
    """Who they are: their role, what they know, what they prefer."""
    FEEDBACK = "FEEDBACK"
    """How they want the work done: a correction, or an approach they confirmed."""
    PROJECT = "PROJECT"
    """What they are working on: goals, constraints, deadlines."""
    REFERENCE = "REFERENCE"
    """Where to look: datasets, instruments, documents they named."""
