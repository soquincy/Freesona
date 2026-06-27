# utils/chroma.py: ChromaDB utility functions for managing and querying a ChromaDB collection.
import os
from typing import Any

import logging
logger = logging.getLogger("FreesonaBot")

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
        docs = result.get("documents", []) or []
        
        # Flatten structure: Chroma returns [[doc1, doc2]]
        flattened = [item for sublist in docs for item in sublist]
        return [doc for doc in flattened if isinstance(doc, str) and doc.strip()]
    except Exception as e:
        logger.error(f"Chroma query error: {e}")
        return []