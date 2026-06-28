# План «Научный клубок» — хакатон Норникель

> Зафиксировано для продолжения работ без потери контекста.  
> Репозиторий: https://github.com/kobyzev-yuri/scinikel

## Видение (из Best_Idea.md)

Диалоговый ассистент исследователя поверх **knowledge graph + семантического поиска**.  
LLM не хранит факты — извлекает из графа и документов, отвечает с citation.

**UI:** лёгкий веб (HTML + JS + FastAPI). React — только если успеем. **Streamlit — нет.**

---

## Что уже сделано ✅

| Компонент | Статус |
|-----------|--------|
| Онтология (Material, Mode, Property, Experiment, …) | ✅ `data/schemas/ontology.yaml` |
| GraphStore (NetworkX, Neo4j — заглушка) | ✅ |
| HybridQueryEngine (material×mode→property, gaps) | ✅ |
| ResearchAgent (LLM + rule-based fallback) | ✅ |
| Веб-чат + vis.js граф | ✅ `frontend/` |
| Ingest PDF (PyPDF2 + PyMuPDF) | ✅ `ingest/pdf_parser.py` |
| Ingest XLSX → ExperimentRecord | ✅ `ingest/xlsx_parser.py` |
| CuratorAgent (LLM JSON + heuristic → граф) | ✅ `agent/curator.py` |
| Qdrant + multilingual-e5 (keyword fallback) | ✅ `search/` |
| API ingest + chat | ✅ `/api/ingest/*`, `/api/chat` |
| Docker + Qdrant | ✅ `docker-compose.yml` |
| Тесты | ✅ 7/7 pytest |
| Demo data | ✅ 5 эксперimentов, 3 документа |

**Коммиты на GitHub:** `6c50a27` (скелет) → `afdf4f9` (ingest + Curator + Qdrant)

---

## Архитектура (не менять без причины)

```
Браузер (HTML/JS) → FastAPI → ResearchAgent
                              → HybridQueryEngine
                                   ├─ NetworkX GraphStore
                                   └─ DocumentIndex (Qdrant+e5 | keyword)
Ingest: PDF/XLSX/Curate → CuratorAgent → graph_materializer → граф + Qdrant
```

Паттерны из [3dtoday](https://github.com/kobyzev-yuri/3dtoday): парсеры, e5, Qdrant, KBLibrarian → CuratorAgent.

---

## Приоритеты на завтра

### 🔴 День 1 — данные + demo path

- [ ] **Получить данные организаторов** — каталог эксперimentов (XLSX), PDF-отчёты, справочники
- [ ] Загрузить: `POST /api/ingest/xlsx`, `POST /api/ingest/pdf`
- [ ] Подогнать `COLUMN_ALIASES` в `xlsx_parser.py` под их формат
- [ ] **Починить intent `who_did_what`** — сейчас парсится, но не обрабатывается в `query/engine.py`
- [ ] **Sample `data/seed/experiments.xlsx`** + e2e тест
- [ ] Прогнать demo-сценарий на чистой машине (`docker compose up`)

### 🟡 День 2 — качество + UI (лёгкий, без Streamlit)

- [ ] UI: кнопка «Пробелы в данных»
- [ ] UI: статус поиска (`/api/search/status` — qdrant+e5 / keyword)
- [ ] UI: форма загрузки XLSX/PDF (`fetch` → `/api/ingest/*`)
- [ ] UI: markdown в ответах чата (списки, жирный)
- [ ] **Hybrid search** — graph + vector вместе, metadata boost (из 3dtoday)
- [ ] **Ollama в ResearchAgent** — через `services/llm.py` (как в Curator)
- [ ] **pdfplumber** — таблицы из PDF-отчётов

### 🟢 День 3 — если успеем

- [ ] OpenCLIP + Qdrant images — рисунки/графики из PDF (из 3dtoday)
- [ ] Curator dedup (vector + experiment.id)
- [ ] Export gap report (Markdown/PDF)
- [ ] Справочники: equipment, teams, topics — отдельные JSON/листы XLSX
- [ ] React UI (замена frontend/, API уже готов)
- [ ] Neo4j backend (для слайда масштабируемости)
- [ ] `docs/` для защиты: demo-script, architecture one-pager

---

## Demo-сценарий для защиты (3 мин)

1. Показать статистику графа (38+ сущностей после загрузки данных)
2. Вопрос: *«Что делали по Ni-Cu концентрату при флотации pH 10.5 и какой эффект на извлечение Ni?»*
3. Показать **граф связей** + **источники**
4. Вопрос: *«Какие комбинации материал×режим ещё не исследованы?»*
5. (Опционально) загрузить XLSX live → новые узлы в графе

---

## Быстрый старт

```bash
cd scinikel
source .venv/bin/activate
pip install -e ".[dev,search]"
./scripts/start_qdrant.sh          # опционально
python scripts/seed_data.py
scinikel                           # → http://localhost:8000
pytest
```

`.env`: `OPENAI_API_KEY` или `LLM_PROVIDER=ollama`

---

## Известные пробелы / баги

| Проблема | Где |
|----------|-----|
| `who_did_what` не реализован в execute | `query/engine.py` |
| Markdown в чате — plain text | `frontend/static/app.js` |
| PDF-картинки парсятся, не индексируются | `pdf_parser.py` → нет OpenCLIP |
| Neo4j — только заглушка | `graph/neo4j_store.py` |
| Assistant LLM — только OpenAI | `agent/assistant.py` |
| Реальные данные Норникеля | ❌ ждём от организаторов |

---

## API шпаргалка

```bash
# Чат
curl -X POST http://localhost:8000/api/chat -H 'Content-Type: application/json' \
  -d '{"message":"..."}'

# Ingest
curl -F "file=@catalog.xlsx" http://localhost:8000/api/ingest/xlsx
curl -F "file=@report.pdf" http://localhost:8000/api/ingest/pdf

# Статус
curl http://localhost:8000/api/graph/stats
curl http://localhost:8000/api/search/status
```

---

## Решения (не обсуждать заново)

- **UI:** HTML + JS, не Streamlit
- **Vector DB:** Qdrant + e5, не ChromaDB
- **Graph (хакатон):** NetworkX достаточно
- **Ingest:** проверенные паттерны из 3dtoday
- **Git SSH:** `~/.ssh/1234`, remote `git@github.com:kobyzev-yuri/scinikel.git`
