# Образцы PDF для теста multimodal ingest

Подобраны под демо-данные scinikel: **Ni-Cu**, **флотация**, **электролиз**, таблицы с % извлечения.

## Рекомендуемый порядок

### 1. Флотация Ni-Cu (лучший старт) — русский, таблицы

**ГИАБ:** «Исследование влияния ионов жёсткости воды на флотируемость медно-никелевых руд»  
- PDF: https://www.giab-online.ru/files/Data/2022/6/6-1_2022_263-278.pdf  
- Тема: флотация, извлечение Cu/Ni, pH, концентрация Ca²⁺  
- Почему: русский язык, лабораторные серии, графики кинетики — близко к `EXP-2024-028/031` (флотация pH)

### 2. Мончегорск / ЭПГ — максимально близко к Норникелю

**КиберЛенинка:** «Обоснование реагентных режимов флотации … медно-никелевой руды Мончегорского района»  
- Статья: https://cyberleninka.ru/article/n/obosnovanie-reagentnyh-rezhimov-flotatsii-soderzhaschey-epg-medno-nikelevoy-rudy-monchegorskogo-rayona  
- PDF: https://cyberleninka.ru/article/n/obosnovanie-reagentnyh-rezhimov-flotatsii-soderzhaschey-epg-medno-nikelevoy-rudy-monchegorskogo-rayona/pdf  
- Тема: ксантогенат, известковая среда, медно-никелевый концентрат, % извлечения

### 3. Флотация Cu-Ni — много таблиц (англ., open access)

**MDPI Minerals 2021:** Hydrodynamic Conditions on Selective Flotation of Cu-Ni Ore  
- DOI: https://doi.org/10.3390/min11030328  
- PDF (с сайта): https://www.mdpi.com/2075-163X/11/3/328/pdf  
- Цифры: Cu recovery **93.1%**, Ni **72.5%**, таблицы M1–M10

**MDPI Minerals 2018:** Pulp Density on Flotation Ni-Cu / Serpentine  
- DOI: https://doi.org/10.3390/min8080317  
- PDF: https://www.mdpi.com/2075-163X/8/8/317/pdf  
- Цифры: Ni 70.7→79.5%, Cu 82→85.4%, плотность пульпы 20–40 wt%

### 4. Обзор технологий (много таблиц в одном файле)

**Springer Open 2025:** Study on mineral processing of copper-nickel sulfide ore  
- PDF: https://jeas.springeropen.com/counter/pdf/10.1186/s44147-025-00596-x.pdf  
- Таблицы: world production, reagents, case studies (Ni recovery 92.13%, 81.61% и т.д.)

### 5. Электролиз Ni (вторая ветка демо-данных)

**MDPI Materials 2025:** Electrowinning of Nickel (pH 3–4.5, 60°C, efficiency 78–93%)  
- DOI: https://doi.org/10.3390/ma18245653  
- Близко к `электролиз 250°C` / EL-3 в seed (по смыслу — электролитическое извлечение Ni)

---

## Скачать и протестировать

```bash
./scripts/fetch_sample_pdfs.sh          # скачает 2–3 PDF в data/samples/
python scripts/test_multimodal_ingest.py --pdf data/samples/giab-ni-cu-flotation-water.pdf
```

Или вручную: сохраните PDF в `data/samples/` и загрузите через **База знаний** в UI.

## Что смотреть в результате

- `vision_provider`: gemini / fallback  
- `vision_images_used`: сколько картинок прошло анализ  
- `experiments[]`: material, mode (флотация/электролиз), property_value (%)  
- В extraction → `image_analysis` → текст таблиц от Gemini

## Демо-вопрос в UI

После ingest откройте **Демо** → **«Мультимодальный поиск»** (4 карточки 🖼, каждая — новый диалог):

1. *Графики жёсткости* — таблицы/графики ионов жёсткости.
2. *Кальций в пульпе* — 27,52 мг/дм³, стр. 10.
3. *Рисунки CLIP* — поиск по `scinikel_images` только в этом PDF.
4. *Кинетика флотации* — быстро-/медленнофлотируемые фракции.

Все запросы явно указывают `doc-giab-ni-cu-flotation-water` — без уточнения материала в графе.
