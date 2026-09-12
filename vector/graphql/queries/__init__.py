"""Read-side resolvers for the vector app."""

from .collection import chroma_collection
from .document import documents

__all__ = ["chroma_collection", "documents"]
