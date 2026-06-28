"""FastAPI application."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from scinikel.agent.assistant import ResearchAgent
from scinikel.config import GRAPH_PATH, ROOT, SEED_DIR, settings
from scinikel.graph import get_graph_store
from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.loader import ingest_seed_data
from scinikel.models.entities import EntityType
from scinikel.query.engine import HybridQueryEngine
from scinikel.search.index import DocumentIndex

_agent: ResearchAgent | None = None
_graph: NetworkXGraphStore | None = None


def _bootstrap() -> tuple[NetworkXGraphStore, DocumentIndex, ResearchAgent]:
    global _graph, _agent
    graph = get_graph_store()
    if isinstance(graph, NetworkXGraphStore) and graph.stats()["entities"] == 0:
        ingest_seed_data(graph, SEED_DIR)
        graph.save(GRAPH_PATH)

    doc_index = DocumentIndex()
    import json

    doc_path = SEED_DIR / "documents.json"
    if doc_path.exists():
        from scinikel.models.entities import Document

        raw_docs = json.loads(doc_path.read_text(encoding="utf-8"))
        docs = [
            Document(
                id=d["id"],
                name=d["title"],
                description=d.get("abstract"),
                attributes={"doc_type": d.get("doc_type"), "year": d.get("year")},
            )
            for d in raw_docs
        ]
        texts = {d["id"]: d.get("text", d.get("abstract", "")) for d in raw_docs}
        doc_index.index_documents(docs, texts)

    query_engine = HybridQueryEngine(graph, doc_index)
    _graph = graph
    _agent = ResearchAgent(query_engine)
    return graph, doc_index, _agent


@asynccontextmanager
async def lifespan(_: FastAPI):
    _bootstrap()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

static_dir = ROOT / "frontend" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    message: str
    citations: list[dict[str, Any]]
    experiments: list[dict[str, Any]]
    subgraph: dict[str, Any] | None = None
    gaps: list[dict[str, str]] = Field(default_factory=list)


@app.get("/", response_class=HTMLResponse)
async def index():
    template = ROOT / "frontend" / "index.html"
    if not template.exists():
        raise HTTPException(404, "UI not found")
    return HTMLResponse(template.read_text(encoding="utf-8"))


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if _agent is None:
        raise HTTPException(503, "Agent not ready")
    resp = _agent.chat(req.message)
    qr = resp.query_result
    return ChatResponse(
        message=resp.message,
        citations=resp.citations,
        experiments=qr.experiments if qr else [],
        subgraph=qr.subgraph if qr else None,
        gaps=qr.gaps if qr else [],
    )


@app.get("/api/graph/stats")
async def graph_stats():
    if _graph is None:
        raise HTTPException(503, "Graph not ready")
    return _graph.stats()


@app.get("/api/graph/subgraph/{entity_id}")
async def subgraph(entity_id: str, depth: int = 2):
    if _graph is None:
        raise HTTPException(503, "Graph not ready")
    if not _graph.get_entity(entity_id):
        raise HTTPException(404, f"Entity {entity_id} not found")
    return _graph.subgraph(entity_id, depth=depth)


@app.get("/api/entities")
async def list_entities(
    entity_type: EntityType | None = None,
    q: str | None = None,
    limit: int = 50,
):
    if _graph is None:
        raise HTTPException(503, "Graph not ready")
    entities = _graph.find_entities(entity_type=entity_type, name_contains=q, limit=limit)
    return [e.model_dump() for e in entities]


@app.post("/api/admin/reload")
async def reload_data():
    """Перезагрузка seed-данных (для итераций на хакатоне)."""
    global _graph, _agent
    graph = NetworkXGraphStore()
    stats = ingest_seed_data(graph, SEED_DIR)
    from scinikel.config import GRAPH_PATH

    graph.save(GRAPH_PATH)
    _, _, agent = _bootstrap()
    return {"status": "ok", "ingested": stats, "graph": graph.stats()}
