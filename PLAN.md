# План «Научный клубок» — хакатон Норникель

> Зафиксировано для продолжения работ без потери контекста.  
> Репозиторий: https://github.com/kobyzev-yuri/scinikel  
> **Юзабилити — наш приоритет:** [docs/USABILITY.md](docs/USABILITY.md)

## Видение (из Best_Idea.md)

Диалоговый ассистент исследователя поверх **knowledge graph + семантического поиска**.  
LLM не хранит факты — извлекает из графа и документов, отвечает с citation.

**UI:** лёгкий веб (HTML + JS + FastAPI). React — только если успеем. **Streamlit — нет.**

---

## Сводка статуса (2026-06-30)

| Направление | Готовность | Комментарий |
|-------------|------------|-------------|
| **Граф + диалог** | ✅ Демо-ready | 15 эксп., follow-up, таблицы, SQLite |
| **Поиск по документам** | 🟡 | BM25 + hybrid есть; production reindex — частично |
| **Мультимодальность (GIAB)** | ✅ Демо-ready | CLIP + Vision + галерея + лайтбокс |
| **Юзабилити** | 🟡 Хорошая база | Галерея, лайтбокс, карусель, citations в SQLite ✅ |
| **Данные Норникеля** | ⬜ | Ждём материалы организаторов |
| **Тесты** | ✅ 91 pytest | |

---

## Что уже сделано ✅

### Ядро и диалог

| Компонент | Статус |
|-----------|--------|
| Онтология (Material, Mode, Property, Experiment, …) | ✅ `data/schemas/ontology.yaml` |
| GraphStore (NetworkX; Neo4j — заглушка) | ✅ |
| HybridQueryEngine (material×mode→property, gaps, compare) | ✅ |
| Intent **`document_media`** — графики/таблицы одного PDF | ✅ `query/engine.py` |
| ResearchAgent (LLM + rule-based fallback) | ✅ |
| Многоходовый диалог + follow-up | ✅ `agent/assistant.py` |
| Уточняющие вопросы (неоднозначный intent) | ✅ |
| Сохранение диалогов (SQLite) | ✅ |
| HTML-таблицы в ответах чата | ✅ |
| Визуализация графа (vis.js, zoom, modal) | ✅ |

### Поиск и документы

| Компонент | Статус |
|-----------|--------|
| Qdrant + e5 (keyword / vector / hybrid) | ✅ |
| BM25 + чанкинг | ✅ `search/bm25.py`, `search/chunking.py` |
| Гибрид RRF (BM25 + dense) | ✅ |
| dedup, metadata boost, rerank (код) | ✅; rerank выкл по умолчанию |
| GIAB sample PDF + bootstrap индекса | ✅ `data/samples/giab-ni-cu-flotation-water.pdf` |
| Режимы lite / local / full | ✅ `llm_runtime.json`, UI |

### Мультимодальность (этап 6)

| Компонент | Статус |
|-----------|--------|
| Извлечение рисунков из PDF → кэш | ✅ `search/pdf_images.py` |
| Vision (Gemini) при ingest | ✅ `services/vision_analyzer.py` |
| OpenCLIP + Qdrant `scinikel_images` | ✅ |
| Librarian-аннотации к рисункам | ✅ `agent/curator.py`, `text_cleanup.py` |
| `GET /api/media/images/{id}` (inline) | ✅ |
| Фоновая индексация CLIP при старте | ✅ `api/app.py` lifespan |
| Канонические id `p{N}-i1`, prune stale | ✅ |
| Демо-категория «Мультимодальный поиск» | ✅ |

### Юзабилити (недавно)

| Компонент | Статус |
|-----------|--------|
| Вкладки: Главная · Диалог · Демо · Режим · База знаний | ✅ |
| Карточки источников (эксп / док / рисунок) | ✅ |
| **Галерея рисунков под ответом в чате** | ✅ `appendMediaGallery` |
| **Лайтбокс** (крупный просмотр, Esc, карусель ← →) | ✅ `#image-modal` |
| **Citations в SQLite** (галерея при reload диалога) | ✅ `encode_assistant_meta` |
| Подсказка «Открыть Главная» после ответа с источниками | ✅ |
| Без внешних ссылок на `/api/media/…` | ✅ |
| Ответ `format_document_media_answer` без «открыть рисунок» | ✅ |

