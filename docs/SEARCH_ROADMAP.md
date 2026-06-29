# Roadmap поиска — «Научный клубок»

> Живой документ: статус этапов обновляем по мере внедрения.  
> **Перенос из 3dtoday (3Dprinter KB):** [3DTODAY_PORTING.md](./3DTODAY_PORTING.md)  
> Исходники: `/media/cnn/home/cnn/3dtoday`

> **Результаты тестов multimodal ingest:** [MULTIMODAL_STATUS.md](./MULTIMODAL_STATUS.md)

**Зависимости на dev-машине:** `./scripts/setup_venv.sh --search --multimodal` (e5 + open-clip-torch).

---

## Три слоя retrieval (не путать)

| Слой | Назначение | Статус | Где в коде |
|------|------------|--------|------------|
| **A. Граф** | Эксперименты, material×mode, сравнения, пробелы | ✅ Работает | `query/engine.py`, `graph/networkx_store.py` |
| **B. Документы (текст)** | Блок «Источники», RAG по PDF/отчётам | 🟡 Частично | `search/index.py` |
| **C. Мультимодальность** | Графики/схемы из PDF | ✅ Работает | `services/vision_analyzer.py`, `search/image_embeddings.py`, ingest PDF |

**Ответ в чате** в первую очередь из **слоя A**. Слои B/C дополняют citations и будущий «полный RAG».

---

## Целевая архитектура

```
                    Запрос пользователя
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
   GraphStore          DocIndex            ImageIndex
   (структура)         (текст)             (CLIP + Vision)
         │                  │                  │
         │            ┌─────┴─────┐            │
         │            ▼           ▼            │
         │         BM25      e5→Qdrant         │
         │            └─────┬─────┘            │
         │                  ▼                  │
         │         Fusion (RRF / weighted)     │
         │                  │                  │
         └──────────────────┼──────────────────┘
                            ▼
                   Rerank (опционально)
                   cross-encoder | LLM
                            ▼
              ResearchAgent → ответ + citations
```

**Принципы:**

- Граф остаётся **источником истины** для фактов об экспериментах.
- Keyword/BM25 и dense — **взаимодополняющие**, не взаимоисключающие.
- Rerank — **после** широкого retrieve, не вместо него.
- LLM-rerank — только при включённом LLM и по флагу (дорого).

---

## Текущее состояние (baseline)

| Возможность | Статус | Примечание |
|-------------|--------|------------|
| Графовый поиск (intent, material, mode, compare) | ✅ | Основной путь ответа |
| Чанкинг документов | ✅ | `chunk_text()`, page `[стр. N]` в PDF |
| BM25 по чанкам | ✅ | Fallback; title+text для индекса (как 3dtoday) |
| Семантический e5 → Qdrant | ✅ | `qdrant+e5+chunks` при `search_mode: vector` |
| Гибрид BM25 + vector (RRF) | ✅ | `search_mode: hybrid` — default в full |
| Graph metadata boost | 🟡 | `metadata_boost.py` + `experiment_ids` из графа |
| Rerank (cross-encoder) | 🟡 | `search/rerank.py`; `RERANK_ENABLED=false` |
| Rerank (LLM) | ⬜ | — |
| Дедуп результатов | ✅ | `search/dedup.py` ← 3dtoday |
| Qdrant payload filters | ✅ | `doc_type`, `experiment_ids` ← 3dtoday |
| **Vision LLM (Gemini 3.5)** | ✅ | `vision_analyzer.py`, ingest PDF |
| **CLIP image search** | ✅ | `scinikel_images`, `GET /api/search/images` |
| Поиск с загруженным фото (6c) | 🟡 | API ingest only; нет `/api/search/image` POST |
| Режимы работы (lite / local / full / custom) | ✅ | default **full** + proxyapi → см. `docs/MULTIMODAL_STATUS.md` |

### Модели и хранилища (текст)

