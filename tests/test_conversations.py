"""Tests for conversation storage."""

from scinikel.storage import conversations as store


def test_create_and_list_conversation(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    conv = store.create_conversation("Тест")
    assert conv.id
    listed = store.list_conversations()
    assert any(c.id == conv.id for c in listed)


def test_add_and_load_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    conv = store.create_conversation()
    store.add_message(conv.id, "user", "Привет", title_hint="Привет")
    store.add_message(conv.id, "assistant", "Ответ", meta="llm:EXP-2023-044")
    payload = store.conversation_payload(conv.id)
    assert payload is not None
    assert len(payload["messages"]) == 2
    assert payload["title"] == "Привет"
    assert payload["messages"][1]["meta"] == "llm:EXP-2023-044"
