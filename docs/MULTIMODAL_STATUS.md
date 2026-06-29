# Мультимодальный ingest — статус и результаты тестов

> Обновлено: 2026-06-29. Связанные документы: [SEARCH_ROADMAP.md](./SEARCH_ROADMAP.md), [3DTODAY_PORTING.md](./3DTODAY_PORTING.md)

## Рекомендуемая конфигурация (зафиксирована по умолчанию)

| Компонент | Значение | Назначение |
|-----------|----------|------------|
| **work_mode** | `full` | LLM + vector search + multimodal ingest |
| **provider** (куратор/чат) | `proxyapi` | `gpt-5.4-mini` — точнее извлечение из PDF |
| **ollama_model** (запасной) | `qwen2.5:7b` | режим `local`, быстрый офлайн-куратор |
| **search_mode** | `hybrid` | BM25 + Qdrant e5 (RRF) — рекомендуется |
| **Vision** | `gemini-3.5-flash` | описание таблиц/графиков при PDF ingest |
| **CLIP** | `ViT-B-16` → `scinikel_images` | поиск по рисункам из PDF |

Файлы: `data/llm_runtime.json`, `config.env` (`GEMINI_MODEL`, `OPENAI_*`).

```bash
./scripts/services.sh start          # API + Qdrant (не --api-only)
cp data/llm_runtime.json.example data/llm_runtime.json  # при первом клоне
./scripts/setup_venv.sh --search --multimodal  # e5 + open-clip-torch
```

## Где мы на roadmap

| Этап | Название | Статус |
|------|----------|--------|
| 0 | dedup, metadata boost, rerank (код) | ✅ |
| 1 | BM25 + чанкинг | 🟡 BM25 + chunks ✅; Qdrant reindex при restart |
| 2 | Dense e5 на чанках | 🟡 e5 на целом документе |
| 3 | Гибрид RRF | ✅ |
| 4 | Graph metadata boost | 🟡 |
| 5 | Rerank CrossEncoder | 🟡 выкл (`RERANK_ENABLED=false`) |
| **6a** | OpenCLIP + Qdrant images | ✅ |
| **6b** | Vision LLM + куратор | ✅ |
| **6c** | Поиск с фото + UI upload | 🟡 карточки источников + ingest-панель; POST image search — нет |

## Прогон на GIAB PDF (2026-06-29)

Тестовый файл: `data/samples/giab-ni-cu-flotation-water.pdf`  
Статья: «Исследование влияния ионов жёсткости воды на флотируемость медно-никелевых руд» (ГИАБ, 2022).

```bash
python scripts/test_multimodal_ingest.py --pdf data/samples/giab-ni-cu-flotation-water.pdf
```

### Результаты по конфигурациям

| Конфиг | curator | property_value | Время | Примечание |
|--------|---------|----------------|-------|------------|
| `lite` / rule | heuristic | «см. таблицы» | ~1 мин | без LLM, без Qdrant |
| `full` + `qwen2.5:7b` | llm | «не указано численно» | ~68 с | локально, быстро |
| **`full` + `gpt-5.4-mini`** | **llm** | **`27,52 мг/дм³` (Ca²⁺)** | **~51 с** | **рекомендуется** |
| `qwen3.6:27b` | timeout → heuristic | — | >120 с | не использовать для ingest |

### Стабильно работает (full + GPT)

| Метрика | Значение |
|---------|----------|
| Vision (Gemini 3.5) | 3–5 / 5 картинок |
| CLIP indexed | 5 |
| Поиск «график извлечения никеля» | top-1: стр. 6, рис. 1 (score ~0.285) |
| Эксперимент | `EXP-2024-001`, флотация Cu-Ni, Ca²⁺ в пульпе |
| doc_id | `DOC-giab-ni-cu-flotation-water` (не `tmp…`) |

### Известные ограничения

- Проценты извлечения Ni/Cu из **графиков** не всегда попадают в `property_value` — статья даёт модели k, ε₀, а не «Ni 87%».
- Дубликаты в Qdrant при повторном ingest одного PDF (разные `doc-tmp*` с прошлых прогонов).
- MDPI PDF — 403 при `curl` без Referer; ГИАБ/КиберЛенинка/Springer — ок (`scripts/fetch_sample_pdfs.sh`).

## UI: представление результатов (2026-06-30)

**Вкладка «Диалог»:**
- Ответ `document_media`: аннотации куратора + блок **«Рисунки из документа»** (сетка миниатюр)
- Клик по миниатюре → **лайтбокс** (крупный просмотр, подпись, аннотация; Esc — закрыть)
- Без переходов по URL `/api/media/images/…` в новой вкладке

**Вкладка «Главная» → «Источники»:**
- Карточки: эксперимент · документ · рисунок (CLIP)
- Миниатюра + кнопка **«Увеличить»** → тот же лайтбокс
- Кнопки: «На графе», «Спросить про документ»

**Вкладка «База знаний» → после PDF ingest:**
- Сводка: страницы, Vision, CLIP, эксперимент в графе
- Быстрый переход в диалог / проверка CLIP

→ Бэклог UX (карусель, история диалогов): [USABILITY.md](./USABILITY.md)

## Следующие шаги (по приоритету)

1. **Юзабилити:** карусель в лайтбоксе, галерея при загрузке старого диалога — см. [USABILITY.md](./USABILITY.md).
2. Промпт куратора: явно тянуть числа из блока Vision (ε₀, k, Ca²⁺).
3. Этап 2 — production reindex e5 на чанках.
4. Этап 6c — `POST /api/search/image` с загрузкой фото в чат.
5. Очистка/дедуп image-коллекции Qdrant при re-ingest (частично: `delete_doc_images`, prune cache).
