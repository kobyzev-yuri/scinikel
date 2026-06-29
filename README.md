# Научный клубок

**Научный клубок** — knowledge graph + диалоговый ассистент для трека хакатона Норникель. Исследователь ведёт обычный диалог; каждый ответ опирается на эксперименты, документы и справочники — не на «память» модели.

> Идея и позиционирование: [Best_Idea.md](./Best_Idea.md)  
> План работ и статус: [PLAN.md](./PLAN.md)  
> **Юзабилити (бэклог UX):** [docs/USABILITY.md](./docs/USABILITY.md)  
> **Roadmap поиска:** [docs/SEARCH_ROADMAP.md](./docs/SEARCH_ROADMAP.md)  
> **Мультимодальность (статус тестов):** [docs/MULTIMODAL_STATUS.md](./docs/MULTIMODAL_STATUS.md)
> **Перенос из 3dtoday:** [docs/3DTODAY_PORTING.md](./docs/3DTODAY_PORTING.md)

## Что есть сейчас

| Возможность | Описание |
|-------------|----------|
| **Диалог** | Многоходовый чат с контекстом; уточняющие вопросы («какой материал?») |
| **Сохранение диалогов** | SQLite (`data/conversations.db`), список слева, восстановление после перезагрузки |
| **Таблицы в ответах** | Markdown-таблицы рендерятся как HTML (сравнения экспериментов) |
| **Граф** | Фрагмент связей по каждому ответу, zoom, полноэкранный режим |
| **Пробелы** | Gap-analysis: какие material×mode ещё не исследованы |
| **Демо-данные** | 15 экспериментов, 9 документов, справочники — см. [data/seed/README.md](./data/seed/README.md) |
| **База знаний (отдельная вкладка)** | Загрузка XLSX/PDF, Vision+CLIP ingest, статистика графа |

Подход к ingest и онтологии **будет уточняться** после получения материалов от организаторов.

## Архитектура

```
┌──────────────────────────────────────────────────────────┐
│  UI (вкладки)                                            │
│  · Диалог: чат + история диалогов + граф + источники     │
│  · База знаний: ingest XLSX/PDF, админ графа             │
└────────────────────────┬─────────────────────────────────┘
                         │ REST
┌────────────────────────▼─────────────────────────────────┐
│  FastAPI                                                 │
│  · /api/chat (+ conversation_id)                         │
│  · /api/conversations (SQLite)                           │
│  · /api/ingest/*, /api/admin/reload                      │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│  ResearchAgent (LLM + rule-based fallback)             │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│  HybridQueryEngine                                       │
│  · intent + обход графа (material×mode→property)       │
│  · поиск по документам (см. roadmap)                    │
└───────────┬────────────────────────────┬─────────────────┘
            │                            │
┌───────────▼──────────┐      ┌──────────▼──────────┐
│ GraphStore           │      │ DocumentIndex         │
│ NetworkX (сейчас)    │      │ сейчас: keyword|e5    │
│ Neo4j (заглушка)     │      │ план: BM25, hybrid    │
└──────────────────────┘      └───────────────────────┘
```

### Сущности (онтология)

| Сущность | Примеры |
|----------|---------|
| Material | Ni-Cu сплав, сульфидный концентрат |
| Mode | флотация pH 10.5, электролиз 250°C |
| Property | извлечение Ni, прочность на разрыв |
| Experiment | EXP-2024-017 |
| Document | отчёты, статьи |
| Equipment | EL-3, FML-8 |
| Team | лаборатории |
| Conclusion | выводы экспериментов |

Схема связей: [`data/schemas/ontology.yaml`](data/schemas/ontology.yaml)

### NetworkX vs Neo4j

| | **NetworkX (сейчас)** | **Neo4j (позже)** |
|---|----------------------|-------------------|
| Назначение | Демо, хакатон, ~сотни узлов | Тысячи узлов, продакшен |
| Запросы | Python-обход, subgraph | Cypher, multi-hop паттерны |
| Запись | seed + ingest в JSON | Параллельные ingest-пайплайны |
| Инфра | Без отдельного сервера | Кластер, репликация, ACL |

Переключение: `GRAPH_BACKEND=neo4j` (заглушка в `scinikel/graph/neo4j_store.py`).

## Быстрый старт

```bash
cd scinikel
./scripts/setup_venv.sh          # системный Python, без Anaconda
# ./scripts/setup_venv.sh --search      # + sentence-transformers / e5
# ./scripts/setup_venv.sh --multimodal    # + open-clip-torch, Pillow (CLIP)
source .venv/bin/activate

# Демо-данные в граф
python scripts/seed_data.py

# Qdrant + API (рекомендуется для полного режима)
./scripts/services.sh start
# stop | restart | status
# ./scripts/services.sh --api-only start   # без Qdrant — только lite/keyword
```

