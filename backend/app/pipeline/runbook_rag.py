from functools import lru_cache

import chromadb

from app.config import settings

COLLECTION_NAME = "runbooks"


@lru_cache
def get_chroma_client() -> chromadb.ClientAPI:
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(settings.chroma_dir))


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(COLLECTION_NAME)


def query_runbook(query_text: str) -> dict | None:
    collection = get_collection()
    if collection.count() == 0:
        return None
    results = collection.query(query_texts=[query_text], n_results=1)
    if not results["ids"] or not results["ids"][0]:
        return None
    return {
        "runbook_id": results["ids"][0][0],
        "title": results["metadatas"][0][0].get("title", results["ids"][0][0]),
        "excerpt": results["documents"][0][0],
    }
