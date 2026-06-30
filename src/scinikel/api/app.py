"""FastAPI application."""

import asyncio
import json
import logging
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from scinikel.agent.assistant import ChatMessage, ResearchAgent
from scinikel.agent.curator import CuratorAgent
from scinikel.config import GRAPH_PATH, ROOT, SEED_DIR, settings
from scinikel.graph import get_graph_store
from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.graph_materializer import doc_id_from_title
from scinikel.ingest.loader import ingest_seed_data, load_experiments_xlsx
from scinikel.ingest.pdf_parser import parse_pdf
from scinikel.models.entities import Document, EntityType
from scinikel.query.engine import HybridQueryEngine
from scinikel.search.index import DocumentIndex
from scinikel.services.llm_runtime import (
    apply_work_mode,
    list_ollama_models,
    probe_ollama,
    probe_proxyapi,
    runtime_payload,
    set_runtime_config,
    vector_search_enabled,
)
from scinikel.services.vision_analyzer import vision_status
from scinikel.storage.conversations import (
    add_message,
    conversation_payload,
    create_conversation,
    delete_conversation,
    encode_assistant_meta,
    get_messages,
    init_db,
    list_conversations,
)

_agent: ResearchAgent | None = None
_graph: NetworkXGraphStore | None = None
_doc_index: DocumentIndex | None = None

logger = logging.getLogger(__name__)


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


def _index_sample_pdfs(doc_index: DocumentIndex) -> int:
    """Быстрый старт: только BM25-текст. CLIP/Vision — в фоне (как ingest в 3dtoday)."""
    from scinikel.ingest.pdf_parser import parse_pdf
    from scinikel.search.pdf_images import persist_pdf_images
    from scinikel.search.sample_docs import SAMPLE_DOC_META, SAMPLE_DOC_PDFS

    indexed = 0
    for doc_id, path in SAMPLE_DOC_PDFS.items():
        if not path.exists():
            continue
        if doc_index.has_doc_chunks(doc_id):
            continue
        if doc_index.rehydrate_doc_from_qdrant(doc_id) > 0:
            indexed += 1
            continue
        try:
            parsed = parse_pdf(path, max_pages=50)
            meta = dict(SAMPLE_DOC_META.get(doc_id) or {})
            meta.setdefault("title", path.stem)
            meta.setdefault("doc_type", "report")
            if doc_index.index_text(doc_id, parsed["content"], meta):
                indexed += 1
                logger.info(
                    "Indexed sample PDF %s (%s chunks)",
                    doc_id,
                    doc_index.doc_chunk_count(doc_id),
                )
            persist_pdf_images(doc_id, parsed.get("images") or [])
        except Exception as exc:
            logger.warning("Sample PDF %s skip: %s", path.name, exc)
    return indexed


def _background_index_sample_images() -> None:
    """Vision + аннотации куратора + CLIP после старта API."""
    from scinikel.search.sample_docs import SAMPLE_DOC_PDFS

    idx = _doc_index
    if idx is None:
        return
    for doc_id in SAMPLE_DOC_PDFS:
        try:
            n = idx.ensure_doc_images_indexed(doc_id, analyze_images=True)
            if n:
                logger.info("Background librarian+CLIP: %s images for %s", n, doc_id)
        except Exception as exc:
            logger.warning("Background image index %s: %s", doc_id, exc)


def _create_doc_index() -> DocumentIndex:
    return DocumentIndex(enable_vector=vector_search_enabled())


def _rebuild_doc_index() -> DocumentIndex:
    global _doc_index, _agent
    doc_index = _create_doc_index()
    _index_seed_documents(doc_index)
    _index_sample_pdfs(doc_index)
    _doc_index = doc_index
    if _graph is not None:
        query_engine = HybridQueryEngine(_graph, doc_index)
        _agent = ResearchAgent(query_engine)
    return doc_index


