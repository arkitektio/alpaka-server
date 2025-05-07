import strawberry
from typing import Optional, List
from strawberry import scalars
from llm import enums


@strawberry.input(description="A large language model to change with")
class ChromeCollectionInput:
    """A large language model provider"""
    name: str
    description: str
    
    
@strawberry.input(description="A function definition for a large language model")
class StructureInput:
    " A structure definition for a large language model"
    identifier: str
    object: str


@strawberry.input(description="A document to put into the vector database")
class DocumentInput:
    """A document input for a large language model"""
    
    content: str
    structure:  StructureInput | None = None
    id: str | None = None
    metadata: Optional[scalars.JSON] = None




@strawberry.input(description="A function call for a large language model")
class QueryInput:
    """ A query input for a large language model"""
    query_texts: List[str]
    n_results: Optional[int] = 5
    where: Optional[scalars.JSON] = None
    
    
    
@strawberry.input
class AddDocumentsToCollectionInput:
    collection: strawberry.ID
    documents: List[DocumentInput]


@strawberry.input
class ChromaCollectionInput:
    name: str
    embedder: strawberry.ID
    description: Optional[str] = None
    is_public: Optional[bool] = False


@strawberry.input
class DeleteCollectionInput:
    id: strawberry.ID

