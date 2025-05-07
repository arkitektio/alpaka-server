
import chromadb
from chromadb.utils import embedding_functions
from django.conf import settings

# Direct Chroma client (used without Django)


async def aget_client():
    return await chromadb.AsyncHttpClient(host=settings.CHROMA_DB_HOST, port=settings.CHROMA_DB_PORT)