def _bootstrap() -> tuple[NetworkXGraphStore, DocumentIndex, ResearchAgent]:
    global _graph, _agent, _doc_index
    graph = get_graph_store()
    if isinstance(graph, NetworkXGraphStore) and graph.stats()["entities"] == 0:
        ingest_seed_data(graph, SEED_DIR)
        graph.save(GRAPH_PATH)

    doc_index = _create_doc_index()
    _index_seed_documents(doc_index)
    _index_sample_pdfs(doc_index)

    query_engine = HybridQueryEngine(graph, doc_index)
    _graph = graph
    _doc_index = doc_index
    _agent = ResearchAgent(query_engine)
    return graph, doc_index, _agent


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    _bootstrap()
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _background_index_sample_images)
    yield


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)

static_dir = ROOT / "frontend" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class ChatMessageItem(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatMessageItem] = Field(default_factory=list)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    message: str
    citations: list[dict[str, Any]]
    experiments: list[dict[str, Any]]
    subgraph: dict[str, Any] | None = None
    gaps: list[dict[str, str]] = Field(default_factory=list)
    llm_used: bool = False
    turn: int = 0
    needs_clarification: bool = False
    clarification_options: list[dict[str, str]] = Field(default_factory=list)
    conversation_id: str | None = None


class ConversationCreate(BaseModel):
    title: str = "Новый диалог"


class CurateRequest(BaseModel):
    title: str
    content: str
    source: str | None = None
    doc_type: str = "report"
    ingest: bool = True


class LLMConfigRequest(BaseModel):
    work_mode: str | None = Field(default=None, pattern="^(lite|local|full|custom)$")
    provider: str | None = Field(default=None, pattern="^(proxyapi|ollama)$")
    openai_model: str | None = None
    ollama_model: str | None = None
    answer_mode: str | None = Field(default=None, pattern="^(llm|rule)$")
    search_mode: str | None = Field(default=None, pattern="^(keyword|vector|hybrid)$")


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

    conv_id = req.conversation_id
    if conv_id and conversation_payload(conv_id) is None:
        raise HTTPException(404, "Conversation not found")
    if not conv_id:
        conv_id = create_conversation().id

    history = [ChatMessage(role=m.role, content=m.content) for m in req.history]
    resp = _agent.chat(req.message, history=history)
    qr = resp.query_result
    turn = len(history) // 2 + 1

    meta = "llm" if resp.llm_used else "graph"
    exp_id: str | None = None
    if qr and qr.experiments:
        exp_id = qr.experiments[0]["experiment"]["id"]
    assistant_meta = encode_assistant_meta(
        llm_used=resp.llm_used,
        experiment_id=exp_id,
        citations=resp.citations,
    )
    add_message(conv_id, "user", req.message, title_hint=req.message)
    add_message(conv_id, "assistant", resp.message, meta=assistant_meta)

    return ChatResponse(
        message=resp.message,
        citations=resp.citations,
        experiments=qr.experiments if qr else [],
        subgraph=qr.subgraph if qr else None,
        gaps=qr.gaps if qr else [],
        llm_used=resp.llm_used,
        turn=turn,
        needs_clarification=qr.needs_clarification if qr else False,
        clarification_options=qr.clarification_options if qr else [],
        conversation_id=conv_id,
    )


@app.get("/api/conversations")
async def conversations_list(limit: int = 50):
    return [
        {"id": c.id, "title": c.title, "created_at": c.created_at, "updated_at": c.updated_at}
        for c in list_conversations(limit=limit)
    ]


@app.post("/api/conversations")
async def conversations_create(req: ConversationCreate):
    conv = create_conversation(req.title)
    return {"id": conv.id, "title": conv.title, "created_at": conv.created_at, "updated_at": conv.updated_at}


@app.get("/api/conversations/{conv_id}")
async def conversations_get(conv_id: str):
    payload = conversation_payload(conv_id)
    if not payload:
        raise HTTPException(404, "Conversation not found")
    return payload


@app.delete("/api/conversations/{conv_id}")
async def conversations_delete(conv_id: str):
    if not delete_conversation(conv_id):
        raise HTTPException(404, "Conversation not found")
    return {"status": "ok"}