→ Детали и бэклог UX: **[docs/USABILITY.md](docs/USABILITY.md)**

### Инфраструктура

| Компонент | Статус |
|-----------|--------|
| Ingest PDF / XLSX / Curate | ✅ |
| CuratorAgent → граф | ✅ |
| `scripts/services.sh` | ✅ |
| Порты из 3dtoday | ✅ [docs/3DTODAY_PORTING.md](docs/3DTODAY_PORTING.md) |
| Demo data | ✅ 15 эксп., 9 док., справочники |
| **Тесты** | ✅ **91** pytest |

---

## Архитектура (актуальная)

```
Браузер (HTML/JS)
  ├─ Главная: граф + панель «Источники» (лайтбox)
  ├─ Диалог: чат + галерея рисунков + лайтбокс
  ├─ Демо / Режим / База знаний
        ↓
FastAPI → ResearchAgent → HybridQueryEngine
                              ├─ NetworkX GraphStore        ← слой A
                              ├─ DocumentIndex (BM25/e5/hybrid) ← слой B
                              └─ ImageIndex (CLIP+Qdrant)   ← слой C ✅
Ingest: PDF → Vision → Curator → граф + Qdrant (текст + images)
Кэш рисунков: data/samples/.cache/images/{doc_id}/
```

---

## Что ещё надо доделать

### 🔴 Критично для защиты / демо

| # | Задача | Статус | Документ |
|---|--------|--------|----------|
| 1 | Прогнать GIAB-сценарий end-to-end после `./scripts/services.sh restart` | 🟡 проверить на машине защиты | [USABILITY.md](docs/USABILITY.md) |
| 2 | Demo-сценарий с **мультимодальным** блоком (галерея, не ссылки) | ✅ код · 🟡 репетиция | ниже |
| 3 | Статус API: `giab_image_count: 5`, hybrid search | 🟡 | `GET /api/search/status` |
| 4 | Зафиксировать `llm_runtime.json` для demo (full + hybrid) | 🟡 | [MULTIMODAL_STATUS.md](docs/MULTIMODAL_STATUS.md) |

### 🟡 Качество поиска и RAG

> **Детали:** [docs/SEARCH_ROADMAP.md](docs/SEARCH_ROADMAP.md)

| Этап | Содержание | Статус |
|------|------------|--------|
| 0 | Baseline + порты 3dtoday | ✅ |
| 1 | BM25 + чанкинг | ✅ |
| 2 | e5 на чанках, production Qdrant | 🟡 |
| 3 | Гибрид BM25 + vector (RRF) | ✅ |
| 4 | Graph metadata boost | 🟡 |
| 5 | Rerank (cross-encoder) | 🟡 код, выкл |
| 6a | OpenCLIP + image collection | ✅ |
| 6b | Vision + librarian | ✅ |
| 6c | Поиск по загруженному фото в чате | ⬜ |

### 🟡 Юзабилити (следующие улучшения)

> **Бэклог:** [docs/USABILITY.md](docs/USABILITY.md)

| Приоритет | Задача |
|-----------|--------|
| 🔴 U1 | Карусель ← → в лайтбоксе | ✅ |
| 🔴 U2 | Рисунки при загрузке старого диалога из SQLite | ✅ |
| 🔴 U3 | Подсказка перейти на «Главную» к источникам | ✅ |
| 🟡 U4 | Единый стиль карточек чат / Источники | ✅ |
| 🟡 U5 | Split-view чат + рисунок на широком экране |
| 🟡 U7 | Индикатор «индексируем рисунки…» при старте | ✅ |

### 🟡 После материалов организаторов

- [ ] Загрузить каталог XLSX + PDF через «База знаний»
- [ ] Подогнать `COLUMN_ALIASES` в `xlsx_parser.py`
- [ ] Пересмотреть онтологию и промпты Curator
- [ ] pdfplumber для таблиц в PDF
- [ ] Curator dedup (vector + experiment.id)

