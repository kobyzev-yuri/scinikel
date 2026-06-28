"""Semantic search over documents and entity descriptions."""

from dataclasses import dataclass

from scinikel.config import CHROMA_PATH, settings
from scinikel.models.entities import Document, Entity


@dataclass
class SearchHit:
    id: str
    text: str
    score: float
    metadata: dict


class DocumentIndex:
    """
    ChromaDB index для внутренних документов.
    Без chromadb или при ошибке — fallback на keyword search.
    """

    def __init__(self) -> None:
        self._collection = None
        self._fallback: list[dict] = []
        self._init_chroma()

    def _init_chroma(self) -> None:
        try:
            import chromadb

            CHROMA_PATH.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            self._collection = client.get_or_create_collection(settings.chroma_collection)
        except Exception:
            self._collection = None

    def index_documents(self, documents: list[Document], texts: dict[str, str]) -> int:
        if not documents:
            return 0

        payloads = []
        for doc in documents:
            text = texts.get(doc.id) or doc.description or doc.name
            meta = {"title": doc.name, "doc_type": doc.attributes.get("doc_type", "")}
            payloads.append({"id": doc.id, "text": text, "metadata": meta})

        self._fallback = payloads

        if self._collection is not None:
            try:
                self._collection.upsert(
                    ids=[p["id"] for p in payloads],
                    documents=[p["text"] for p in payloads],
                    metadatas=[p["metadata"] for p in payloads],
                )
            except Exception:
                self._collection = None

        return len(payloads)

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        if self._collection is not None:
            try:
                if self._collection.count() > 0:
                    results = self._collection.query(query_texts=[query], n_results=min(limit, 20))
                    hits: list[SearchHit] = []
                    for i, doc_id in enumerate(results["ids"][0]):
                        hits.append(
                            SearchHit(
                                id=doc_id,
                                text=results["documents"][0][i] or "",
                                score=1.0 - (results["distances"][0][i] if results["distances"] else 0),
                                metadata=results["metadatas"][0][i] or {},
                            )
                        )
                    return hits
            except Exception:
                pass

        needle = query.lower()
        scored = []
        for item in self._fallback:
            text = item["text"].lower()
            score = sum(1 for word in needle.split() if word in text) / max(len(needle.split()), 1)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchHit(id=item["id"], text=item["text"], score=score, metadata=item["metadata"])
            for score, item in scored[:limit]
        ]


def entity_to_snippet(entity: Entity) -> str:
    parts = [entity.name]
    if entity.description:
        parts.append(entity.description)
    for key, val in entity.attributes.items():
        if val:
            parts.append(f"{key}: {val}")
    return " | ".join(parts)
