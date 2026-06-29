# Научный клубок

**Научный клубок** — knowledge graph + диалоговый ассистент для трека хакатона Норникель. Исследователь ведёт обычный диалог; каждый ответ опирается на эксперименты, документы и справочники — не на «память» модели.

> Идея и позиционирование: [Best_Idea.md](./Best_Idea.md)  
> План работ и статус: [PLAN.md](./PLAN.md)

## Что есть сейчас

| Возможность | Описание |
|-------------|----------|
| **Диалог** | Многоходовый чат с контекстом; уточняющие вопросы («какой материал?») |
| **Сохранение диалогов** | SQLite (`data/conversations.db`), список слева, восстановление после перезагрузки |
| **Таблицы в ответах** | Markdown-таблицы рендерятся как HTML (сравнения экспериментов) |
| **Граф** | Фрагмент связей по каждому ответу, zoom, полноэкранный режим |
| **Пробелы** | Gap-analysis: какие material×mode ещё не исследованы |
| **Демо-данные** | 15 экспериментов, 9 документов, справочники — см. [data/seed/README.md](./data/seed/README.md) |
| **База знаний (отдельная вкладка)** | Загрузка XLSX/PDF, статистика графа, перезагрузка seed |

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
│  · семантический / keyword поиск по документам           │
└───────────┬────────────────────────────┬─────────────────┘
            │                            │
┌───────────▼──────────┐      ┌──────────▼──────────┐
│ GraphStore           │      │ DocumentIndex         │
│ NetworkX (сейчас)    │      │ Qdrant + e5 | keyword │
│ Neo4j (заглушка)     │      └───────────────────────┘
└──────────────────────┘
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
# ./scripts/setup_venv.sh --search   # + sentence-transformers / e5
source .venv/bin/activate

# Демо-данные в граф
python scripts/seed_data.py

# Qdrant + API
./scripts/services.sh start
# stop | restart | status
# ./scripts/services.sh --docker start   # полный стек в Docker
```

Откройте http://localhost:8000

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
- PDF отчёт → `POST /api/ingest/pdf`
- Статистика графа, перезагрузка демо-seed

## Примеры вопросов

**Прямые:**
- «Что делали по Ni-Cu концентрату при флотации pH 10.5 и какой эффект на извлечение Ni?»
- «Кто занимался электролизом и на какой установке?»
- «Какие комбинации материал×режим ещё не исследованы?»

**Многоходовый диалог:**
1. «Что делали по электролизу?» → уточнение материала (чипы)
2. «да, сравни» / «свести в таблицу» → сравнение с HTML-таблицей

## Qdrant + embeddings

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
│   ├── search/            # Qdrant + e5
│   └── storage/           # SQLite диалоги
├── scripts/
│   ├── services.sh        # start/stop Qdrant + API
│   ├── seed_data.py
│   └── build_demo_xlsx.py
└── tests/
```

## Roadmap

**Сейчас (готово к демо на синтетике):**
- [x] Многоходовый диалог + уточнения
- [x] Сохранение диалогов (SQLite)
- [x] HTML-таблицы в чате
- [x] Вкладки: Диалог / База знаний
- [x] Демо-корпус 15 эксп. / 9 док.

**После материалов организаторов:**
- [ ] Импорт реального каталога (формат XLSX/API)
- [ ] Подгонка онтологии и парсеров под их документы
- [ ] NER / Curator на реальном корпусе
- [ ] Hybrid search (graph + vector, metadata boost)

**Если успеем:**
- [ ] pdfplumber — таблицы из PDF
- [ ] Neo4j + Cypher для масштаба
- [ ] Export gap report
- [ ] Мультимодальность (графики из PDF)
