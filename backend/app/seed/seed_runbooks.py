"""Ingests runbooks/*.md into the local persistent Chroma collection used by
the RAG retrieval step. Run: `python -m app.seed.seed_runbooks` (from
backend/, with the venv active). Safe to re-run — it recreates the
collection each time.
"""

from app.config import settings
from app.pipeline.runbook_rag import COLLECTION_NAME, get_chroma_client
from app.seed.fault_scenarios import FAULT_SCENARIOS


def seed() -> None:
    client = get_chroma_client()
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)

    runbook_filenames = {s.runbook_filename for s in FAULT_SCENARIOS.values()}

    ids, documents, metadatas = [], [], []
    for filename in sorted(runbook_filenames):
        path = settings.runbooks_dir / filename
        if not path.exists():
            print(f"skipping missing runbook: {filename}")
            continue
        content = path.read_text()
        title = content.splitlines()[0].lstrip("# ").strip()
        ids.append(filename)
        documents.append(content)
        metadatas.append({"title": title, "filename": filename})

    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    print(f"Seeded {len(ids)} runbooks into Chroma collection '{COLLECTION_NAME}'")


if __name__ == "__main__":
    seed()
