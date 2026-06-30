"""SQLite-хранилище диалогов."""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scinikel.config import DATA_DIR

DB_PATH = DATA_DIR / "conversations.db"

_CITATION_KEYS = (
    "type",
    "id",
    "title",
    "image_url",
    "page",
    "snippet",
    "librarian_annotation",
    "key_points",
    "doc_id",
    "doc_title",
    "score",
    "chunk_id",
    "excerpt_type",
    "figure_type",
    "media_label",
)


@dataclass
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str


@dataclass
class StoredMessage:
    id: int
    conversation_id: str
    role: str
    content: str
    meta: str | None
    created_at: str


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                meta TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages(conversation_id, id);
            """
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def slim_citations(citations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Компактные citations для meta assistant-сообщения (галерея при reload)."""
    if not citations:
        return []
    slim: list[dict[str, Any]] = []
    for item in citations[:12]:
        row = {k: item[k] for k in _CITATION_KEYS if k in item and item[k] is not None}
        if row:
            slim.append(row)
    return slim


def encode_assistant_meta(
    *,
    llm_used: bool,
    experiment_id: str | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> str:
    """JSON meta для assistant: kind, exp_id, citations (обратносовместимо со строкой llm:EXP)."""
    payload: dict[str, Any] = {
        "v": 1,
        "kind": "llm" if llm_used else "graph",
    }
    if experiment_id:
        payload["exp_id"] = experiment_id
    slim = slim_citations(citations)
    if slim:
        payload["citations"] = slim
    return json.dumps(payload, ensure_ascii=False)


def parse_assistant_meta(meta: str | None) -> dict[str, Any]:
    """Разбор meta: JSON (новый) или llm:EXP-… (старый)."""
    if not meta:
        return {"kind": "", "exp_id": None, "citations": None}
    raw = meta.strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {
                    "kind": data.get("kind") or "",
                    "exp_id": data.get("exp_id"),
                    "citations": data.get("citations"),
                }
        except json.JSONDecodeError:
            pass
    kind, _, tail = raw.partition(":")
    exp_id = tail if tail.startswith("EXP-") else None
    return {"kind": kind or raw, "exp_id": exp_id, "citations": None}


def create_conversation(title: str = "Новый диалог") -> Conversation:
    init_db()
    conv_id = str(uuid.uuid4())
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conv_id, title[:120], now, now),
        )
    return Conversation(id=conv_id, title=title[:120], created_at=now, updated_at=now)


def list_conversations(limit: int = 50) -> list[Conversation]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [Conversation(**dict(row)) for row in rows]


def get_conversation(conv_id: str) -> Conversation | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conv_id,),
        ).fetchone()
    return Conversation(**dict(row)) if row else None


def get_messages(conv_id: str) -> list[StoredMessage]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, conversation_id, role, content, meta, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id
            """,
            (conv_id,),
        ).fetchall()
    return [StoredMessage(**dict(row)) for row in rows]


def add_message(
    conv_id: str,
    role: str,
    content: str,
    *,
    meta: str | None = None,
    title_hint: str | None = None,
) -> StoredMessage:
    init_db()
    now = _now()
    with _connect() as conn:
        if not conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conv_id,)).fetchone():
            raise KeyError(f"Conversation {conv_id} not found")
        cur = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, meta, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conv_id, role, content, meta, now),
        )
        if title_hint and role == "user":
            count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND role = 'user'",
                (conv_id,),
            ).fetchone()[0]
            if count == 1:
                conn.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (title_hint[:120], now, conv_id),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conv_id),
                )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conv_id),
            )
        msg_id = cur.lastrowid
    return StoredMessage(
        id=int(msg_id),
        conversation_id=conv_id,
        role=role,
        content=content,
        meta=meta,
        created_at=now,
    )


def delete_conversation(conv_id: str) -> bool:
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    return cur.rowcount > 0


def conversation_payload(conv_id: str) -> dict[str, Any] | None:
    conv = get_conversation(conv_id)
    if not conv:
        return None
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "meta": m.meta,
                "created_at": m.created_at,
            }
            for m in get_messages(conv_id)
        ],
    }