Откройте http://localhost:8000

### Рекомендуемая конфигурация (по умолчанию)

| Параметр | Значение |
|----------|----------|
| `work_mode` | `full` |
| Куратор / чат | `proxyapi` → `gpt-5.4-mini` |
| Поиск документов | `hybrid` (BM25 + e5 RRF) |
| Vision при PDF | `gemini-3.5-flash` (ProxyAPI) |
| CLIP | `ViT-B-16` → коллекция `scinikel_images` |
| Локальный запасной | `ollama` → `qwen2.5:7b` (режим `local`) |

Файл `data/llm_runtime.json` (шаблон: `data/llm_runtime.json.example`). Подробнее и результаты тестов: **[docs/MULTIMODAL_STATUS.md](./docs/MULTIMODAL_STATUS.md)**.

```bash
# Проверка multimodal ingest
./scripts/fetch_sample_pdfs.sh
python scripts/test_multimodal_ingest.py --pdf data/samples/giab-ni-cu-flotation-water.pdf
```

### LLM через config.env

```bash
cp config.env.example config.env
# OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
# или LLM_PROVIDER=ollama
```

Файл `config.env` в корне (не коммитится). Без LLM ответы формируются из графа (rule-based fallback).

## Интерфейс

### Вкладка «Диалог»

- Чат с демо-вопросами по категориям (клик → отправка).
- **Панель «Диалоги»** слева: автосохранение в SQLite, переключение между беседами, **+ Новый**.
- После перезагрузки страницы или API открывается последний диалог.
- Справа — источники (citations); внизу — интерактивный граф ответа.

**Сохранение диалога** — автоматическое при каждом сообщении. Файл: `data/conversations.db` (в `.gitignore`). Первое сообщение пользователя становится заголовком диалога.

### Вкладка «База знаний»

Загрузка и обслуживание данных — отдельно от исследовательского чата:

- XLSX каталог экспериментов → `POST /api/ingest/xlsx`
- PDF отчёт → `POST /api/ingest/pdf` (галочки **Gemini Vision** и **OpenCLIP**)
- Статистика графа, перезагрузка демо-seed
- Статус Vision/CLIP: `GET /api/vision/status`

## Примеры вопросов

**Прямые:**
- «Что делали по Ni-Cu концентрату при флотации pH 10.5 и какой эффект на извлечение Ni?»
- «Кто занимался электролизом и на какой установке?»
- «Какие комбинации материал×режим ещё не исследованы?»

**Многоходовый диалог:**
1. «Что делали по электролизу?» → уточнение материала (чипы)
2. «да, сравни» / «свести в таблицу» → сравнение с HTML-таблицей

## Поиск по документам (RAG)

**Три слоя:** (A) граф экспериментов — основа ответа; (B) текстовый поиск по PDF; (C) изображения — в плане.

| Режим сейчас | Описание |
|--------------|----------|
| **Граф** | Всегда: material×mode, сравнения, пробелы |
| **keyword** | Naive overlap по целому тексту документа (fallback) |
| **hybrid RRF** | BM25 + e5: `search_mode: hybrid` (default в full) |
| **qdrant+e5** | Только dense: `search_mode: vector` |
| **CLIP images** | OpenCLIP → `scinikel_images`; `GET /api/search/images?q=...` |

**План развития** (поэтапно): BM25 + чанкинг → гибрид (RRF) → graph boost → rerank.

→ Статус этапов: **[docs/SEARCH_ROADMAP.md](./docs/SEARCH_ROADMAP.md)** · тесты ingest: **[docs/MULTIMODAL_STATUS.md](./docs/MULTIMODAL_STATUS.md)**

```bash
# torch + sentence-transformers (если ещё не ставили)
./scripts/setup_venv.sh --search

./scripts/services.sh start    # Qdrant + API
curl -s http://localhost:8000/api/search/status
```

Без Qdrant или при `search_mode: keyword` — только BM25 по чанкам. В `hybrid` при недоступном Qdrant — fallback на BM25.

## Qdrant + embeddings (кратко)

```bash
./scripts/services.sh start    # Qdrant + API
./scripts/services.sh stop
./scripts/services.sh restart
./scripts/services.sh status
```

Без Qdrant (или без `pip install -e ".[search]"`) — режим **keyword** по документам.