| Компонент | Значение по умолчанию |
|-----------|----------------------|
| Embeddings | `intfloat/multilingual-e5-base` (768 dim) |
| Префиксы E5 | `query:` / `passage:` |
| Vector DB | Qdrant, коллекция `scinikel_docs` |
| Keyword сейчас | In-memory, без BM25 (`search/index.py`) |

### Runtime: что включать

| Цель | `answer_mode` | `search_mode` | Сервисы |
|------|---------------|---------------|---------|
| Минимум RAM, без LLM | `rule` | `keyword` | API only (`--api-only`) |
| LLM без torch на inference | `llm` | `keyword` | Ollama / ProxyAPI |
| Qdrant без LLM | `rule` | `vector` | API + Qdrant + `[search]` |
| Полный стек | `llm` | `vector` | API + Qdrant + Ollama + `[search]` |

Проверка: `GET /api/search/status` → `backend`, `search_mode`, `vector_search_enabled`.

---

## Этапы внедрения

### Этап 0 — Baseline (сделано)

- [x] `DocumentIndex`: vector **или** naive keyword
- [x] `HybridQueryEngine`: граф + `doc_index.search(limit=3)` для sources
- [x] Runtime `search_mode`: `keyword` | `vector`
- [x] Ingest: текст PDF/XLSX/curate → `index_text` / `index_documents`
- [x] Профили «Режим работы» в UI
- [x] Портируемые модули из 3dtoday: dedup, metadata boost, rerank, Qdrant filters

**3dtoday:** нет BM25/chunking — этапы 1–3 пишем сами; dense+metadata+rерank — уже адаптированы.

---

### Этап 1 — Настоящий keyword + чанкинг

**Цель:** BM25 (или Qdrant sparse) вместо naive overlap; документы режутся на чанки.

| Задача | Файлы | Статус |
|--------|-------|--------|
| Чанкинг (по абзацам / overlap) | `search/chunking.py`, ingest | ✅ |
| BM25 индекс in-memory | `search/bm25.py`, `search/index.py` | ✅ |
| Payload: `doc_id`, `chunk_id`, `page`, `experiment_ids` | `search/index.py` | ✅ |
| Поиск возвращает чанк | `GET /api/search/chunks`, citations | ✅ |
| Тесты: `250°C`, `EXP-2024-031` | `tests/test_search_bm25.py` | ✅ |

**Критерий:** запрос «250°C электролиз» находит нужный **фрагмент** PDF без e5.

**Критерий приёмки:** демо на seed без torch; с `--search` + Qdrant — `backend: qdrant+e5`.

**3dtoday:** chunking только в `config.env.example`, в коде нет — **реализуем с нуля**.

**Цель:** стабильный семантический поиск; torch/e5 уже установлены.

| Задача | Файлы | Статус |
|--------|-------|--------|
| Индексировать **чанки**, не целые документы | `search/index.py`, `embeddings.py` | ⬜ |
| Отдельные point id на чанк в Qdrant | `search/vector_db.py` | ⬜ |
| Профиль UI «Семантический поиск» + документация | `frontend/`, README | 🟡 частично |
| Healthcheck: модель загружена, размерность 768 | `/api/search/status` | ⬜ |
| Fallback: Qdrant down → BM25 (не naive keyword) | `search/index.py` | ⬜ |
| Retrieve k=20 → dedup → rerank → top-5 | `search/index.py` | ✅ (из RetrievalAgent) |

**3dtoday:** whole-article indexing — у нас тот же долг; чанки — наш этап 1+2.

**Критерий:** перефраз («повышенная температура очистки никеля») находит тот же чанк, что и «250°C».

**Оценка:** 1 день (после этапа 1).

---

### Этап 3 — Гибрид (BM25 + dense)

**Цель:** объединить оба сигнала; industry-standard RRF.