### 🟢 Если успеем

- [ ] Этап 6c — upload фото в чат
- [ ] Neo4j backend (слайд про масштаб)
- [ ] React UI
- [ ] Export gap report (Markdown/PDF)

---

## Demo-сценарий для защиты (~4 мин)

### Блок A — граф и диалог (2 мин)

1. Статус в шапке: граф, режим **full**, hybrid search.
2. **Диалог** → *«Что делали по Ni-Cu концентрату при флотации pH 10.5?»*
3. Граф на **Главной**, источники справа.
4. Follow-up: *«свести в таблицу»* → HTML-таблица.

### Блок B — мультимодальность GIAB (2 мин) ⭐

1. **Демо** → «Мультимодальный поиск» → вопрос про **жёсткость воды / графики флотации**.
2. Ответ: аннотации куратора + **галерея рисунков под сообщением**.
3. Клик → **лайтбокс** (стр. 8 — гистограмма Ca²⁺ 27,52 мг/дм³).
4. **Главная** → карточки «Рисунок» → «Увеличить».
5. Фраза для жюри: *«Не уходим по ссылкам — всё в контексте вопроса»*.

### Опционально

- Пробелы material×mode
- Уточняющие чипы
- F5 → диалог восстановился
- Загрузка XLSX live

---

## Быстрый старт

```bash
cd scinikel
./scripts/setup_venv.sh --search --multimodal
source .venv/bin/activate
pip install -e ".[dev,search,multimodal]"
python scripts/seed_data.py
./scripts/services.sh start          # → http://localhost:8000
curl -s http://127.0.0.1:8000/api/search/status | python -m json.tool
pytest
```

Проверка GIAB-рисунков:

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  http://127.0.0.1:8000/api/media/images/doc-giab-ni-cu-flotation-water-p8-i1
ls data/samples/.cache/images/doc-giab-ni-cu-flotation-water/
```

`config.env`: `OPENAI_API_KEY` или `LLM_PROVIDER=ollama`

---

## Известные ограничения

| Проблема | Статус |
|----------|--------|
| Данные Норникеля | ❌ ждём организаторов |
| e5 на чunks — не везде production | 🟡 этап 2 |
| Rerank выключен по умолчанию | 🟡 этап 5 |
| Поиск по фото в чате (6c) | ⬜ |
| Галерея не восстанавливается из SQLite | ✅ citations в JSON meta (новые ответы) |
| Neo4j — заглушка | `graph/neo4j_store.py` |
| `conversations.db` локальная | не в git |

---

## Карта документов

| Файл | Назначение |
|------|------------|
| [PLAN.md](./PLAN.md) | **Этот файл** — общий план и статус |
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | **Архитектура** — слои, потоки, диаграммы |
| [docs/USABILITY.md](./docs/USABILITY.md) | UX: сделано + бэклог + приёмка |
| [docs/SEARCH_ROADMAP.md](./docs/SEARCH_ROADMAP.md) | Этапы поиска BM25 → hybrid → rerank |
| [docs/MULTIMODAL_STATUS.md](./docs/MULTIMODAL_STATUS.md) | CLIP/Vision, тесты GIAB |
| [docs/3DTODAY_PORTING.md](./docs/3DTODAY_PORTING.md) | Перенос паттернов 3dtoday |
| [README.md](./README.md) | Быстрый старт, API |
| [Best_Idea.md](./Best_Idea.md) | Видение для защиты |

---

## Решения (не обсуждать заново)

- **UI:** HTML + JS; юзабилити важнее новых фич
- **Рисунки:** галерея + лайтбокс, не ссылки в новую вкладку
- **Диалоги:** SQLite
- **Vector DB:** Qdrant + e5
- **Graph (хакатон):** NetworkX достаточно
- **Ingest:** паттерны 3dtoday; доработка после реальных файлов

---

*Последнее обновление: 2026-06-30 — зафиксированы мультимодальное GIAB-демо, галерея/лайтбокс, бэклог юзабилити.*
