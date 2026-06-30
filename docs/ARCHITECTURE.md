# Архитектура решения — «Научный клубок»

> Документ для защиты и команды: слои системы, потоки данных, поиск.  
> Связано: [PLAN.md](../PLAN.md) · [KB_BACKOFFICE.md](./KB_BACKOFFICE.md) · [SEARCH_ROADMAP.md](./SEARCH_ROADMAP.md) · [USABILITY.md](./USABILITY.md)

**Обновлено:** 2026-06-30

---

## 1. Назначение

«Научный клубок» — диалоговый ассистент исследователя Норникеля поверх **графа знаний** и **корпуса документов**.  
LLM не хранит факты: извлекает их из графа, чанков PDF и CLIP-индекса рисунков, формирует ответ с **citations**.

**Важно:** нарезка текста на чанки и индексация e5 → Qdrant выполняются в **бэкофисе** (вкладка «База знаний», ingest API), а не при вопросе в чате. Подробно: [KB_BACKOFFICE.md](./KB_BACKOFFICE.md).

---

## 2. Слои системы

```mermaid
flowchart TB
  subgraph UI["Браузер (HTML + JS)"]
    Main["Главная: граф + Источники"]
    Dialog["Диалог: чат + галерея + лайтбокс"]
    Ingest["База знаний: ingest PDF/XLSX"]
    Demo["Демо / Режим работы"]
  end

  subgraph API["FastAPI"]
    Chat["POST /api/chat"]
    Search["GET /api/search/*"]
    Media["GET /api/media/images/{id}"]
    IngestAPI["POST /api/ingest/*"]
  end

  subgraph Agent["Агент"]
    RA["ResearchAgent"]
    Curator["CuratorAgent"]
    Struct["structured_answer"]
  end

  subgraph Query["Запросы"]
    HQE["HybridQueryEngine"]
    Parser["Intent parser"]
  end

  subgraph LayerA["Слой A — Граф"]
    NX["NetworkX GraphStore"]
    Onto["ontology.yaml"]
  end

  subgraph LayerB["Слой B — Текст"]
    DI["DocumentIndex"]
    BM25["BM25 in-memory"]
    E5["multilingual-e5"]
    QD["Qdrant scinikel_docs"]
  end

  subgraph LayerC["Слой C — Рисунки"]
    PDFImg["pdf_images.py"]
    CLIP["OpenCLIP ViT-B-16"]
    QI["Qdrant scinikel_images"]
    Cache["data/samples/.cache/images/"]
  end

  subgraph Storage["Хранилища"]
    SQLite["SQLite conversations.db"]
    GraphJSON["data/graph.json"]
    Seed["data/seed/"]
  end

  UI --> API
  Chat --> RA
  IngestAPI --> Curator
  RA --> HQE
  RA --> Struct
  HQE --> Parser
  HQE --> NX
  HQE --> DI
  HQE --> PDFImg
  DI --> BM25
  DI --> E5 --> QD
  PDFImg --> CLIP --> QI
  PDFImg --> Cache
  Media --> Cache
  Curator --> NX
  Chat --> SQLite
  NX --> GraphJSON
  Seed --> NX
```

### Роли слоёв

| Слой | Назначение | Источник правды | Когда используется |
|------|------------|-----------------|-------------------|
| **A. Граф** | Эксперименты, material×mode, пробелы, сравнения | `graph.json`, seed XLSX | Основной ответ в чате |
| **B. Текст** | Фрагменты PDF/отчётов, RAG | Qdrant + BM25 | Citations, `document_media` |
| **C. Рисунки** | Графики, таблицы как изображения | CLIP + кэш файлов | GIAB-демо, мультимодальный поиск |

---

## 3. Поток: вопрос пользователя → ответ

```mermaid
sequenceDiagram
  actor User as Пользователь
  participant UI as frontend/app.js
  participant API as POST /api/chat
  participant DB as SQLite
  participant Agent as ResearchAgent
  participant Engine as HybridQueryEngine
  participant Graph as NetworkX
  participant Docs as DocumentIndex
  participant CLIP as ImageIndex

  User->>UI: Вопрос (+ history)
  UI->>API: message, conversation_id
  API->>Agent: chat(message, history)

  alt scoped doc_id в вопросе
    Agent->>Engine: execute (document_media)
    Engine->>Docs: BM25/hybrid по чанкам doc
    Engine->>CLIP: search images по doc_id
  else обычный intent
    Agent->>Engine: execute (alloy / gaps / compare / …)
    Engine->>Graph: query experiments
    Engine->>Docs: _retrieve_context
    Engine->>CLIP: image hits (если релевантно)
  end

  Engine-->>Agent: QueryResult
  alt document_media
    Agent->>Agent: format_document_media_answer
  else LLM включён
    Agent->>Agent: _llm_answer + citations
  else rule mode
    Agent->>Agent: format_structured_answer
  end

  Agent-->>API: message + citations + subgraph
  API->>DB: user + assistant (meta JSON + citations)
  API-->>UI: ChatResponse
  UI->>UI: галерея, лайтбокс, renderCitations, renderGraph
```

