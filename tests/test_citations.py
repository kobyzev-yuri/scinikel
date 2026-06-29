"""Tests for citation building in ResearchAgent."""

from scinikel.agent.assistant import ResearchAgent
from scinikel.query.engine import QueryResult


def test_build_citations_includes_documents_and_images():
    qr = QueryResult(
        answer="ok",
        experiments=[
            {
                "experiment": {"id": "EXP-1", "name": "Тест"},
                "materials": [{"name": "Ni-Cu"}],
                "modes": [{"name": "флотация pH 10.5"}],
                "measurements": [{"value": "87% Ni"}],
            }
        ],
        sources=[
            {
                "id": "doc-1",
                "title": "Отчёт",
                "snippet": "фрагмент текста",
                "excerpt_type": "text",
                "score": 0.81,
            }
        ],
        images=[
            {
                "id": "doc-1-p6-i1",
                "title": "Страница 6, рис. 1",
                "snippet": "график Ni",
                "score": 0.28,
                "page": 6,
            }
        ],
    )
    citations = ResearchAgent._build_citations(qr)
    types = [c["type"] for c in citations]
    assert types == ["experiment", "document", "image"]
    assert citations[0]["id"] == "EXP-1"
    assert citations[1]["snippet"] == "фрагмент текста"
    assert citations[2]["page"] == 6
