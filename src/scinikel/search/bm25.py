"""BM25 keyword search по чанкам — fallback когда Qdrant/e5 недоступны (этап 1 roadmap)."""

from __future__ import annotations

import math
import re
from typing import Any

TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Okapi BM25 (Robertson–Walker)
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return [t.lower().replace("ё", "е") for t in TOKEN_RE.findall(text) if len(t) > 1]


class BM25Index:
    """In-memory BM25 по списку чанков (паттерн payload как в vector_db / dedup)."""

    def __init__(self) -> None:
        self._docs: list[dict[str, Any]] = []
        self._tokens: list[list[str]] = []
        self._df: dict[str, int] = {}
        self._avgdl = 0.0

    def __len__(self) -> int:
        return len(self._docs)

    def rebuild(self, documents: list[dict[str, Any]]) -> None:
        """documents: {id, text, metadata} — как в DocumentIndex._chunks."""
        self._docs = list(documents)
        self._tokens = [tokenize(doc.get("index_text") or doc.get("text") or "") for doc in self._docs]
        self._df = {}
        lengths: list[int] = []
        for toks in self._tokens:
            lengths.append(len(toks))
            for term in set(toks):
                self._df[term] = self._df.get(term, 0) + 1
        self._avgdl = sum(lengths) / max(len(lengths), 1)

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not self._docs:
            return []

        q_terms = tokenize(query)
        if not q_terms:
            return []

        n = len(self._docs)
        scores: list[tuple[int, float]] = []

        for idx, doc_toks in enumerate(self._tokens):
            dl = len(doc_toks)
            if dl == 0:
                continue
            tf: dict[str, int] = {}
            for t in doc_toks:
                tf[t] = tf.get(t, 0) + 1

            score = 0.0
            for term in q_terms:
                if term not in self._df:
                    continue
                freq = tf.get(term, 0)
                if freq == 0:
                    continue
                idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                denom = freq + K1 * (1 - B + B * dl / self._avgdl)
                score += idf * (freq * (K1 + 1)) / denom

            if score > 0:
                scores.append((idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        results: list[dict[str, Any]] = []
        for idx, score in scores[:limit]:
            doc = self._docs[idx]
            meta = dict(doc.get("metadata") or {})
            results.append(
                {
                    "id": doc.get("id") or meta.get("chunk_id") or meta.get("doc_id"),
                    "text": doc.get("text") or meta.get("text", ""),
                    "score": score,
                    "metadata": meta,
                    "backend": "bm25",
                }
            )
        return results