### Ветвление ответа (ResearchAgent)

```mermaid
flowchart TD
  Start["chat(user_message)"] --> Scope{"scoped_document_id?"}
  Scope -->|да| DM["intent: document_media"]
  Scope -->|нет| Parse["parse intent + follow-up"]
  Parse --> Exec["HybridQueryEngine.execute"]
  DM --> ExecDM["_execute_document_media"]

  Exec --> Clarify{"needs_clarification?"}
  ExecDM --> FmtDM["format_document_media_answer"]

  Clarify -->|да| ClarMsg["_clarification_answer"]
  Clarify -->|нет| LLM{"should_use_llm?"}
  LLM -->|нет| Rule["format_structured_answer"]
  LLM -->|да| LLMCall["_llm_answer"]
  LLMCall --> Rule

  FmtDM --> Cit["_build_citations"]
  Rule --> Cit
  ClarMsg --> Cit
  LLMCall --> Cit
  Cit --> End["AgentResponse"]
```

---

## 4. Поток: поиск по документам (слой B)

```mermaid
flowchart LR
  Q["Запрос пользователя"] --> Mode{"search_mode"}

  Mode -->|keyword| BM25Only["BM25 по чанкам"]
  Mode -->|vector| VecOnly["e5 → Qdrant top-k"]
  Mode -->|hybrid| Both["BM25 + Vector параллельно"]

  Both --> RRF["Reciprocal Rank Fusion"]
  BM25Only --> Dedup
  VecOnly --> Dedup
  RRF --> Dedup["dedup_search_results"]

  Dedup --> Boost{"experiment_ids из графа?"}
  Boost -->|да| MetaBoost["metadata_boost"]
  Boost -->|нет| Rerank
  MetaBoost --> Rerank{"RERANK_ENABLED?"}
  Rerank -->|да| CE["CrossEncoder rerank"]
  Rerank -->|нет| Hits["SearchHit[]"]
  CE --> Hits

  Hits --> Citations["citations type=document"]
```

### Чанкинг и индексация текста

```mermaid
flowchart TB
  PDF["PDF / seed documents.json"] --> Parse["pdf_parser / loader"]
  Parse --> Chunk["chunking.py → TextChunk[]"]
  Chunk --> BM25Idx["BM25Index.add"]
  Chunk --> Embed["e5 embed passages"]
  Embed --> Upsert["Qdrant upsert scinikel_docs"]

  subgraph meta["Метаданные чанка"]
    doc_id
    chunk_id
    page_hint
    experiment_id
    excerpt_type
  end

  Chunk --> meta
```

**Режимы** (`data/llm_runtime.json`):

| `search_mode` | Активные backend'ы |
|---------------|-------------------|
| `keyword` | BM25 |
| `vector` | Qdrant + e5 |
| `hybrid` | BM25 + Qdrant + RRF |

---

## 5. Поток: мультимодальный поиск (слой C)

### Ingest PDF → индекс рисунков

```mermaid
flowchart TB
  Upload["POST /api/ingest/pdf"] --> PyMuPDF["pdf_parser: extract images"]
  PyMuPDF --> Tmp["/tmp paths"]
  Tmp --> Persist["persist_pdf_images → .cache/images/{doc_id}/"]
  Persist --> VisionGate{"analyze_images?"}

  VisionGate -->|да| Gemini["vision_analyzer Gemini"]
  Gemini --> Raw["сырой текст Vision"]
  Raw --> Librarian["CuratorAgent.librarian_annotate_vision"]
  Librarian --> Ann["librarian_annotation + key_points"]

  VisionGate -->|нет| Alt["alt из PDF metadata"]
  Ann --> CLIPIdx
  Alt --> CLIPIdx["index_pdf_images"]
  CLIPIdx --> OpenCLIP["OpenCLIP embed image"]
  OpenCLIP --> QdrantImg["Qdrant scinikel_images"]

  PyMuPDF --> Text["текст страниц"]
  Text --> Curator["CuratorAgent → experiments"]
  Curator --> Graph["graph_materializer → NetworkX"]
  Text --> ChunkIdx["DocumentIndex.index_chunks"]
```

### Запрос `document_media` (GIAB-демо)

```mermaid
flowchart TB
  Q["Вопрос про doc-giab-… / жёсткость воды"] --> Intent["intent = document_media"]
  Intent --> Ensure["ensure_doc_indexed + ensure_doc_images_indexed"]
  Ensure --> TQ["_document_media_queries"]
  Ensure --> IQ["_document_media_image_queries"]

  TQ --> Chunks["_search_document_chunks (BM25/hybrid, scope doc_id)"]
  IQ --> ImgSearch["_search_image_sources (CLIP, scope doc_id)"]

  Chunks --> RankT["rank + summarize_vision_image"]
  ImgSearch --> RankI["librarian annotations + flotation ranking"]

  RankT --> Sources["sources[]"]
  RankI --> Images["images[]"]
  Sources --> Answer["format_document_media_answer"]
  Images --> Answer
  Images --> Gallery["UI: msg-media-gallery"]
  Images --> Lightbox["UI: carousel lightbox"]
```