| Задача | Файлы | Статус |
|--------|-------|--------|
| `search_mode: hybrid` в runtime | `services/llm_runtime.py` | ✅ default full |
| RRF fusion top-k | `search/fusion.py` | ✅ |
| `DocumentIndex.search()` → единый ranked list | `search/index.py` | ✅ |
| UI: режим «Гибрид (BM25 + e5)» | `frontend/index.html` | ✅ |
| Метрики в `/api/search/status`: `backends_active[]` | `api/app.py` | ✅ |

**3dtoday:** «hybrid» = metadata boost, **не** BM25+vector. Настоящий RRF — **новый код scinikel**.

**Цель:** эксперименты из графа поднимают связанные документы/чанки.

| Задача | Файлы | Статус |
|--------|-------|--------|
| Связь Document ↔ Experiment в графе / payload | ingest, `graph_materializer` | 🟡 частично |
| `experiment_ids` из графа → doc search filters | `query/engine.py` | ✅ |
| Boost по experiment_id в metadata | `search/metadata_boost.py` | ✅ |

**3dtoday:** boost по `printer_models` / `materials` — у нас аналог через `experiment_ids`.

**Критерий:** при ответе по EXP-2024-031 источником №1 — PDF с этим экспериментом.

**Оценка:** 1 день.

---

### Этап 5 — Rerank

**Цель:** сузить top-20 → top-3–5 перед ответом / citations.

| Вариант | Когда | Статус |
|---------|-------|--------|
| **A. Cross-encoder** (`bge-reranker-v2-m3` или аналог) | По умолчанию для hybrid | ✅ код (`RERANK_ENABLED`) |
| **B. LLM rerank** | `answer_mode: llm` + флаг `rerank: llm` | ⬜ |
| **C. Без rerank** | lite / экономия latency | ✅ по умолчанию |

| Задача | Файлы | Статус |
|--------|-------|--------|
| `search/rerank.py` — CrossEncoder | ✅ ← `RetrievalAgent` | ✅ |
| Retrieve k=20, rerank k=5 | `search/index.py` | ✅ |
| Runtime: `rerank_mode` в UI | `llm_runtime.json` | ⬜ |

**Критерий:** latency rerank < 500 ms на CPU для top-20 (cross-encoder).

**Оценка:** 1–2 дня.

---

### Этап 6 — Мультимодальность (из 3dtoday: CLIP + Gemini/llava)

**В 3dtoday уже есть полный стек** — переносим по подэтапам, не изобретаем заново.

#### 6a — OpenCLIP + Qdrant images

| Задача | Источник 3dtoday | Статус |
|--------|------------------|--------|
| `OpenCLIPEmbeddings` | `openclip_embeddings.py` | ✅ `search/image_embeddings.py` |
| Коллекция `scinikel_images` (512d) | `vector_db` dual collection | ✅ |
| `index_image()` при PDF ingest | `article_indexer.index_image` | ✅ `api/app.py` ingest_pdf |
| `search(is_image=True)` | `rag_service.search` | ✅ `GET /api/search/images` |

#### 6b — Vision LLM + умный библиотекарь (таблицы, графики)

| Задача | Источник 3dtoday | Статус |
|--------|------------------|--------|
| `VisionAnalyzer` + промпт «таблицы, текст, графики» | `vision_analyzer.py` | ✅ `gemini-3.5-flash` |
| `_analyze_images()` при ingest (до 10 img) | `kb_librarian.py` | ✅ `curator._analyze_images` |
| Слияние `image_analysis` → контент куратора | `_create_summary()` | ✅ `_merge_image_context` |
| Передать `images` из `pdf_parser` в curator | `api/app.py` ingest_pdf | ✅ |
| Промпт: таблицы EXP, Ni/Cu, T, pH | адаптация домена | ✅ |
| `check_relevance` → металлургия | `check_relevance_to_3d_printing` | ✅ keyword heuristic |
| Gemini via ProxyAPI | `GEMINI_BASE_URL` | ✅ |
| Fallback Ollama `llava` | `OLLAMA_VISION_MODEL` | 🟡 код есть, не тестировали |
| Куратор LLM | GPT / Ollama | ✅ default **gpt-5.4-mini** (см. тесты) |

