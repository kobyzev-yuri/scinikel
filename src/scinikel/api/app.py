"""FastAPI application."""

import json
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from scinikel.agent.assistant import ResearchAgent
from scinikel.agent.curator import CuratorAgent
from scinikel.config import GRAPH_PATH, ROOT, SEED_DIR, settings
from scinikel.graph import get_graph_store
from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.loader import ingest_seed_data, load_experiments_xlsx
from scinikel.ingest.pdf_parser import parse_pdf
from scinikel.models.entities import Document, EntityType
from scinikel.query.engine import HybridQueryEngine
from scinikel.search.index import DocumentIndex

_agent: ResearchAgent | None = None
_graph: NetworkXGraphStore | None = None
_doc_index: DocumentIndex | None = None


def _index_seed_documents(doc_index: DocumentIndex) -> int:
    doc_path = SEED_DIR / "documents.json"
    if not doc_path.exists():
        return 0
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
    return doc_index.index_documents(docs, texts)


def _bootstrap() -> tuple[NetworkXGraphStore, DocumentIndex, ResearchAgent]:
    global _graph, _agent, _doc_index
    graph = get_graph_store()
    if isinstance(graph, NetworkXGraphStore) and graph.stats()["entities"] == 0:
        ingest_seed_data(graph, SEED_DIR)
        graph.save(GRAPH_PATH)

    doc_index = DocumentIndex()
    _index_seed_documents(doc_index)

    query_engine = HybridQueryEngine(graph, doc_index)
    _graph = graph
    _doc_index = doc_index
    _agent = ResearchAgent(query_engine)
    return graph, doc_index, _agent


@asynccontextmanager
async def lifespan(_: FastAPI):
    _bootstrap()
    yield


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)

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


class CurateRequest(BaseModel):
    title: str
    content: str
    source: str | None = None
    doc_type: str = "report"
    ingest: bool = True


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


@app.get("/api/search/status")
async def search_status():
    idx = _doc_index or DocumentIndex()
    return {"backend": idx.backend, "qdrant_collection": settings.qdrant_collection}


@app.post("/api/ingest/curate")
async def ingest_curate(req: CurateRequest):
    if _graph is None:
        raise HTTPException(503, "Graph not ready")
    curator = CuratorAgent(_graph)
    if req.ingest:
        result = await curator.review_and_ingest(
            req.title, req.content, source=req.source, doc_type=req.doc_type
        )
    else:
        extraction = await curator.review_and_extract(
            req.title, req.content, source=req.source, doc_type=req.doc_type
        )
        result = {"extraction": extraction}

    if _doc_index and req.content:
        doc_id = result.get("extraction", {}).get("document", {}).get("id") or slugify_doc(req.title)
        _doc_index.index_text(doc_id, req.content, {"title": req.title, "doc_type": req.doc_type})

    if isinstance(_graph, NetworkXGraphStore):
        _graph.save(GRAPH_PATH)
    return result


@app.post("/api/ingest/pdf")
async def ingest_pdf(file: UploadFile = File(...), max_pages: int = 20, ingest: bool = True):
    if _graph is None:
        raise HTTPException(503, "Graph not ready")

    suffix = Path(file.filename or "doc.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    parsed = parse_pdf(tmp_path, max_pages=max_pages)
    Path(tmp_path).unlink(missing_ok=True)
    if not parsed:
        raise HTTPException(400, "Failed to parse PDF")

    curator = CuratorAgent(_graph)
    if ingest:
        result = await curator.review_and_ingest(
            parsed["title"],
            parsed["content"],
            source=parsed.get("source"),
            doc_type="report",
        )
    else:
        extraction = await curator.review_and_extract(
            parsed["title"], parsed["content"], source=parsed.get("source")
        )
        result = {"extraction": extraction}

    result["parsed"] = {
        "title": parsed["title"],
        "pages_parsed": parsed.get("pages_parsed"),
        "images_count": len(parsed.get("images", [])),
    }

    if _doc_index:
        doc_id = result.get("extraction", {}).get("document", {}).get("id") or slugify_doc(parsed["title"])
        _doc_index.index_text(doc_id, parsed["content"], {"title": parsed["title"], "doc_type": "report"})

    if isinstance(_graph, NetworkXGraphStore):
        _graph.save(GRAPH_PATH)
    return result


@app.post("/api/ingest/xlsx")
async def ingest_xlsx(file: UploadFile = File(...)):
    if _graph is None:
        raise HTTPException(503, "Graph not ready")

    suffix = Path(file.filename or "data.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        count = load_experiments_xlsx(_graph, Path(tmp_path))
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if isinstance(_graph, NetworkXGraphStore):
        _graph.save(GRAPH_PATH)
    return {"status": "ok", "experiments_loaded": count, "graph": _graph.stats()}


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
    global _graph, _agent, _doc_index
    graph = NetworkXGraphStore()
    stats = ingest_seed_data(graph, SEED_DIR)
    graph.save(GRAPH_PATH)
    _, doc_index, agent = _bootstrap()
    return {"status": "ok", "ingested": stats, "graph": graph.stats(), "search_backend": doc_index.backend}


def slugify_doc(title: str) -> str:
    import re

    base = re.sub(r"[^\w\s-]", "", title.lower())
    return "doc-" + re.sub(r"[\s_]+", "-", base.strip())[:48]