### Отдача рисунка в UI

```mermaid
sequenceDiagram
  participant UI as Браузер
  participant API as GET /api/media/images/{id}
  participant Resolve as resolve_image_file
  participant Cache as .cache/images/

  UI->>API: doc-giab-…-p8-i1
  API->>Resolve: normalize_image_id
  Resolve->>Cache: canonical p{N}-i1
  Cache-->>API: JPEG/PNG
  API-->>UI: FileResponse inline
  UI->>UI: лайтбокс / галерея
```

---

## 6. Поток: ingest и наполнение графа

```mermaid
flowchart LR
  subgraph sources["Источники"]
    XLSX["catalog.xlsx"]
    PDF["report.pdf"]
    Manual["Curate API"]
  end

  subgraph pipeline["Ingest pipeline"]
    XLSX --> XParser["xlsx_parser"]
    PDF --> PParser["pdf_parser + Vision"]
    Manual --> Curator
    XParser --> Curator["CuratorAgent.review_and_extract"]
    PParser --> Curator
    Curator --> Materializer["graph_materializer"]
  end

  Materializer --> Graph["NetworkX graph.json"]
  PParser --> DocIdx["DocumentIndex"]
  PParser --> ImgIdx["CLIP index"]
```

---

## 7. Поток: UI и сохранение контекста

```mermaid
flowchart TB
  subgraph tabs["Вкладки"]
    D["Диалог"]
    M["Главная"]
  end

  ChatResp["ChatResponse"] --> D
  ChatResp --> M

  ChatResp --> Msg["appendMessage + галерея"]
  ChatResp --> CitPanel["renderCitations"]
  ChatResp --> Subgraph["renderGraph vis.js"]
  ChatResp --> SQLite["meta JSON: citations + exp_id"]

  SQLite --> Reload["loadConversation"]
  Reload --> Msg
  Reload --> CitPanel
  Reload --> SubgraphLocal["localStorage subgraph fallback"]

  D --> Hint["подсказка → Главная"]
  D --> LB["лайтбокс ← → карусель"]
  M --> LB
```

---

## 8. Компоненты и файлы

| Компонент | Путь |
|-----------|------|
| API, lifespan, media | `src/scinikel/api/app.py` |
| Диалоговый агент | `src/scinikel/agent/assistant.py` |
| Формат ответов PDF/таблиц | `src/scinikel/agent/structured_answer.py` |
| Куратор + librarian Vision | `src/scinikel/agent/curator.py` |
| Intent + graph + document_media | `src/scinikel/query/engine.py` |
| Индекс текста | `src/scinikel/search/index.py` |
| BM25, chunking, RRF | `search/bm25.py`, `chunking.py`, `fusion.py` |
| CLIP + кэш рисунков | `search/pdf_images.py`, `image_embeddings.py` |
| Qdrant | `search/vector_db.py` |
| Режимы lite/local/full | `services/llm_runtime.py` |
| Диалоги SQLite | `storage/conversations.py` |
| UI | `frontend/static/app.js`, `index.html` |

---

## 9. Внешние зависимости

```mermaid
flowchart LR
  App["scinikel API"] --> Qdrant["Qdrant :6333"]
  App --> LLM["OpenAI / ProxyAPI / Ollama"]
  App --> Gemini["Gemini Vision"]
  App --> Torch["torch + sentence-transformers + open-clip"]

  Qdrant --> Collections["scinikel_docs · scinikel_images"]
```

| Сервис | Назначение | Обязательность |
|--------|------------|----------------|
| Qdrant | Векторный поиск текста и рисунков | full / multimodal |
| LLM | Ответы и Curator ingest | local / full |
| Gemini | Vision при PDF ingest | multimodal |
| torch + e5 + CLIP | Эмбеддинги | hybrid + images |

---

## 10. Масштабирование (после хакатона)

| Сейчас | Целевое |
|--------|---------|
| NetworkX in-memory | Neo4j + Cypher |
| SQLite диалоги | PostgreSQL / shared store |
| Один процесс API | workers + очередь ingest |
| Локальный Qdrant | репликация, ACL |

---

## 11. Связанные документы

- [KB_BACKOFFICE.md](./KB_BACKOFFICE.md) — бэкофис: ingest, чанки, e5
- [PLAN.md](../PLAN.md) — статус и приоритеты
- [SEARCH_ROADMAP.md](./SEARCH_ROADMAP.md) — этапы 0–6 поиска
- [MULTIMODAL_STATUS.md](./MULTIMODAL_STATUS.md) — GIAB, CLIP, Vision
- [USABILITY.md](./USABILITY.md) — UX и приёмка
- [3DTODAY_PORTING.md](./3DTODAY_PORTING.md) — заимствования из 3dtoday
