# Научный клубок

**Научный клубок** — скелет knowledge graph + диалогового ассистента для трека хакатона Норникель. Диалог сверху, граф знаний и семантический поиск снизу. Каждый ответ опирается на эксперименты, документы и справочники — не на «память» модели.

> Идея и позиционирование: [Best_Idea.md](./Best_Idea.md)

## Архитектура

```
┌─────────────────────────────────────────┐
│  UI: чат + визуализация графа (vis.js)  │
└──────────────────┬──────────────────────┘
                   │ REST /api/chat
┌──────────────────▼──────────────────────┐
│  ResearchAgent (LLM + fallback)         │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  HybridQueryEngine                      │
│  · парсинг вопроса (→ NER/LLM позже)    │
│  · обход графа (материал×режим→свойство)│
│  · семантический поиск по документам    │
└───────┬──────────────────────┬──────────┘
        │                      │
┌───────▼────────┐    ┌────────▼─────────┐
│ GraphStore     │    │ DocumentIndex    │
│ NetworkX/Neo4j │    │ Qdrant + e5      │
└────────────────┘    └──────────────────┘
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

## Быстрый старт

```bash
cd scinikel
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,search]"   # search = sentence-transformers/e5

# Загрузить демо-данные
python scripts/seed_data.py

# Запустить сервер
scinikel
# или: uvicorn scinikel.api.app:app --reload
```

Откройте http://localhost:8000

### LLM через config.env

```bash
cp config.env.example config.env
# заполните OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
```

Файл `config.env` в корне проекта (не коммитится). Поддерживаются OpenAI/ProxyAPI и Ollama (`LLM_PROVIDER=ollama`).

## Примеры вопросов

- «Что делали по Ni-Cu концентрату при флотации pH 10.5 и какой эффект на извлечение Ni?»
- «Кто занимался электролизом и на какой установке?»
- «Какие комбинации материал×режим ещё не исследованы?»

### Qdrant + embeddings (как в [3dtoday](https://github.com/kobyzev-yuri/3dtoday))

```bash
./scripts/start_qdrant.sh
# или: docker compose up -d qdrant
```

Без Qdrant система работает в keyword-fallback режиме.

## API

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/chat` | Диалог с ассистентом |
| POST | `/api/ingest/xlsx` | Загрузка каталога экспериментов (XLSX) |
| POST | `/api/ingest/pdf` | Парсинг PDF + CuratorAgent → граф |
| POST | `/api/ingest/curate` | Текст → извлечение сущностей → граф |
| GET | `/api/search/status` | Backend поиска (qdrant+e5 / keyword) |
| GET | `/api/graph/stats` | Статистика графа |
| GET | `/api/graph/subgraph/{id}` | Фрагмент графа для визуализации |
| GET | `/api/entities` | Поиск сущностей |
| POST | `/api/admin/reload` | Перезагрузка seed-данных |

## Подключение данных хакатона

Скелет рассчитан на поэтапное наполнение:

1. **Каталог экспериментов** → `experiments.json`, `experiments.xlsx` или `POST /api/ingest/xlsx`
2. **Корпус документов** → `documents.json`, PDF через `POST /api/ingest/pdf`
3. **Отчёты/статьи** → `POST /api/ingest/curate` (CuratorAgent → граф + Qdrant)

После добавления файлов:

```bash
python scripts/seed_data.py
# или POST /api/admin/reload
```

### Точки расширения

| Модуль | Что менять при получении данных |
|--------|----------------------------------|
| `data/schemas/ontology.yaml` | Новые сущности и связи |
| `scinikel/ingest/pdf_parser.py` | PDF (PyPDF2 + PyMuPDF) |
| `scinikel/ingest/xlsx_parser.py` | XLSX каталог экспериментов |
| `scinikel/agent/curator.py` | LLM JSON extraction → граф |
| `scinikel/search/embeddings.py` | multilingual-e5-base |
| `scinikel/search/vector_db.py` | Qdrant |
| `scinikel/query/engine.py` | NER, LLM-intent, Cypher |
| `scinikel/graph/neo4j_store.py` | Production graph backend |
| `scinikel/agent/assistant.py` | Tool-calling, уточняющие вопросы |

## Тесты

```bash
pytest
```

## Docker

```bash
docker compose up --build
```

## Структура проекта

```
scinikel/
├── Best_Idea.md           # заявка / vision
├── data/
│   ├── schemas/ontology.yaml
│   ├── seed/              # демо-данные (заменить реальными)
│   └── graph.json         # persisted graph (генерируется)
├── frontend/              # чат + граф
├── src/scinikel/
│   ├── agent/             # LLM-ассистент
│   ├── api/               # FastAPI
│   ├── graph/             # NetworkX / Neo4j
│   ├── ingest/            # ETL
│   ├── models/            # Pydantic-сущности
│   ├── query/             # гибридный поиск
│   └── search/            # векторный индекс
├── scripts/seed_data.py
└── tests/
```

## Roadmap для хакатона

- [ ] Импорт реального каталога эксперimentов (CSV/API)
- [ ] NER по корпусу документов → автоматическое наполнение графа
- [ ] Мультимодальность: схемы установок, графики из PDF
- [ ] Neo4j + Cypher для сложных обходов
- [ ] Уточняющий диалог («какой именно сплав?», «за какой период?»)
- [ ] Экспорт «истории решений» и отчёт по пробелам
