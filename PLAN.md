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
| GraphStore (NetworkX; Neo4j — заглушка) | ✅ |
| HybridQueryEngine (material×mode→property, gaps, compare) | ✅ |
| ResearchAgent (LLM + rule-based fallback) | ✅ |
| Многоходовый диалог + follow-up («да, сравни», «свести в таблицу») | ✅ `agent/assistant.py` |
| Уточняющие вопросы (неоднозначный intent) | ✅ `query/engine.py` |
| Сохранение диалогов (SQLite) | ✅ `storage/conversations.py`, API |
| Веб-UI: вкладки **Диалог** / **База знаний** | ✅ `frontend/` |
| HTML-таблицы в ответах чата | ✅ `frontend/static/app.js` |
| История диалогов в сайдбаре | ✅ |
| Визуализация графа (vis.js, zoom, modal) | ✅ |
| Демо-вопросы по категориям в UI | ✅ |
| Ingest PDF / XLSX / Curate | ✅ |
| CuratorAgent (LLM JSON + heuristic → граф) | ✅ |
| Qdrant + e5 (keyword fallback без torch) | ✅ |
| `scripts/services.sh` (start/stop/restart) | ✅ |
| Demo data | ✅ 15 эксп., 9 док., справочники |
| Тесты | ✅ **29** pytest |

**Текущая стратегия:** демо на синтетике выглядит достаточно для защиты скелета. **Подходы к ingest и онтологии обновим после получения материалов организаторов.**

---

## Архитектура (не менять без причины)

```
Браузер (HTML/JS, 2 вкладки)
  ├─ Диалог: чат + SQLite history + граф + citations
  └─ База знаний: ingest XLSX/PDF, admin reload
        ↓
FastAPI → ResearchAgent → HybridQueryEngine
                              ├─ NetworkX GraphStore
                              └─ DocumentIndex (Qdrant+e5 | keyword)
Ingest: PDF/XLSX/Curate → CuratorAgent → graph_materializer → граф + Qdrant
Диалоги: SQLite (data/conversations.db)
```

Паттерны из [3dtoday](https://github.com/kobyzev-yuri/3dtoday): парсеры, e5, Qdrant, CuratorAgent.

---

## Приоритеты (актуально)

### 🔴 Сейчас — ждём данные организаторов

- [ ] **Получить материалы** — каталог экспериментов (XLSX), PDF-отчёты, справочники
- [ ] Загрузить через вкладку «База знаний» или API ingest
- [ ] Подогнать `COLUMN_ALIASES` в `xlsx_parser.py` под их формат
- [ ] Пересмотреть онтологию и промпты Curator под реальный корпус
- [ ] Прогнать demo-сценарий на их данных

### 🟡 Качество (после первого импорта)

- [ ] **Hybrid search** — graph + vector вместе, metadata boost
- [ ] **pdfplumber** — таблицы из PDF-отчётов
- [ ] Curator dedup (vector + experiment.id)
- [ ] Export gap report (Markdown/PDF)

### 🟢 Если успеем

- [ ] OpenCLIP + Qdrant images — графики из PDF
- [ ] Neo4j backend (масштаб, Cypher)
- [ ] React UI (API уже готов)
- [ ] `docs/` для защиты: one-pager, demo-script

---

## Demo-сценарий для защиты (~3 мин)

1. Статус: граф (~100+ сущностей), LLM badge, backend поиска.
2. Вкладка **Диалог** → демо-вопрос: *«Что делали по Ni-Cu концентрату при флотации pH 10.5?»*
3. Показать **граф**, **источники**, ответ с LLM.
4. Follow-up: *«сравни с pH 9»* → **таблица** в чате.
5. Вопрос про **пробелы** (material×mode).
6. (Опционально) неоднозначный вопрос → **уточнение** чипами.
7. (Опционально) вкладка **База знаний** → загрузка XLSX live.
8. (Опционально) F5 → **диалог восстановился** из SQLite.

---

## Быстрый старт

```bash
cd scinikel
./scripts/setup_venv.sh
source .venv/bin/activate
pip install -e ".[dev,search]"
python scripts/seed_data.py
./scripts/services.sh start          # → http://localhost:8000
pytest
```

`config.env`: `OPENAI_API_KEY` или `LLM_PROVIDER=ollama`

---

## Диалоги: как сохранить и вернуться

| Действие | Как |
|----------|-----|
| Сохранить | Автоматически при каждом сообщении |
| Где хранится | `data/conversations.db` |
| Вернуться после F5 | Открывается последний диалог |
| Другой диалог | Клик в списке слева |
| Новый диалог | **+ Новый** |
| После restart API | История на месте (файл БД не трогать) |

---

## Известные ограничения

| Проблема | Где / статус |
|----------|----------------|
| Данные Норникеля | ❌ ждём от организаторов |
| PDF-картинки не индексируются | нет OpenCLIP |
| Neo4j — заглушка | `graph/neo4j_store.py` |
| Онтология и парсеры | под синтетику; пересмотр после импорта |
| `conversations.db` локальная | не в git; на другой машине — пусто |

---

## API шпаргалка

```bash
# Чат (с диалогом)
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"...","conversation_id":"<uuid>"}'

# Диалоги
curl http://localhost:8000/api/conversations
curl http://localhost:8000/api/conversations/<uuid>

# Ingest
curl -F "file=@catalog.xlsx" http://localhost:8000/api/ingest/xlsx
curl -F "file=@report.pdf" http://localhost:8000/api/ingest/pdf

# Статус
curl http://localhost:8000/api/graph/stats
curl http://localhost:8000/api/assistant/status
curl http://localhost:8000/api/search/status
```

---

## Решения (не обсуждать заново)

- **UI:** HTML + JS, две вкладки; не Streamlit
- **Диалоги:** SQLite, не localStorage
- **Vector DB:** Qdrant + e5, не ChromaDB
- **Graph (хакатон):** NetworkX достаточно; Neo4j — слайд про масштаб
- **Ingest:** паттерны из 3dtoday; доработка после реальных файлов
- **Git SSH:** `~/.ssh/1234`, remote `git@github.com:kobyzev-yuri/scinikel.git`