@app.get("/api/assistant/status")
async def assistant_status():
    idx = _doc_index or _create_doc_index()
    llm = runtime_payload()
    preset = next((m for m in llm["work_modes"] if m["id"] == llm["work_mode"]), None)
    return {
        "llm_enabled": llm["llm_enabled"],
        "answer_mode": llm["answer_mode"],
        "llm_provider": llm["provider"],
        "llm_model": llm["active_label"],
        "search_backend": idx.backend,
        "search_mode": llm["search_mode"],
        "work_mode": llm["work_mode"],
        "work_mode_name": preset["name"] if preset else llm["work_mode"],
        "resources": llm.get("resources", {}),
        "graph_entities": _graph.stats()["entities"] if _graph else 0,
    }


@app.get("/api/llm/config")
async def llm_config_get():
    payload = runtime_payload()
    payload["ollama_models"] = list_ollama_models()
    return payload


@app.post("/api/llm/config")
async def llm_config_set(req: LLMConfigRequest):
    prev_search = runtime_payload()["search_mode"]
    try:
        if req.work_mode and req.work_mode in ("lite", "local", "full"):
            payload = apply_work_mode(req.work_mode)
            if req.openai_model or req.ollama_model or req.provider:
                payload = set_runtime_config(
                    provider=req.provider,
                    openai_model=req.openai_model,
                    ollama_model=req.ollama_model,
                )
        else:
            cfg = runtime_payload()
            payload = set_runtime_config(
                provider=req.provider or cfg["provider"],
                openai_model=req.openai_model,
                ollama_model=req.ollama_model,
                answer_mode=req.answer_mode,
                search_mode=req.search_mode,
                work_mode=req.work_mode if req.work_mode != "custom" else None,
            )
        if payload["search_mode"] != prev_search:
            idx = _rebuild_doc_index()
            payload = runtime_payload()
            payload["search_backend"] = idx.backend
        else:
            idx = _doc_index or _create_doc_index()
            payload["search_backend"] = idx.backend
        return payload
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/llm/probe")
async def llm_probe(provider: str | None = None):
    cfg = runtime_payload()
    target = provider or cfg["provider"]
    if target == "ollama":
        return {"provider": "ollama", **probe_ollama()}
    return {"provider": "proxyapi", **probe_proxyapi()}


@app.get("/api/vision/status")
async def api_vision_status():
    return vision_status()


@app.get("/api/search/images")
async def search_images(q: str, limit: int = 5, doc_id: str | None = None):
    idx = _doc_index or _create_doc_index()
    hits = idx.search_images(q, limit=limit, doc_id=doc_id)
    return {
        "query": q,
        "backend": "openclip+qdrant" if hits else "unavailable",
        "results": [
            {"id": h.id, "score": h.score, "text": h.text, "metadata": h.metadata}
            for h in hits
        ],
    }


@app.get("/api/media/images/{image_id:path}")
async def get_media_image(image_id: str):
    """Отдать рисунок из кэша (inline в браузере, не скачивание в «Документы»)."""
    from scinikel.search.pdf_images import resolve_image_file, strip_image_extension

    clean_id = strip_image_extension(image_id.split("/")[-1])
    path = resolve_image_file(clean_id)
    if path is None or not path.is_file():
        logger.warning("Image not found: %s (from %s)", clean_id, image_id)
        raise HTTPException(404, f"Image not found: {clean_id}")
    suffix = path.suffix.lower()
    media = "image/png" if suffix == ".png" else "image/jpeg"
    return FileResponse(
        path,
        media_type=media,
        filename=path.name,
        content_disposition_type="inline",
    )


@app.get("/api/search/chunks")
async def search_chunks(q: str, limit: int = 5):
    """Прямой поиск по чанкам — для проверки релевантности (этап 1)."""
    idx = _doc_index or _create_doc_index()
    hits = idx.search(q, limit=limit)
    return {
        "query": q,
        "backend": idx.backend,
        "chunk_count": idx.chunk_count,
        "results": [
            {
                "chunk_id": h.metadata.get("chunk_id") or h.id,
                "doc_id": h.metadata.get("doc_id"),
                "title": h.metadata.get("title"),
                "page": h.metadata.get("page"),
                "score": h.score,
                "text": h.text[:500],
                "experiment_ids": h.metadata.get("experiment_ids") or [],
                "fusion_sources": h.metadata.get("fusion_sources") or [],
            }
            for h in hits
        ],
    }


