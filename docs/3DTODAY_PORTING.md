# Перенос паттернов из 3dtoday (3Dprinter KB)

> Источник: `/media/cnn/home/cnn/3dtoday` (репозиторий [kobyzev-yuri/3dtoday](https://github.com/kobyzev-yuri/3dtoday))  
> Целевой проект: **scinikel** (`/home/cnn/scinikel`)

Документ фиксирует, **что уже перенесено**, **что брать следующим** и **чего в 3dtoday нет** (BM25, RRF, chunking).

---

## Важно: два смысла слова «hybrid»

| Проект | «Hybrid search» означает |
|--------|-------------------------|
| **3dtoday** | Вектор Qdrant + **фильтры/boost по metadata** (`problem_type`, `printer_models`) |
| **scinikel roadmap** | **BM25 + dense** fusion (RRF) + graph boost |

В 3dtoday **нет** BM25 и RRF. Семантический «гибрид» 3dtoday ≈ **этап 4** roadmap scinikel (metadata boost), не этап 3.

---

## Мультимодальность в 3dtoday (CLIP + Gemini / llava)

В 3dtoday реализованы **два дополняющих контура**, не один:

```
                    PDF / URL / загрузка фото
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
     Vision LLM (ingest / query)        OpenCLIP (index / search)
     Gemini 3.x / Ollama llava          ViT-B-16 → Qdrant 512d
              │                               │
              ▼                               ▼
     Текстовое описание картинки      Вектор в kb_*_images
     + relevance check                 Поиск: текст→картинки
              │                               │
              └───────────────┬───────────────┘
                              ▼
              RetrievalAgent: vision_context → e5 search → rerank
```

### Умный библиотекарь (`KBLibrarianAgent`) + Gemini Vision

Это **отдельный и главный ingest-контур** — не только поиск.

| Шаг | Модуль | Что делает |
|-----|--------|------------|
| 1 | `document_parser` / PDF | Текст + список `images[]` (base64, path, alt) |
| 2 | `kb_librarian.review_and_decide()` | Текст → LLM (GPT/Gemini/Ollama) |
| 3 | `kb_librarian._analyze_images()` | До **10 картинок** → **Gemini Vision** (`vision_analyzer.py`) |
| 4 | Промпт Gemini | «Извлеки весь видимый текст, **таблицы**, графики, схемы» |
| 5 | `check_relevance_to_3d_printing()` | Фильтр релевантных картинок |
| 6 | `_create_summary()` | **Сливает** текстовый анализ + описания картинок в abstract |
| 7 | `_check_duplicates` → Qdrant | Решение approve/reject + индекс |

**Зачем Vision на ingest:** в PDF таблицы часто **не попадают в PyPDF2-текст** — они отрисованы как растр. Gemini «читает» картинку страницы/таблицы и возвращает структурированное описание на русском.

Промпт в `vision_analyzer._analyze_with_gemini`:

```
2. Извлеки весь видимый текст (сохрани форматирование)
4. Выдели ключевые разделы, заголовки, таблицы
5. Опиши схемы, диаграммы, графики если есть
```

**Для scinikel (металлургия):** те же картинки из `pdf_parser` — это часто **таблицы результатов** (EXP, Ni%, T°C, pH), графики извлечения, схемы установок. Без Vision куратор видит только обрывки текста.

**Текущий разрыв в scinikel:**

```
pdf_parser → images[] (есть)  →  curator.review_and_extract(content только)  →  LLM без картинок
                                      ↑ images_count в API, но не передаются
```

Целевой пайплайн (этап 6b):

```
pdf_parser → images[]
     → VisionAnalyzer (Gemini) → image_analyses[] (таблицы как markdown/JSON)
     → дописать в content или отдельное поле visual_context
     → CuratorAgent._llm_extract() → experiments[] в граф
```

---

### Контур A — Vision LLM при запросе (диагностика)

| Модуль 3dtoday | Назначение |
|----------------|------------|
| `services/vision_analyzer.py` | Анализ байтов/файла изображения |
| Провайдеры | **Gemini** (`gemini-3-pro-preview` через ProxyAPI) или **Ollama `llava`** |
| `kb_librarian._analyze_images()` | При ingest: до 10 картинок → описание + `check_relevance` |
| `RetrievalAgent.search_with_image()` | При запросе: фото дефекта → `vision_context` → улучшенный текстовый поиск |
| `POST /api/diagnose/image` | UI: загрузка фото + query + rerank |

**Конфиг 3dtoday** (`config.env.example`):

```bash
GEMINI_API_KEY=...
GEMINI_BASE_URL=https://api.proxyapi.ru/google
GEMINI_MODEL=gemini-3.5-flash
OLLAMA_VISION_MODEL=llava
VISION_PRIMARY_MODEL=ollama_llava
VISION_FALLBACK_MODEL=gemini_proxyapi
```

**Смысл для scinikel:** микрофото шлака, графики XRD, схемы печи — Gemini/llava **описывает** картинку текстом → попадает в Curator / улучшает запрос. Не заменяет граф экспериментов.

### Контур B — OpenCLIP (векторный multimodal search)

| Модуль 3dtoday | Назначение |
|----------------|------------|
| `services/openclip_embeddings.py` | `encode_image()`, `encode_text()` в **общем** 512d пространстве |
| `article_indexer.index_image()` | CLIP-вектор → Qdrant коллекция **изображений** |
| `vector_db.py` | `kb_3dtoday` (768d e5) + `kb_3dtoday_images` (512d CLIP) |
| `rag_service.search(is_image=True)` | Семантический поиск по коллекции картинок |

```bash
OPENCLIP_MODEL=ViT-B-16
OPENCLIP_PRETRAINED=openai
IMAGE_EMBEDDING_DIMENSION=512
QDRANT_IMAGE_COLLECTION=kb_3dtoday_images
```

**Смысл для scinikel:** запрос «график зависимости извлечения Ni от температуры» может найти **рисунок** из PDF без полного описания LLM.

### Как это связано при поиске (3dtoday)

1. Пользователь загружает **фото** + текст.
2. **VisionAnalyzer** → `vision_context` (symptoms, description).
3. Запрос **обогащается** (`_enhance_query_with_vision_context`).
4. **e5 + Qdrant** (текст) + опционально **CLIP** (картинки).
5. **CrossEncoder rerank** → top-k.

Документация: `3dtoday/docs/IMAGE_DIAGNOSTIC_FEATURE.md`.

### Перенос в scinikel (этап 6 — два подэтапа)

| Подэтап | Источник 3dtoday | Цель в scinikel | Статус |
|---------|------------------|-----------------|--------|
| **6a CLIP** | `openclip_embeddings.py`, `index_image`, image Qdrant | Индекс фигур из `pdf_parser` images | ✅ |
| **6b Vision** | `vision_analyzer.py`, `kb_librarian._analyze_images` | Описание графиков при ingest PDF | ✅ `gemini-3.5-flash` |
| **6c API/UI** | `/api/diagnose/image`, user_ui upload | `GET /api/search/images`, чекбоксы ingest | 🟡 |

**Домен scinikel вместо 3D-печати:**

| 3dtoday | scinikel |
|---------|----------|
| `problem_type` (stringing, warping) | `process_hint` (флотация, обжиг) |
| `printer_models` | `equipment` (EL-3, FML-8) |
| `materials` (PLA, PETG) | `material` (Ni-Cu сплав, концентрат) |
| relevance «3D printing» | relevance «металлургия / R&D» |

---

## Карта модулей

| 3dtoday | scinikel | Статус |
|---------|----------|--------|
| `services/rag_service.py` | `search/embeddings.py`, `search/index.py` | ✅ e5, поиск |
| `services/vector_db.py` | `search/vector_db.py` | ✅ 🟡 фильтры payload добавлены |
| `services/rag_service.search` dedup | `search/dedup.py` | ✅ |
| `rag_service.hybrid_search` boost | `search/metadata_boost.py` | ✅ (experiment_id, doc_type) |
| `agents/retrieval_agent.py` rerank | `search/rerank.py` | ✅ опционально `RERANK_ENABLED=true` |
| `services/openclip_embeddings.py` | `search/image_embeddings.py` | ✅ этап 6a |
| `services/vision_analyzer.py` (Gemini/llava) | `services/vision_analyzer.py` | ✅ этап 6b |
| `kb_librarian._analyze_images` + `_create_summary` | `agent/curator.py` | ✅ этап 6b |
| `retrieval_agent.search_with_image` | — | ⬜ этап 6c |
| `services/article_indexer.py` | `search/index.py` ingest | ✅ text + image |
| `agents/kb_librarian.py` | `agent/curator.py` | 🟡 без vector dedup |
| `services/document_parser.py` | `ingest/pdf_parser.py` | 🟡 PDF only |
| `agents/retrieval_agent.py` vision | `GET /api/search/images` | 🟡 этап 6c |
| BM25 / chunking | `search/bm25.py`, `search/chunking.py` | ✅ этап 1 (нет в 3dtoday — свой код) |

---

## Уже перенесено в код (2026-06-29)

### 1. Дедупликация (`search/dedup.py`)

Из `rag_service.search`: убрать дубли по `doc_id` / `url` перед выдачей.

### 2. Metadata boost (`search/metadata_boost.py`)

Из `hybrid_search`: +0.1 за `doc_type`, +0.15 если `experiment_id` совпал с фильтром из графа.

### 3. Rerank (`search/rerank.py`)

Из `RetrievalAgent._rerank_results`:

- модель: `cross-encoder/ms-marco-MiniLM-L-12-v2` (`RERANKER_MODEL`)
- blend: `0.4 * vector_score + 0.6 * rerank_score`
- включается: `RERANK_ENABLED=true` в `config.env`

### 4. Qdrant filters (`search/vector_db.py`)

Паттерн `vector_db.search(filters=...)`: `doc_type`, `doc_ids`, `experiment_ids`.

### 5. Graph → doc pipeline (`query/engine.py`)

После поиска экспериментов в графе — `experiment_ids` передаются в `DocumentIndex.search(filters=...)` (аналог boost по printer/material в 3dtoday).

---

## Следующие переносы (по приоритету)

### A. Curator: vector duplicate check

**Откуда:** `kb_librarian.py` → `_check_duplicates()`  
**Куда:** `agent/curator.py` перед ingest  
**Смысл:** top-5 vector search + LLM «это дубликат?»

### B. OpenCLIP + image collection (этап 6a)

**Откуда:** `openclip_embeddings.py`, `article_indexer.index_image()`, dual `vector_db`  
**Куда:** `search/image_embeddings.py`, `scinikel_images` (512d)  
**Смысл:** векторный поиск графиков/схем из PDF

### B2. Vision LLM + умный библиотекарь (этап 6b)

**Откуда:** `vision_analyzer.py`, `kb_librarian._analyze_images()`, `_create_summary()`  
**Куда:** `services/vision_analyzer.py`, расширение `curator.review_and_extract(images=...)`  
**Смысл:**
- Gemini описывает **как понял** каждую картинку (OCR + интерпретация)
- Особенно важно для **таблиц в PDF** — PyPDF2 их не видит, PyMuPDF даёт растр
- Описания сливаются в контент **до** извлечения `experiments[]` в граф

**Адаптация промпта под металлургию** (вместо 3D-печати):

```
Тип: таблица результатов | график | схема установки | микрофото
Извлеки: EXP-ID, материал, режим, Ni/Cu %, T, pH, вывод
Таблицы: markdown-таблица или JSON rows
```

**Fallback:** если Gemini недоступен — `llava` или эвристика по `alt` (как `_analyze_images_fallback` в 3dtoday).

### B3. Поиск с картинкой (этап 6c)

**Откуда:** `RetrievalAgent.search_with_image`, `POST /api/diagnose/image`  
**Куда:** `POST /api/search/image` или расширение `/api/chat` с attachment  
**Смысл:** фото + вопрос → vision_context → e5/CLIP → rerank

### C. Retrieve pipeline как в RetrievalAgent

**Откуда:** `retrieval_agent.search`: `retrieve_k=20` → dedup → rerank → `limit=5`  
**Куда:** уже в `DocumentIndex.search`; донастроить `retrieve_k` / пороги из `config.env`

### D. Rich PDF / HTML parser

**Откуда:** `document_parser.py` (Trafilatura, Readability)  
**Куда:** `ingest/` — если появятся URL/HTML от организаторов

---

## Что делать новому в scinikel (нет готового в 3dtoday)

| Задача | Действие |
|--------|----------|
| BM25 | `rank_bm25` или Qdrant sparse — **писать в scinikel** |
| Чанкинг | `search/chunking.py` — **писать в scinikel** (в 3dtoday только env, код пустой) |
| RRF fusion | `search/fusion.py` — **писать в scinikel** |
| Graph material×mode | Уже есть — **уникальность scinikel**, не из 3dtoday |

---

## Конфигурация (scinikel)

```bash
# config.env — поиск (как в 3dtoday)
HF_MODEL_NAME=intfloat/multilingual-e5-base
EMBEDDING_DIMENSION=768
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=scinikel_docs

# rerank (из 3dtoday RetrievalAgent)
RERANK_ENABLED=false
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-12-v2

# multimodal — CLIP (этап 6a, из 3dtoday)
# OPENCLIP_MODEL=ViT-B-16
# OPENCLIP_PRETRAINED=openai
# IMAGE_EMBEDDING_DIMENSION=512
# QDRANT_IMAGE_COLLECTION=scinikel_images

# multimodal — Vision LLM (этап 6b, из 3dtoday)
# GEMINI_API_KEY=...                    # или OPENAI_API_KEY через ProxyAPI
# GEMINI_BASE_URL=https://api.proxyapi.ru/google
# GEMINI_MODEL=gemini-3-pro-preview
# OLLAMA_VISION_MODEL=llava
# VISION_PRIMARY_MODEL=ollama_llava    # llava | gemini_proxyapi
```

Опциональные пакеты: `open-clip-torch`, `Pillow` (как в 3dtoday `requirements.txt`).

Runtime UI: `search_mode` в `data/llm_runtime.json` (`keyword` | `vector`); позже `image_search: true`.

---

## Зависимости

| Пакет | 3dtoday | scinikel |
|-------|---------|----------|
| sentence-transformers + torch | ✅ | ✅ `[search]` |
| qdrant-client | ✅ | ✅ core |
| open-clip-torch + Pillow | ✅ | ✅ этап 6a |
| ProxyAPI Gemini (`gemini-3.5-flash`) | ✅ | ✅ этап 6b |
| Ollama llava | ✅ | 🟡 fallback, не тестировали |
| rank-bm25 | ❌ | ⬜ planned |

---

## Связанные документы

- [SEARCH_ROADMAP.md](./SEARCH_ROADMAP.md) — этапы 0–6 с отметками 3dtoday
- [PLAN.md](../PLAN.md) — общий план проекта
- [README.md](../README.md) — быстрый старт

---

*Путь к исходникам 3dtoday на этой машине: `/media/cnn/home/cnn/3dtoday`*