## API

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/chat` | Диалог; тело: `message`, `history[]`, `conversation_id?` |
| GET | `/api/conversations` | Список сохранённых диалогов |
| POST | `/api/conversations` | Создать диалог (`title`) |
| GET | `/api/conversations/{id}` | Диалог с сообщениями |
| DELETE | `/api/conversations/{id}` | Удалить диалог |
| GET | `/api/assistant/status` | LLM вкл/выкл, модель |
| GET | `/api/search/status` | Backend поиска (qdrant+e5 / keyword) |
| POST | `/api/ingest/xlsx` | Загрузка каталога экспериментов |
| POST | `/api/ingest/pdf` | Парсинг PDF → граф |
| POST | `/api/ingest/curate` | Текст → CuratorAgent → граф |
| GET | `/api/graph/stats` | Статистика графа |
| GET | `/api/graph/subgraph/{id}` | Фрагмент для vis.js |
| GET | `/api/entities` | Поиск сущностей |
| POST | `/api/admin/reload` | Перезагрузка seed-данных |

Пример чата с сохранением:

```bash
# создать диалог
curl -s -X POST http://localhost:8000/api/conversations \
  -H 'Content-Type: application/json' -d '{"title":"Тест"}'

# отправить сообщение (подставьте id из ответа выше)
curl -s -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Какие пробелы по флотации?","conversation_id":"<uuid>"}'
```

## Подключение данных хакатона

Скелет рассчитан на поэтапное наполнение после материалов организаторов:

1. **Каталог экспериментов** → `experiments.json` / XLSX / `POST /api/ingest/xlsx`
2. **Корпус документов** → `documents.json`, PDF через ingest
3. **Отчёты/статьи** → `POST /api/ingest/curate` (CuratorAgent → граф + Qdrant)

После добавления файлов:

```bash
python scripts/seed_data.py
# или вкладка «База знаний» → «Перезагрузить демо-данные»
# или POST /api/admin/reload
```

### Точки расширения (после реальных данных)

| Модуль | Что менять |
|--------|------------|
| `data/schemas/ontology.yaml` | Новые сущности и связи под корпус Норникеля |
| `scinikel/ingest/xlsx_parser.py` | `COLUMN_ALIASES` под их XLSX |
| `scinikel/ingest/pdf_parser.py` | Структура PDF-отчётов |
| `scinikel/agent/curator.py` | Промпты и схема JSON extraction |
| `scinikel/query/engine.py` | Intent, NER, уточнения |
| `scinikel/graph/neo4j_store.py` | Production graph backend |

## Тесты

```bash
pytest   # 29 тестов: query, assistant, demo data, conversations, …
```

## Docker

```bash
docker compose up --build
```

## Структура проекта

```
scinikel/
├── Best_Idea.md           # vision / заявка
├── PLAN.md                # план и статус для команды
├── docs/
│   └── SEARCH_ROADMAP.md  # этапы поиска: BM25, hybrid, rerank, CLIP
├── data/
│   ├── schemas/ontology.yaml
│   ├── seed/              # демо (см. seed/README.md)
│   ├── graph.json         # persisted graph (генерируется)
│   └── conversations.db   # диалоги (генерируется, не в git)
├── frontend/              # HTML + JS + vis.js
├── src/scinikel/
│   ├── agent/             # ResearchAgent, CuratorAgent
│   ├── api/               # FastAPI
│   ├── graph/             # NetworkX / Neo4j
│   ├── ingest/            # ETL
│   ├── query/             # HybridQueryEngine
│   ├── search/            # DocumentIndex; план: bm25, fusion, rerank
│   └── storage/           # SQLite диалоги
├── scripts/
│   ├── services.sh        # start/stop Qdrant + API
│   ├── seed_data.py
│   └── build_demo_xlsx.py
└── tests/
```

## Roadmap

Сводный статус: **[PLAN.md](./PLAN.md)** · UX-бэклог: **[docs/USABILITY.md](./docs/USABILITY.md)** (2026-06-30)

**Готово к демо:**
- [x] Многоходовый диалог + уточнения + SQLite
- [x] HTML-таблицы, граф (vis.js), вкладки UI
- [x] BM25 + hybrid search (код)
- [x] GIAB: CLIP + Vision + `document_media`
- [x] Галерея рисунков + лайтбокс (без ссылок в новую вкладку)

**В работе / до защиты:**
- [ ] Репетиция demo-сценария GIAB (блок B в PLAN.md)
- [ ] UX: карусель в лайтбоксе, рисунки в старых диалогах — [USABILITY.md](./docs/USABILITY.md)
- [ ] Production reindex e5 на чанках — [SEARCH_ROADMAP.md](./docs/SEARCH_ROADMAP.md)

**После материалов организаторов:**
- [ ] Импорт каталога XLSX + PDF
- [ ] Онтология и парсеры под их формат
- [ ] pdfplumber, Curator dedup

**Если успеем:**
- [ ] Поиск по фото в чате (этап 6c)
- [ ] Rerank, Neo4j, export gap report
