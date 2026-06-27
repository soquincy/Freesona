import os
from typing import Any

try:
    import chromadb
except ImportError:  # pragma: no cover - optional dependency
    chromadb = None

from dotenv import load_dotenv

load_dotenv()


def get_chroma_client() -> Any | None:
    if chromadb is None:
        return None
    persist_directory = os.getenv("CHROMA_PERSIST_DIRECTORY", "./.chroma")
    return chromadb.PersistentClient(path=persist_directory)


def get_collection(collection_name: str | None = None) -> Any | None:
    client = get_chroma_client()
    if client is None:
        return None
    name = collection_name or os.getenv("CHROMA_COLLECTION", "freesona")
    return client.get_or_create_collection(name=name)


def query_knowledge(query: str, limit: int = 3, collection_name: str | None = None) -> list[str]:
    collection = get_collection(collection_name)
    if collection is None:
        return []
    try:
        result = collection.query(query_texts=[query], n_results=limit)
    except Exception:
        return []
    documents = result.get("documents", []) or []
    if not documents:
        return []
    return [doc for chunk in documents for doc in chunk if isinstance(doc, str) and doc.strip()]
