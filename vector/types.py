import datetime
import strawberry
from typing import Optional, List
from strawberry.types import Info
from vector import models, enums, filters
import strawberry_django
from strawberry import scalars
from authentikate.strawberry.types import User

# --- Strawberry types ---

# --- RETURN TYPES ---

@strawberry.type(description="The type of the tool")
class Structure:
    identifier: str 
    object: str



# Output type for similarity results
@strawberry.type
class Document:
    _metadata: strawberry.Private[dict]
    id: str
    content: str
    distance: Optional[float] = None
    
    @strawberry.field
    def metadata(self) -> Optional[scalars.JSON]:
        """Get the metadata for the document"""
        return self._metadata
    
    @strawberry.field(description="A function definition for a large language model")
    def structure(self) -> Optional[Structure]:
        """Get the structure for the document"""
        if self._metadata and "identifier" in self._metadata:
            return Structure(identifier=self._metadata["identifier"], object=self._metadata["object"])
        return None



@strawberry_django.type(models.ChromaCollection, description="A collection of documents searchable by string", filters=filters.ChromaCollectionFilter, pagination=True)
class ChromaCollection:
    """A provider of LLMs"""
    id: strawberry.ID
    name: str
    description: str 
    created_at: datetime.datetime
    owner: User 
    
    @strawberry_django.field
    def count(self, info: Info) -> int:
        """Count the number of items in the collection"""
        return models.ChromaCollection.objects.filter(name=self.name).count()
    
    
    