@app.get("/api/search/status")
async def search_status():
    from scinikel.search.image_embeddings import clip_status
    from scinikel.search.sample_docs import SAMPLE_DOC_IMAGE_EXPECTED

    idx = _doc_index or _create_doc_index()
    llm = runtime_payload()
    giab = "doc-giab-ni-cu-flotation-water"
    giab_images = idx.doc_image_count(giab)
    giab_expected = SAMPLE_DOC_IMAGE_EXPECTED.get(giab, 0)
    clip = clip_status()
    images_indexing = bool(
        clip.get("available")
        and giab_expected > 0
        and giab_images < giab_expected
    )
    return {
        "backend": idx.backend,
        "backends_active": idx.backends_active(),
        "chunk_count": idx.chunk_count,
        "giab_chunk_count": idx.doc_chunk_count(giab),
        "giab_image_count": giab_images,
        "giab_images_expected": giab_expected,
        "images_indexing": images_indexing,
        "clip": clip,
        "search_mode": llm["search_mode"],
        "vector_search_enabled": llm["vector_search_enabled"],
        "hybrid_search_enabled": llm.get("hybrid_search_enabled", False),
        "qdrant_collection": settings.qdrant_collection,
    }


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
        doc_id = doc_id_from_title(req.title)
        if result.get("extraction", {}).get("document"):
            result["extraction"]["document"]["id"] = doc_id
        _doc_index.index_text(doc_id, req.content, {"title": req.title, "doc_type": req.doc_type})

    if isinstance(_graph, NetworkXGraphStore):
        _graph.save(GRAPH_PATH)
    return result


@app.post("/api/ingest/pdf")
async def ingest_pdf(
    file: UploadFile = File(...),
    max_pages: int = 20,
    ingest: bool = True,
    analyze_images: bool = True,
    index_images: bool = True,
):
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

    upload_title = Path(file.filename or "doc.pdf").stem
    if upload_title and not upload_title.startswith("tmp"):
        parsed["title"] = upload_title

    images = parsed.get("images") or []
    curator = CuratorAgent(_graph)
    if ingest:
        result = await curator.review_and_ingest(
            parsed["title"],
            parsed["content"],
            source=parsed.get("source"),
            doc_type="report",
            images=images,
            analyze_images=analyze_images,
        )
    else:
        extraction = await curator.review_and_extract(
            parsed["title"],
            parsed["content"],
            source=parsed.get("source"),
            images=images,
            analyze_images=analyze_images,
        )
        result = {"extraction": extraction}

    extraction = result.get("extraction") or {}
    enriched = curator._merge_image_context(parsed["content"], extraction.get("image_analysis"))
    doc_id = doc_id_from_title(parsed["title"])
    if extraction.get("document"):
        extraction["document"]["id"] = doc_id

    images_indexed = 0
    if _doc_index:
        _doc_index.index_text(doc_id, enriched, {"title": parsed["title"], "doc_type": "report"})
        if index_images:
            analyses = (extraction.get("image_analysis") or {}).get("image_analyses")
            images_indexed = _index_pdf_images(
                _doc_index,
                doc_id,
                images,
                parsed["title"],
                analyze_images=analyze_images,
                image_analyses=analyses,
            )

    result["parsed"] = {
        "title": parsed["title"],
        "pages_parsed": parsed.get("pages_parsed"),
        "images_count": len(images),
        "images_indexed": images_indexed,
        "analyze_images": analyze_images,
        "vision_provider": (extraction.get("image_analysis") or {}).get("provider"),
        "vision_images_used": (extraction.get("image_analysis") or {}).get("relevant_images_count", 0),
    }

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
    """Deprecated alias — используйте doc_id_from_title."""
    return doc_id_from_title(title)


def _index_pdf_images(
    doc_index: DocumentIndex,
    doc_id: str,
    images: list[dict[str, Any]],
    title: str,
    *,
    analyze_images: bool = True,
    image_analyses: list[dict[str, Any]] | None = None,
) -> int:
    from scinikel.search.pdf_images import index_pdf_images

    return index_pdf_images(
        doc_index,
        doc_id,
        images,
        title,
        analyze_images=analyze_images,
        image_analyses=image_analyses,
    )