**Протестировано:** `data/samples/giab-ni-cu-flotation-water.pdf` — [MULTIMODAL_STATUS.md](./MULTIMODAL_STATUS.md)

#### 6c — Поиск с изображением + UI

| Задача | Источник 3dtoday | Статус |
|--------|------------------|--------|
| `search_with_image()` | `retrieval_agent.py` | ⬜ |
| `vision_context` → enhance query → e5 → rerank | тот же пайплайн | ⬜ |
| API `POST /api/diagnose/image` | `main.py` | ⬜ → `POST /api/search/image` |
| UI upload + preview | `user_ui.py` | ⬜ |

**Критерий:** PDF с графиком → CLIP находит фигуру; Gemini добавляет текстовое описание в Curator; опционально поиск по загруженному фото.

**Оценка:** 6a ~1 день (порт), 6b ~1–2 дня, 6c ~1 день.

---

## Сводная таблица статусов

| Этап | Название | Статус | Приоритет |
|------|----------|--------|-----------|
| 0 | Baseline + порты из 3dtoday (dedup, boost, rerank) | ✅ | — |
| 1 | BM25 + чанкинг | ⬜ | 🔴 (нет в 3dtoday) |
| 2 | Dense production (e5 чанки) | 🟡 | 🔴 |
| 3 | Гибрид RRF (BM25+dense) | ⬜ | 🟡 (≠ hybrid 3dtoday) |
| 4 | Graph metadata boost | 🟡 частично | 🟡 |
| 5 | Rerank CrossEncoder | 🟡 код, выкл по умолчанию | 🟢 |
| 6 | Мультимодальность: CLIP + Gemini | ✅ 6a–6b / 🟡 6c | см. [MULTIMODAL_STATUS.md](./MULTIMODAL_STATUS.md) |

**Легенда:** ✅ готово · 🟡 частично · ⬜ не начато

---

## Рекомендуемый порядок работ (что успеем на хакатон)

1. **Этап 1** — BM25 + чанкинг (максимальный эффект при уже установленном torch).
2. **Этап 2** — включить e5 на чанках; профиль «Qdrant без LLM» для демо.
3. **Этап 3** — гибрид (сильный слайд на защите).
4. **Этап 4** — graph boost (уникальность «клубка»).
5. **Этап 6c** — поиск с фото в API/UI (остаток мультимодальности).
6. **Этап 1–3** — BM25, чанкинг, RRF (следующий приоритет после мультимодальности).

---

## API и конфигурация (целевое)

### `GET /api/search/status` (расширить)

```json
{
  "backend": "hybrid",
  "search_mode": "hybrid",
  "backends_active": ["graph", "bm25", "qdrant+e5"],
  "rerank_mode": "none",
  "image_search": false,
  "chunk_count": 42,
  "embedding_model": "intfloat/multilingual-e5-base"
}
```

### `data/llm_runtime.json` (целевые поля)

```json
{
  "search_mode": "keyword | vector | hybrid",
  "rerank_mode": "none | cross_encoder | llm",
  "image_search": false
}
```

---

## Тесты (добавлять по этапам)

| Файл | Покрытие |
|------|----------|
| `tests/test_search_bm25.py` | BM25, чанки, EXP-ID |
| `tests/test_search_vector.py` | e5, Qdrant mock |
| `tests/test_search_hybrid.py` | RRF, fusion |
| `tests/test_search_graph_boost.py` | boost по experiment_id |
| `tests/test_query.py` | граф (уже есть) |

---

## Связанные документы

- [PLAN.md](../PLAN.md) — общий план проекта
- [README.md](../README.md) — быстрый старт, API
- [data/seed/README.md](../data/seed/README.md) — демо-сценарии неоднозначности
- [3DTODAY_PORTING.md](./3DTODAY_PORTING.md) — карта переноса из 3dtoday

---

*Последнее обновление статуса: 2026-06-29 — зафиксирован вектор развития поиска; torch/sentence-transformers на dev установлены.*
