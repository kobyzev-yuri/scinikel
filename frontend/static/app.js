const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("input");
const demoQuestionsEl = document.getElementById("demo-questions");
const citationsEl = document.getElementById("citations");
const statsEl = document.getElementById("stats");
const indexStatusEl = document.getElementById("index-status");
const runtimeModeEl = document.getElementById("runtime-mode");
const graphEl = document.getElementById("graph");
const graphModalEl = document.getElementById("graph-modal");
const graphModalCanvasEl = document.getElementById("graph-modal-canvas");
const imageModalEl = document.getElementById("image-modal");
const imageModalImgEl = document.getElementById("image-modal-img");
const imageModalCaptionEl = document.getElementById("image-modal-caption");
const imageModalNoteEl = document.getElementById("image-modal-note");
const imageModalCounterEl = document.getElementById("image-modal-counter");
const imageModalPrevEl = document.getElementById("image-modal-prev");
const imageModalNextEl = document.getElementById("image-modal-next");

let lightboxSlides = [];
let lightboxIndex = 0;
let lastRenderedCitations = [];
const uploadStatusEl = document.getElementById("upload-status");
const ingestResultEl = document.getElementById("ingest-result");
const visionStatusEl = document.getElementById("vision-status");
const dialogInfoEl = document.getElementById("dialog-info");
const newDialogBtn = document.getElementById("new-dialog");
const conversationListEl = document.getElementById("conversation-list");
const graphDetailEl = document.getElementById("graph-detail");
const graphStatusEl = document.getElementById("graph-status");
const toggleOfflineBtn = document.getElementById("toggle-offline");

let cachedLlmConfig = null;
let suppressRuntimeAutoApply = false;

const SUBGRAPH_STORAGE_PREFIX = "scinikel:subgraph:";

const WORK_MODE_PRESETS = {
  lite: { work_mode: "lite", answer_mode: "rule", search_mode: "keyword" },
  local: { work_mode: "local", answer_mode: "llm", search_mode: "keyword", provider: "ollama" },
  full: { work_mode: "full", answer_mode: "llm", search_mode: "hybrid" },
};

function updateOfflineButton(answerMode) {
  if (!toggleOfflineBtn) return;
  const noLlm = answerMode === "rule";
  toggleOfflineBtn.textContent = noLlm ? "Без LLM: вкл" : "Без LLM: выкл";
  toggleOfflineBtn.classList.toggle("active", noLlm);
  toggleOfflineBtn.title = noLlm
    ? "LLM отключён — ответы только из графа. Нажмите, чтобы включить LLM."
    : "Отключить LLM — ответы только из графа (минимум ресурсов)";
}

function showRuntimeToast(message, isError = false) {
  if (!llmStatusMsgEl) return;
  llmStatusMsgEl.textContent = message;
  llmStatusMsgEl.className = `llm-status-msg ${isError ? "err" : "ok"}`;
}

function formatRuntimeModeLabel(status) {
  if (status.answer_mode === "rule" || !status.llm_enabled) {
    return "Без LLM · только граф";
  }
  const name = status.work_mode_name && status.work_mode_name !== "Своя настройка"
    ? status.work_mode_name
    : "LLM";
  const search =
    status.search_mode === "hybrid"
      ? " + гибрид BM25+e5"
      : status.search_backend === "qdrant+e5" || status.search_mode === "vector"
        ? " + семантический поиск"
        : "";
  return `${name} · ${status.llm_model}${search}`;
}

async function fetchLlmConfigCached() {
  const res = await fetch("/api/llm/config");
  if (!res.ok) throw new Error("config failed");
  cachedLlmConfig = await res.json();
  return cachedLlmConfig;
}

async function applyAnswerMode(answerMode) {
  const cfg = cachedLlmConfig || (await fetchLlmConfigCached());
  const body = {
    provider: cfg.provider,
    answer_mode: answerMode,
    search_mode: cfg.search_mode,
    openai_model: cfg.openai_model,
    ollama_model: cfg.ollama_model,
  };
  if (answerMode === "rule") {
    body.work_mode = "lite";
  } else if (cfg.work_mode === "lite") {
    body.work_mode = "local";
  }
  return applyRuntimeConfig(body);
}

async function applyWorkModePreset(workMode) {
  const preset = WORK_MODE_PRESETS[workMode];
  if (!preset) throw new Error(`Неизвестный профиль: ${workMode}`);
  const cfg = cachedLlmConfig || (await fetchLlmConfigCached());
  const body = { ...preset };
  if (workMode !== "lite" && cfg.ollama_model) body.ollama_model = cfg.ollama_model;
  if (workMode === "full" && cfg.provider === "proxyapi") body.provider = "proxyapi";
  if (cfg.openai_model) body.openai_model = cfg.openai_model;
  return applyRuntimeConfig(body);
}

async function applyRuntimeConfig(body) {
  const res = await fetch("/api/llm/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data;
  try {
    data = await res.json();
  } catch (_) {
    throw new Error(`Сервер вернул ${res.status} — перезапустите API`);
  }
  if (!res.ok) {
    const detail = data.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d) => d.msg).join("; ")
      : detail || `ошибка ${res.status}`;
    throw new Error(msg);
  }
  cachedLlmConfig = data;
  syncRuntimeForm(data);
  updateOfflineButton(data.answer_mode);
  await loadStatus();
  return data;
}

async function toggleOfflineMode() {
  if (!toggleOfflineBtn) return;
  toggleOfflineBtn.disabled = true;
  try {
    const cfg = await fetchLlmConfigCached();
    const disableLlm = cfg.answer_mode !== "rule";
    if (disableLlm) {
      await applyRuntimeConfig({ answer_mode: "rule", search_mode: "keyword" });
      showRuntimeToast("LLM отключён — ответы формируются только из графа");
    } else {
      await applyRuntimeConfig({
        answer_mode: "llm",
        search_mode: cfg.search_mode || "keyword",
        provider: cfg.provider || "ollama",
        ollama_model: cfg.ollama_model,
        openai_model: cfg.openai_model,
      });
      showRuntimeToast("LLM снова включён");
    }
  } catch (err) {
    console.error("toggleOfflineMode:", err);
    showRuntimeToast(`Не удалось переключить: ${err.message}`, true);
  } finally {
    toggleOfflineBtn.disabled = false;
  }
}

function parseMessageMeta(meta = "") {
  const [kind, center] = (meta || "").split(":", 2);
  return { kind: kind || meta, center: center?.startsWith("EXP-") ? center : null };
}

function parseStoredMeta(meta = "") {
  if (!meta) return { kind: "", center: null, citations: null };
  const raw = String(meta).trim();
  if (raw.startsWith("{")) {
    try {
      const data = JSON.parse(raw);
      if (data && typeof data === "object") {
        return {
          kind: data.kind || "",
          center: data.exp_id || null,
          citations: Array.isArray(data.citations) ? data.citations : null,
        };
      }
    } catch (_) {
      /* legacy string below */
    }
  }
  const { kind, center } = parseMessageMeta(raw);
  return { kind, center, citations: null };
}

function formatMessageMeta(meta = "") {
  const { kind } = parseStoredMeta(meta);
  if (kind === "llm") return "ответ сформулирован LLM";
  if (kind === "graph") return "ответ из графа (без LLM)";
  return "";
}

function saveSubgraphForConversation(convId, subgraph) {
  if (!convId || !subgraph?.nodes?.length) return;
  try {
    localStorage.setItem(`${SUBGRAPH_STORAGE_PREFIX}${convId}`, JSON.stringify(subgraph));
  } catch (_) {
    /* quota */
  }
}

function loadStoredSubgraph(convId) {
  if (!convId) return null;
  try {
    const raw = localStorage.getItem(`${SUBGRAPH_STORAGE_PREFIX}${convId}`);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

async function fetchSubgraphForExperiment(expId) {
  const res = await fetch(`/api/graph/subgraph/${encodeURIComponent(expId)}?depth=1`);
  if (!res.ok) return null;
  return res.json();
}

async function restoreGraphForConversation(convId, messages) {
  const stored = loadStoredSubgraph(convId);
  if (stored?.nodes?.length) {
    renderGraph(stored);
    return;
  }

  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role !== "assistant") continue;

    const { center } = parseStoredMeta(msg.meta);
    const expId = center || (msg.content.match(/EXP-\d{4}-\d{3}/) || [])[0];
    if (!expId) continue;

    const subgraph = await fetchSubgraphForExperiment(expId);
    if (subgraph?.nodes?.length) {
      renderGraph(subgraph);
      saveSubgraphForConversation(convId, subgraph);
      return;
    }
  }

  renderGraph(null);
}

function setGraphStatus(text) {
  if (graphStatusEl) graphStatusEl.textContent = text;
}

/** История диалога для LLM (без приветствия) */
const chatHistory = [];
const MAX_HISTORY_MESSAGES = 20;
let currentConversationId = null;

let network = null;
let modalNetwork = null;
let lastSubgraph = null;

const TYPE_COLORS = {
  Experiment: "#3d9a8b",
  Material: "#6b8cce",
  Mode: "#c9a227",
  Property: "#c76b6b",
  Team: "#9b7ed9",
  Equipment: "#7ed99b",
  Conclusion: "#e8eef5",
  Document: "#8b9cb3",
  Topic: "#8b9cb3",
};

const GRAPH_OPTIONS = {
  nodes: {
    shape: "box",
    margin: 12,
    borderWidth: 2,
    widthConstraint: { minimum: 100, maximum: 220 },
    font: { multi: true },
  },
  edges: {
    width: 1.5,
    smooth: { type: "dynamic" },
    font: { strokeWidth: 0, background: "rgba(15, 20, 25, 0.85)" },
  },
  physics: {
    enabled: true,
    stabilization: {
      enabled: true,
      iterations: 120,
      updateInterval: 20,
      fit: true,
    },
    barnesHut: {
      gravitationalConstant: -3500,
      centralGravity: 0.35,
      springLength: 130,
      springConstant: 0.06,
      damping: 0.55,
      avoidOverlap: 0.4,
    },
  },
  interaction: {
    hover: true,
    zoomView: true,
    dragView: true,
    tooltipDelay: 80,
    navigationButtons: false,
    keyboard: { enabled: true },
  },
};

function formatNodeLabel(text) {
  const label = (text || "").trim();
  if (label.length <= 30) return label;
  const breakAt = label.lastIndexOf(" ", 28);
  if (breakAt > 10) {
    return `${label.slice(0, breakAt)}\n${label.slice(breakAt + 1)}`;
  }
  return `${label.slice(0, 28)}…`;
}

function buildGraphData(subgraph) {
  const nodes = new vis.DataSet(
    subgraph.nodes.map((n) => {
      const fullLabel = n.label || n.id;
      const isLight = n.type === "Conclusion";
      return {
        id: n.id,
        label: formatNodeLabel(fullLabel),
        title: `${n.type}: ${fullLabel}`,
        color: {
          background: TYPE_COLORS[n.type] || "#888",
          border: isLight ? "#8b9cb3" : "#ffffff55",
          highlight: { background: TYPE_COLORS[n.type] || "#aaa", border: "#fff" },
        },
        font: {
          color: isLight ? "#1a2332" : "#fff",
          size: 15,
          face: "Segoe UI, system-ui, sans-serif",
        },
        size: n.type === "Experiment" ? 30 : 24,
      };
    })
  );

  const seenEdgeIds = new Set();
  const edgeRows = [];
  for (const e of subgraph.edges || []) {
    const edgeId = e.id || `${e.source}-${e.target}-${e.label || ""}`;
    if (seenEdgeIds.has(edgeId)) continue;
    seenEdgeIds.add(edgeId);
    edgeRows.push({
      id: edgeId,
      from: e.source,
      to: e.target,
      label: (e.label || "").replace(/_/g, " "),
      arrows: "to",
      font: { size: 12, align: "middle", color: "#c5d0de" },
      color: { color: "#4a5d75", highlight: "#8b9cb3" },
    });
  }

  return { nodes, edges: new vis.DataSet(edgeRows) };
}

function fitGraph(net, padding = 40, animate = true) {
  if (!net) return;
  net.fit({
    animation: animate
      ? { duration: 280, easingFunction: "easeInOutQuad" }
      : false,
    padding,
  });
}

/** Остановить физику и вписать граф — иначе узлы «улетают» за край */
function freezeAndFit(net, padding = 40, onDone) {
  if (!net) return;
  net.setOptions({ physics: { enabled: false } });
  fitGraph(net, padding, false);
  if (typeof onDone === "function") {
    requestAnimationFrame(() => onDone());
  }
}

function mountGraph(container, subgraph, currentNetwork, onReady) {
  if (!subgraph?.nodes?.length) {
    container.innerHTML =
      "<p class='graph-placeholder'>Задайте вопрос — здесь появится фрагмент графа</p>";
    if (currentNetwork) currentNetwork.destroy();
    return null;
  }

  container.innerHTML = "";
  const data = buildGraphData(subgraph);
  if (currentNetwork) currentNetwork.destroy();
  const net = new vis.Network(container, data, GRAPH_OPTIONS);

  let settled = false;
  const settle = () => {
    if (settled) return;
    settled = true;
    const pad = container.classList.contains("graph-canvas--modal") ? 50 : 40;
    freezeAndFit(net, pad, onReady);
  };

  net.once("stabilizationIterationsDone", settle);
  net.on("doubleClick", () => fitGraph(net));

  // Малый граф или быстрая стабилизация — подстраховка
  setTimeout(settle, 600);

  return net;
}

function zoomGraph(net, factor) {
  if (!net) return;
  const scale = net.getScale() * factor;
  net.moveTo({ scale: Math.min(2.5, Math.max(0.15, scale)) });
}

function openGraphModal() {
  if (!lastSubgraph?.nodes?.length) return;
  graphModalEl.hidden = false;
  document.body.style.overflow = "hidden";
  modalNetwork = mountGraph(graphModalCanvasEl, lastSubgraph, modalNetwork, () => {
    fitGraph(modalNetwork, 50);
  });
}

function closeGraphModal() {
  graphModalEl.hidden = true;
  document.body.style.overflow = "";
  if (modalNetwork) {
    modalNetwork.destroy();
    modalNetwork = null;
  }
}

function slidesFromCitations(citations) {
  return imageCitationsFrom(citations).map((c) => ({
    url: normalizeMediaUrl(c.image_url),
    caption: `${c.title || c.id || "Рисунок"}${c.page ? ` · стр. ${c.page}` : ""}`,
    note: c.librarian_annotation || c.snippet || "",
  }));
}

function showLightboxSlide() {
  if (!lightboxSlides.length || !imageModalImgEl) return;
  const slide = lightboxSlides[lightboxIndex];
  imageModalImgEl.src = slide.url;
  imageModalImgEl.alt = slide.caption || "Рисунок из документа";
  if (imageModalCaptionEl) imageModalCaptionEl.textContent = slide.caption || "Рисунок из документа";
  if (imageModalNoteEl) {
    imageModalNoteEl.textContent = slide.note || "";
    imageModalNoteEl.hidden = !slide.note;
  }
  const multi = lightboxSlides.length > 1;
  if (imageModalPrevEl) imageModalPrevEl.hidden = !multi;
  if (imageModalNextEl) imageModalNextEl.hidden = !multi;
  if (imageModalCounterEl) {
    imageModalCounterEl.hidden = !multi;
    imageModalCounterEl.textContent = multi ? `${lightboxIndex + 1} / ${lightboxSlides.length}` : "";
  }
}

function openImageLightbox(url, caption = "", note = "", slides = null, startIndex = 0) {
  if (!imageModalEl || !imageModalImgEl) return;
  if (slides?.length) {
    lightboxSlides = slides;
    const idx = slides.findIndex((s) => s.url === normalizeMediaUrl(url));
    lightboxIndex = idx >= 0 ? idx : Math.max(0, Math.min(startIndex, slides.length - 1));
  } else {
    const mediaUrl = normalizeMediaUrl(url);
    if (!mediaUrl.startsWith("/api/media/images/")) return;
    lightboxSlides = [{ url: mediaUrl, caption, note }];
    lightboxIndex = 0;
  }
  showLightboxSlide();
  imageModalEl.hidden = false;
  document.body.style.overflow = "hidden";
}

function stepLightbox(delta) {
  if (lightboxSlides.length < 2) return;
  lightboxIndex = (lightboxIndex + delta + lightboxSlides.length) % lightboxSlides.length;
  showLightboxSlide();
}

function closeImageLightbox() {
  if (!imageModalEl) return;
  imageModalEl.hidden = true;
  document.body.style.overflow = "";
  lightboxSlides = [];
  lightboxIndex = 0;
  if (imageModalImgEl) imageModalImgEl.removeAttribute("src");
}

function imageCitationsFrom(citations) {
  return (citations || []).filter((c) => c.type === "image" && normalizeMediaUrl(c.image_url));
}

function mediaCaption(c) {
  const page = c.page ? ` · стр. ${c.page}` : "";
  return `${c.title || c.id || "Рисунок"}${page}`;
}

function buildSourceImageBlock(
  c,
  slides,
  index,
  { showAnnotation = true, showKeyPoints = true, showCaption = true } = {}
) {
  const url = normalizeMediaUrl(c.image_url);
  const block = document.createElement("div");
  block.className = "source-image-block";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "source-media-btn";
  btn.dataset.mediaUrl = url;
  const img = document.createElement("img");
  img.className = "source-media-thumb";
  img.src = url;
  img.alt = c.title || c.id || "рисунок";
  img.loading = "lazy";
  const cap = document.createElement("span");
  cap.className = "source-media-cap";
  cap.textContent = mediaCaption(c);
  btn.appendChild(img);
  if (showCaption) {
    btn.appendChild(cap);
  }
  const note = c.librarian_annotation || c.snippet || "";
  const caption = cap.textContent || mediaCaption(c);
  btn.addEventListener("click", () => openImageLightbox(url, caption, note, slides, index));
  block.appendChild(btn);

  const ann = (c.librarian_annotation || c.snippet || "").trim();
  if (showAnnotation && ann && ann !== (c.title || "")) {
    const annEl = document.createElement("p");
    annEl.className = "source-image-annotation";
    annEl.textContent = ann;
    block.appendChild(annEl);
  }

  if (showKeyPoints && c.key_points?.length) {
    const ul = document.createElement("ul");
    ul.className = "source-keypoints";
    for (const kp of c.key_points) {
      const li = document.createElement("li");
      li.textContent = kp;
      ul.appendChild(li);
    }
    block.appendChild(ul);
  }

  return block;
}

function buildMediaCard(c, slides, index) {
  const card = document.createElement("article");
  card.className = "source-card source-card--image";
  card.appendChild(buildSourceImageBlock(c, slides, index, { showAnnotation: false, showKeyPoints: false }));
  return card;
}

function wireMediaInElement(root, slides = null) {
  if (!root) return;
  const slideList = slides || slidesFromCitations(lastRenderedCitations);
  root.querySelectorAll("[data-media-url]").forEach((el) => {
    if (el.dataset.mediaWired) return;
    el.dataset.mediaWired = "1";
    el.addEventListener("click", (e) => {
      e.preventDefault();
      const url = el.dataset.mediaUrl;
      const caption = el.dataset.mediaCaption || el.querySelector(".source-media-cap, .msg-media-cap")?.textContent || "";
      const note = el.dataset.mediaNote || "";
      openImageLightbox(url, caption, note, slideList.length ? slideList : null);
    });
  });
}

function appendSourcesHint(container, citations) {
  const images = imageCitationsFrom(citations);
  const hasDocs = (citations || []).some((c) => c.type === "document");
  if (!images.length && !hasDocs) return;
  const hint = document.createElement("div");
  hint.className = "msg-sources-hint";
  const text = document.createElement("p");
  text.className = "msg-sources-hint-text";
  text.textContent =
    images.length && hasDocs
      ? "Граф, текстовые фрагменты и карточки источников — на вкладке «Главная»."
      : images.length
        ? "Полные карточки рисунков и граф — на вкладке «Главная»."
        : "Текстовые источники и граф — на вкладке «Главная».";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn-secondary msg-sources-hint-btn";
  btn.textContent = "Открыть «Главная»";
  btn.addEventListener("click", () => switchTab("main"));
  hint.appendChild(text);
  hint.appendChild(btn);
  container.appendChild(hint);
}

function appendMediaGallery(container, citations) {
  const images = imageCitationsFrom(citations);
  if (!images.length) return;
  const slides = slidesFromCitations(citations);
  const gallery = document.createElement("div");
  gallery.className = "source-media-gallery msg-media-gallery";
  const title = document.createElement("p");
  title.className = "source-section-title msg-media-gallery-title";
  title.textContent = "Рисунки из документа";
  gallery.appendChild(title);
  const grid = document.createElement("div");
  grid.className = "source-media-grid msg-media-gallery-grid";
  images.forEach((c, index) => {
    grid.appendChild(buildMediaCard(c, slides, index));
  });
  gallery.appendChild(grid);
  container.appendChild(gallery);
}

/** Стандартные вопросы для демо — привязаны к data/seed */
const DEMO_QUESTIONS = [
  {
    title: "Эксперименты",
    hint: "материал × режим → свойство",
    items: [
      {
        label: "флотация Ni pH 10.5",
        q: "Что делали по Ni-Cu концентрату при флотации pH 10.5 и какой эффект на извлечение Ni?",
      },
      {
        label: "электролиз 250°C",
        q: "Что известно про электролиз Ni-Cu сплава при 250°C?",
      },
      {
        label: "термообработка 600°C",
        q: "Как термообработка 600°C влияет на прочность Ni-Cu сплава?",
      },
      {
        label: "обжиг концентрата",
        q: "Что показал обжиг Ni-Cu концентрата при 800°C по зольности?",
      },
    ],
  },
  {
    title: "Кто и на чём",
    hint: "команды, лаборатории, установки",
    items: [
      {
        label: "электролиз — кто?",
        q: "Кто занимался электролизом и на какой установке?",
      },
      {
        label: "гидромет — лаборатория",
        q: "Какая лаборатория проводила выщелачивание Ni-Cu концентрата?",
      },
      {
        label: "флотация — установка",
        q: "На какой установке проводили флотацию Ni-Cu концентрата?",
      },
    ],
  },
  {
    title: "Гидрометаллургия",
    hint: "выщелачивание, автоклав",
    items: [
      {
        label: "кислотное выщелачивание",
        q: "Что делали по выщелачиванию Ni-Cu концентрата?",
      },
      {
        label: "автоклав vs кислота",
        q: "Сравни автоклавное и кислотное выщелачивание Ni-Cu концентрата — какое извлечение выше?",
      },
    ],
  },
  {
    title: "Пробелы в данных",
    hint: "gap-analysis по графу",
    items: [
      {
        label: "все пробелы",
        q: "Какие комбинации материал×режим ещё не исследованы?",
        gaps: true,
      },
      {
        label: "пробелы по шламу",
        q: "Что не исследовали по вольфрамовому шламу?",
        gaps: true,
      },
    ],
  },
  {
    title: "Уточнение",
    hint: "неоднозначный запрос → выбор варианта",
    items: [
      {
        label: "⚡ электролиз (неоднозначно)",
        q: "Что делали по электролизу?",
        clarify: true,
      },
      {
        label: "флотация (неоднозначно)",
        q: "Что делали по флотации?",
        clarify: true,
      },
    ],
  },
  {
    title: "Мультимодальный поиск",
    hint: "только doc-giab-ni-cu-flotation-water · новый диалог на каждый клик",
    items: [
      {
        label: "🖼 графики жёсткости",
        q: "doc-giab-ni-cu-flotation-water: какие графики и таблицы показывают влияние ионов жёсткости воды на флотацию медно-никелевых руд?",
        multimodal: true,
        freshDialog: true,
      },
      {
        label: "кальций в пульпе",
        q: "doc-giab-ni-cu-flotation-water: при какой концентрации кальция в пульпе (мг/дм³) лучшее извлечение никеля? Укажи страницу и фрагмент.",
        multimodal: true,
        freshDialog: true,
      },
      {
        label: "рисунки CLIP",
        q: "doc-giab-ni-cu-flotation-water: найди рисунки с графиками извлечения меди и никеля при флотации.",
        multimodal: true,
        freshDialog: true,
      },
      {
        label: "кинетика флотации",
        q: "doc-giab-ni-cu-flotation-water: что на рисунках по кинетике флотации быстро- и медленнофлотируемых фракций Cu и Ni?",
        multimodal: true,
        freshDialog: true,
      },
    ],
  },
  {
    title: "Другие материалы",
    hint: "медь, вольфрам, коррозия",
    items: [
      {
        label: "медный концентрат",
        q: "Что делали с медным концентратом при флотации pH 10.5?",
      },
      {
        label: "вольфрамовый шлам",
        q: "Какой результат дала магнитная сепарация вольфрамового шлама?",
      },
      {
        label: "коррозия Ni-Cu",
        q: "Какова коррозионная стойкость Ni-Cu сплава в морской среде?",
      },
    ],
  },
];

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function updateDialogInfo(turn = 0) {
  if (!dialogInfoEl) return;
  const turns = turn || Math.ceil(chatHistory.length / 2);
  dialogInfoEl.textContent =
    turns > 0
      ? `Диалог · реплика ${turns} · можно задавать уточнения`
      : "Диалог · задайте первый вопрос";
}

function resetDialog() {
  chatHistory.length = 0;
  lastSubgraph = null;
  closeGraphModal();
  createConversation(true);
}

async function createConversation(showGreeting = true) {
  try {
    const res = await fetch("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Новый диалог" }),
    });
    if (!res.ok) throw new Error("create failed");
    const data = await res.json();
    currentConversationId = data.id;
    messagesEl.innerHTML = "";
    renderCitations([]);
    renderGraph(null);
    updateDialogInfo(0);
    if (showGreeting) showWelcome();
    input.focus();
    await loadConversations();
  } catch (err) {
    console.error("createConversation:", err);
  }
}

async function loadConversations() {
  if (!conversationListEl) return;
  try {
    const res = await fetch("/api/conversations");
    if (!res.ok) return;
    const items = await res.json();
    conversationListEl.innerHTML = "";
    for (const item of items) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `conversation-item${item.id === currentConversationId ? " active" : ""}`;
      btn.dataset.id = item.id;
      btn.textContent = item.title || "Без названия";
      btn.title = new Date(item.updated_at).toLocaleString("ru-RU");
      li.appendChild(btn);
      conversationListEl.appendChild(li);
    }
  } catch (err) {
    console.error("loadConversations:", err);
  }
}

async function loadConversation(convId) {
  try {
    const res = await fetch(`/api/conversations/${convId}`);
    if (!res.ok) throw new Error("not found");
    const data = await res.json();
    currentConversationId = data.id;
    chatHistory.length = 0;
    messagesEl.innerHTML = "";
    let lastCitations = null;
    for (const msg of data.messages) {
      const stored = parseStoredMeta(msg.meta);
      const citations = msg.role === "assistant" ? stored.citations : null;
      if (citations?.length) lastCitations = citations;
      appendMessage(msg.role, msg.content, formatMessageMeta(msg.meta), citations);
      chatHistory.push({ role: msg.role, content: msg.content });
    }
    updateDialogInfo(Math.ceil(chatHistory.length / 2));
    if (lastCitations?.length) {
      renderCitations(lastCitations);
    } else {
      renderCitations([]);
    }
    await restoreGraphForConversation(data.id, data.messages);
    await loadConversations();
  } catch (err) {
    console.error("loadConversation:", err);
  }
}

async function loadGraphDetail() {
  if (!graphDetailEl) return;
  try {
    const res = await fetch("/api/graph/stats");
    const stats = await res.json();
    graphDetailEl.textContent = JSON.stringify(stats, null, 2);
  } catch (_) {
    graphDetailEl.textContent = "Не удалось загрузить статистику";
  }
}

function switchTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.hidden = panel.id !== `tab-${tabName}`;
  });
  if (tabName === "knowledge") {
    loadGraphDetail();
    loadVisionStatus();
  }
  if (tabName === "llm") loadLlmConfig();
}

const llmActiveEl = document.getElementById("llm-active");
const llmOpenaiModelEl = document.getElementById("llm-openai-model");
const llmOllamaModelEl = document.getElementById("llm-ollama-model");
const llmProxyapiFields = document.getElementById("llm-proxyapi-fields");
const llmOllamaFields = document.getElementById("llm-ollama-fields");
const llmStatusMsgEl = document.getElementById("llm-status-msg");
const workModeCardsEl = document.getElementById("work-mode-cards");
const runtimeResourcesEl = document.getElementById("runtime-resources");
const runtimeAdvancedEl = document.getElementById("runtime-advanced");

const WORK_MODE_ICONS = { lite: "⚡", local: "🖥", full: "🔬" };

function getSelectedLlmProvider() {
  const checked = document.querySelector('input[name="llm-provider"]:checked');
  return checked?.value || "proxyapi";
}

function getSelectedAnswerMode() {
  const checked = document.querySelector('input[name="llm-answer-mode"]:checked');
  return checked?.value || "llm";
}

function getSelectedSearchMode() {
  const checked = document.querySelector('input[name="search-mode"]:checked');
  return checked?.value || "keyword";
}

function resourceTags(resources = {}) {
  const tags = [];
  if (resources.ram) tags.push({ text: `RAM: ${resources.ram}`, cls: "ok" });
  if (resources.llm === false) tags.push({ text: "без LLM", cls: "ok" });
  if (resources.llm === true) tags.push({ text: "LLM", cls: "warn" });
  if (resources.vector === false) tags.push({ text: "без Qdrant", cls: "ok" });
  if (resources.vector === true) tags.push({ text: "Qdrant+e5", cls: "warn" });
  if (resources.network === false) tags.push({ text: "без сети", cls: "ok" });
  if (resources.network === true) tags.push({ text: "сеть", cls: "warn" });
  if (resources.docker === true) tags.push({ text: "Docker", cls: "warn" });
  return tags;
}

function renderWorkModeCards(modes, activeId) {
  if (!workModeCardsEl) return;
  workModeCardsEl.innerHTML = "";
  for (const mode of modes.filter((m) => m.id !== "custom")) {
    const label = document.createElement("label");
    label.className = `work-mode-card${mode.id === activeId ? " selected" : ""}`;
    const tags = resourceTags(mode.resources).map(
      (t) => `<span class="work-mode-tag ${t.cls}">${t.text}</span>`
    ).join("");
    label.innerHTML = `
      <input type="radio" name="work-mode" value="${mode.id}" ${mode.id === activeId ? "checked" : ""} />
      <span class="work-mode-title">${WORK_MODE_ICONS[mode.id] || "⚙"} ${mode.name}</span>
      <span class="work-mode-hint">${mode.hint}</span>
      <div class="work-mode-tags">${tags}</div>
    `;
    label.addEventListener("click", async () => {
      document.querySelectorAll(".work-mode-card").forEach((c) => c.classList.remove("selected"));
      label.classList.add("selected");
      label.querySelector("input").checked = true;
      if (llmStatusMsgEl) {
        llmStatusMsgEl.textContent = "Применение профиля…";
        llmStatusMsgEl.className = "llm-status-msg";
      }
      try {
        const data = await applyWorkModePreset(mode.id);
        if (llmStatusMsgEl) {
          const noLlm = data.answer_mode === "rule";
          llmStatusMsgEl.textContent = noLlm
            ? `Профиль «${mode.name}»: LLM отключён, ответы из графа.`
            : `Профиль «${mode.name}» применён.`;
          llmStatusMsgEl.className = "llm-status-msg ok";
        }
      } catch (err) {
        if (llmStatusMsgEl) {
          llmStatusMsgEl.textContent = `Ошибка: ${err.message}`;
          llmStatusMsgEl.className = "llm-status-msg err";
        }
      }
    });
    workModeCardsEl.appendChild(label);
  }
}

function renderRuntimeResources(cfg) {
  if (!runtimeResourcesEl) return;
  const items = [];
  const preset = cfg.work_modes?.find((m) => m.id === cfg.work_mode);
  if (preset) items.push(`Профиль: ${preset.name}`);
  items.push(`Ответы: ${cfg.answer_mode === "rule" ? "граф (rule-based)" : cfg.active_label}`);
  items.push(
    `Поиск: ${
      cfg.search_mode === "hybrid"
        ? "гибрид RRF"
        : cfg.search_mode === "vector"
          ? "семантический"
          : "ключевые слова"
    }`
  );
  const r = cfg.resources || {};
  if (r.ram) items.push(`Память: ${r.ram}`);
  runtimeResourcesEl.innerHTML = items.map((t) => `<li>${t}</li>`).join("");
}

function syncRuntimeForm(cfg) {
  suppressRuntimeAutoApply = true;
  const modeRadio = document.querySelector(
    `input[name="llm-answer-mode"][value="${cfg.answer_mode || "llm"}"]`
  );
  if (modeRadio) modeRadio.checked = true;
  const searchRadio = document.querySelector(
    `input[name="search-mode"][value="${cfg.search_mode || "keyword"}"]`
  );
  if (searchRadio) searchRadio.checked = true;
  const providerRadio = document.querySelector(`input[name="llm-provider"][value="${cfg.provider}"]`);
  if (providerRadio) providerRadio.checked = true;
  if (llmOpenaiModelEl) llmOpenaiModelEl.value = cfg.openai_model || "";
  fillOllamaModelSelect(cfg.ollama_models, cfg.ollama_model);
  updateLlmFieldsVisibility();
  if (llmActiveEl) {
    const preset = cfg.work_modes?.find((m) => m.id === cfg.work_mode);
    llmActiveEl.textContent = preset
      ? `${preset.name} · ${cfg.active_label}`
      : `Сейчас: ${cfg.active_label}`;
  }
  renderWorkModeCards(cfg.work_modes || [], cfg.work_mode);
  renderRuntimeResources(cfg);
  if (cfg.work_mode === "custom" && runtimeAdvancedEl) runtimeAdvancedEl.open = true;
  suppressRuntimeAutoApply = false;
}

function updateLlmFieldsVisibility() {
  const ruleOnly = getSelectedAnswerMode() === "rule";
  const provider = getSelectedLlmProvider();
  const grid = document.querySelector(".llm-provider-grid");
  if (grid) grid.classList.toggle("disabled", ruleOnly);
  if (llmProxyapiFields) llmProxyapiFields.hidden = ruleOnly || provider !== "proxyapi";
  if (llmOllamaFields) llmOllamaFields.hidden = ruleOnly || provider !== "ollama";
  document.querySelectorAll('input[name="search-mode"]').forEach((el) => {
    el.closest(".llm-mode-option")?.classList.toggle("disabled", ruleOnly);
  });
}

function fillOllamaModelSelect(models, selected) {
  if (!llmOllamaModelEl) return;
  llmOllamaModelEl.innerHTML = "";
  if (!models?.length) {
    const opt = document.createElement("option");
    opt.value = selected || "";
    opt.textContent = selected || "Ollama недоступна — введите имя в config.env";
    llmOllamaModelEl.appendChild(opt);
    return;
  }
  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m.name;
    opt.textContent = m.size ? `${m.name} (${m.size})` : m.name;
    llmOllamaModelEl.appendChild(opt);
  }
  if (selected) llmOllamaModelEl.value = selected;
}

async function loadLlmConfig() {
  if (!llmActiveEl) return;
  try {
    const res = await fetch("/api/llm/config");
    if (!res.ok) throw new Error("config failed");
    const cfg = await res.json();
    cachedLlmConfig = cfg;
    syncRuntimeForm(cfg);
    updateOfflineButton(cfg.answer_mode || "llm");
    if (llmStatusMsgEl && !llmStatusMsgEl.classList.contains("ok")) {
      if (cfg.answer_mode === "rule") {
        llmStatusMsgEl.textContent = "Экономный режим: ответы из графа, без LLM и эмбеддингов.";
      } else if (cfg.search_mode === "keyword") {
        llmStatusMsgEl.textContent = "Поиск по ключевым словам — Qdrant не используется.";
      } else {
        llmStatusMsgEl.textContent = cfg.has_api_key
          ? "Полный режим: LLM + семантический поиск."
          : "Для облачного LLM задайте OPENAI_API_KEY в config.env";
      }
      llmStatusMsgEl.className = "llm-status-msg";
    }
  } catch (err) {
    llmActiveEl.textContent = "Не удалось загрузить настройки";
    console.error("loadLlmConfig:", err);
  }
}

async function saveLlmConfig() {
  if (!llmStatusMsgEl) return;
  const provider = getSelectedLlmProvider();
  const answer_mode = getSelectedAnswerMode();
  const search_mode = getSelectedSearchMode();
  const body = {
    provider,
    answer_mode,
    search_mode,
    work_mode: "custom",
  };
  if (provider === "proxyapi" && llmOpenaiModelEl?.value.trim()) {
    body.openai_model = llmOpenaiModelEl.value.trim();
  }
  if (provider === "ollama" && llmOllamaModelEl?.value) {
    body.ollama_model = llmOllamaModelEl.value;
  }
  llmStatusMsgEl.textContent = "Сохранение…";
  llmStatusMsgEl.className = "llm-status-msg";
  try {
    const data = await applyRuntimeConfig(body);
    llmStatusMsgEl.textContent =
      data.work_mode === "lite"
        ? "Экономный режим: только граф, минимум ресурсов."
        : `Настройки применены. Поиск: ${data.search_backend || data.search_mode}.`;
    llmStatusMsgEl.className = "llm-status-msg ok";
  } catch (err) {
    llmStatusMsgEl.textContent = `Ошибка: ${err.message}`;
    llmStatusMsgEl.className = "llm-status-msg err";
  }
}

async function refreshOfflineUiFromServer() {
  try {
    const cfg = await fetchLlmConfigCached();
    updateOfflineButton(cfg.answer_mode || "llm");
  } catch (_) {
    /* ignore */
  }
}

async function probeLlmConfig() {
  if (!llmStatusMsgEl) return;
  const provider = getSelectedLlmProvider();
  llmStatusMsgEl.textContent = "Проверка…";
  llmStatusMsgEl.className = "llm-status-msg";
  try {
    const res = await fetch(`/api/llm/probe?provider=${encodeURIComponent(provider)}`);
    const data = await res.json();
    if (data.ok) {
      const extra =
        provider === "ollama" && data.models?.length
          ? ` Модели: ${data.models.join(", ")}`
          : data.note
            ? ` ${data.note}`
            : "";
      llmStatusMsgEl.textContent = `Соединение OK (${provider})${extra}`;
      llmStatusMsgEl.className = "llm-status-msg ok";
      if (provider === "ollama" && data.models?.length) {
        fillOllamaModelSelect(
          data.models.map((name) => ({ name, size: "" })),
          llmOllamaModelEl?.value
        );
      }
    } else {
      llmStatusMsgEl.textContent = `Ошибка (${provider}): ${data.error || "неизвестно"}`;
      llmStatusMsgEl.className = "llm-status-msg err";
    }
  } catch (err) {
    llmStatusMsgEl.textContent = `Ошибка: ${err.message}`;
    llmStatusMsgEl.className = "llm-status-msg err";
  }
}

function isTableRow(line) {
  const t = line.trim();
  return t.startsWith("|") && t.includes("|");
}

function isTableSeparator(line) {
  return /^\|?[\s\-:|\u2014]+\|?$/.test(line.trim());
}

function parseTableCells(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

function renderTableHtml(rows) {
  if (!rows.length) return "";
  const [header, ...body] = rows;
  let html = '<div class="table-block"><table class="data-table"><thead><tr>';
  for (const cell of header) {
    html += `<th>${cell}</th>`;
  }
  html += "</tr></thead><tbody>";
  for (const row of body) {
    html += "<tr>";
    for (const cell of row) {
      const cls = /%$|^\d+([.,]\d+)?$/.test(cell.replace(/\s/g, "")) ? ' class="num"' : "";
      html += `<td${cls}>${cell}</td>`;
    }
    html += "</tr>";
  }
  html += "</tbody></table></div>";
  return html;
}

function normalizeMediaUrl(href) {
  if (!href) return "";
  const raw = String(href).trim();
  if (raw.includes("<")) {
    const id = raw.match(/(doc-giab-[\w-]+-p\d+-i\d+)/i);
    return id ? `/api/media/images/${id[1]}` : "";
  }
  if (raw.startsWith("/api/media/images/")) {
    const tail = raw.slice("/api/media/images/".length).replace(/\.(jpe?g|png|gif|webp)$/i, "");
    const id = tail.match(/^(doc-giab-[\w-]+-p\d+-i\d+)/i);
    return id ? `/api/media/images/${id[1]}` : raw.replace(/\.(jpe?g|png|gif|webp)$/i, "");
  }
  const fromPath = raw.match(/(doc-giab-[\w-]+-p\d+-i\d+)(?:\.(jpe?g|png|gif|webp))?$/i);
  if (fromPath) return `/api/media/images/${fromPath[1]}`;
  const bare = raw.match(/^(doc-giab-[\w-]+-p\d+-i\d+)\.(jpe?g|png|gif|webp)$/i);
  if (bare) return `/api/media/images/${bare[1]}`;
  if (/^doc-giab-[\w-]+-p\d+-i\d+$/i.test(raw)) return `/api/media/images/${raw}`;
  return raw;
}

function autolinkDocGiabImages(text) {
  return text.replace(
    /\b(doc-giab-[\w-]+-p\d+-i\d+)(?:\.(jpe?g|png|gif|webp))?\b/gi,
    (match, id, _ext, offset, whole) => {
      if (offset > 0 && whole[offset - 1] === "/") return match;
      const open = whole.lastIndexOf("(", offset);
      const close = whole.lastIndexOf(")", offset);
      if (open > close) return match;
      return `[${match}](/api/media/images/${id})`;
    }
  );
}

function renderTextBlock(text) {
  let html = escapeHtml(autolinkDocGiabImages(text));
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_all, label, href) => {
    const url = normalizeMediaUrl(href);
    if (url.startsWith("/api/media/images/")) {
      const cap = label.replace(/^(открыть\s+)?рисунок$/i, "Рисунок").trim() || "Рисунок";
      return (
        `<button type="button" class="source-media-btn msg-media-inline" data-media-url="${url}" data-media-caption="${cap}">` +
        `<img class="source-media-thumb msg-media-thumb" src="${url}" alt="${cap}" loading="lazy">` +
        `<span class="source-media-cap msg-media-cap">${cap}</span></button>`
      );
    }
    if (url.startsWith("/api/")) {
      return `<a class="msg-link" href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    }
    return `[${label}](${href})`;
  });
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/^### (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^## (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^• (.+)$/gm, "<li>$1</li>");
  if (html.includes("<li>")) {
    html = html.replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>");
  }
  html = html.replace(/\n\n/g, "</p><p>");
  html = html.replace(/\n/g, "<br>");
  return `<div class="msg-text"><p>${html}</p></div>`;
}

function renderMarkdown(text) {
  const lines = text.split("\n");
  const parts = [];
  let textBuf = [];
  let tableBuf = [];

  const flushText = () => {
    if (textBuf.length) {
      parts.push(renderTextBlock(textBuf.join("\n").trim()));
      textBuf = [];
    }
  };

  const flushTable = () => {
    if (!tableBuf.length) return;
    const rows = [];
    for (const line of tableBuf) {
      if (isTableSeparator(line)) continue;
      rows.push(parseTableCells(line).map((c) => escapeHtml(c)));
    }
    if (rows.length) parts.push(renderTableHtml(rows));
    tableBuf = [];
  };

  for (const line of lines) {
    if (isTableRow(line)) {
      flushText();
      tableBuf.push(line);
    } else {
      flushTable();
      textBuf.push(line);
    }
  }
  flushTable();
  flushText();
  return parts.join("") || renderTextBlock(text);
}

function appendClarificationOptions(options) {
  if (!options?.length) return;
  const wrap = document.createElement("div");
  wrap.className = "clarification-options";
  const label = document.createElement("span");
  label.className = "clarification-label";
  label.textContent = "Уточнить:";
  wrap.appendChild(label);
  for (const opt of options) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "example clarification-chip";
    btn.textContent = opt.label;
    btn.title = opt.suggestion;
    btn.dataset.q = opt.suggestion;
    wrap.appendChild(btn);
  }
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendMessage(role, text, meta = "", citations = null) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  if (role === "assistant") {
    div.innerHTML = renderMarkdown(text);
    wireMediaInElement(div, citations ? slidesFromCitations(citations) : null);
    appendMediaGallery(div, citations);
    appendSourcesHint(div, citations);
    if (meta) {
      const tag = document.createElement("div");
      tag.className = "msg-meta";
      tag.textContent = meta;
      div.appendChild(tag);
    }
  } else {
    div.textContent = text;
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

let imageIndexPollTimer = null;

function updateImageIndexBadge(data) {
  if (!indexStatusEl) return;
  const expected = data?.giab_images_expected || 0;
  const count = data?.giab_image_count || 0;
  if (data?.images_indexing && expected > 0) {
    indexStatusEl.hidden = false;
    indexStatusEl.textContent = `Рисунки: ${count}/${expected}…`;
    indexStatusEl.className = "badge index-status indexing";
    indexStatusEl.title = "Фоновая индексация CLIP + Vision для демо-PDF";
    return true;
  }
  if (expected > 0 && count >= expected) {
    indexStatusEl.hidden = false;
    indexStatusEl.textContent = `Рисунки: ${count}`;
    indexStatusEl.className = "badge index-status ok";
    indexStatusEl.title = "CLIP-индекс рисунков готов";
    return false;
  }
  indexStatusEl.hidden = true;
  return false;
}

async function pollImageIndexStatus() {
  try {
    const res = await fetch("/api/search/status");
    if (!res.ok) return;
    const data = await res.json();
    const stillIndexing = updateImageIndexBadge(data);
    if (!stillIndexing && imageIndexPollTimer) {
      clearInterval(imageIndexPollTimer);
      imageIndexPollTimer = null;
    }
  } catch (_) {
    /* ignore */
  }
}

function startImageIndexPolling() {
  if (imageIndexPollTimer) return;
  pollImageIndexStatus();
  imageIndexPollTimer = setInterval(pollImageIndexStatus, 4000);
}

async function loadStatus() {
  try {
    const [graphRes, statusRes] = await Promise.all([
      fetch("/api/graph/stats"),
      fetch("/api/assistant/status"),
    ]);
    const graph = await graphRes.json();
    const status = await statusRes.json();
    statsEl.textContent = `Граф: ${graph.entities} сущностей, ${graph.relations} связей`;
    if (runtimeModeEl) {
      runtimeModeEl.textContent = formatRuntimeModeLabel(status);
      const noLlm = status.answer_mode === "rule" || !status.llm_enabled;
      runtimeModeEl.className = `badge badge-clickable ${noLlm ? "ok mode-lite" : "ok"}`;
      runtimeModeEl.title = noLlm
        ? "LLM выключен — ответы только из графа. Нажмите для настройки."
        : `Режим: ${status.work_mode_name || status.work_mode}. Нажмите для настройки.`;
    }
    updateOfflineButton(status.answer_mode || (status.llm_enabled ? "llm" : "rule"));
    startImageIndexPolling();
  } catch (_) {
    statsEl.textContent = "Сервер недоступен";
    if (runtimeModeEl) {
      runtimeModeEl.textContent = "Сервер недоступен";
      runtimeModeEl.className = "badge warn";
    }
  }
}

function renderGraph(subgraph) {
  lastSubgraph = subgraph;
  if (!subgraph?.nodes?.length) {
    if (network) {
      network.destroy();
      network = null;
    }
    graphEl.innerHTML =
      "<p class='graph-placeholder'>Задайте вопрос во вкладке «Диалог» — здесь появится фрагмент графа</p>";
    setGraphStatus("Задайте вопрос во вкладке «Диалог» — здесь появится фрагмент графа");
    return;
  }

  const mount = () => {
    if (typeof vis === "undefined") {
      graphEl.innerHTML =
        "<p class='graph-placeholder'>Библиотека vis.js не загрузилась — обновите страницу (Ctrl+F5)</p>";
      setGraphStatus("Ошибка: vis.js недоступен");
      return;
    }
    try {
      network = mountGraph(graphEl, subgraph, network, () => {
        graphEl.closest(".graph-section")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
      if (!graphModalEl.hidden && modalNetwork) {
        modalNetwork = mountGraph(graphModalCanvasEl, subgraph, modalNetwork);
      }
      const n = subgraph.nodes.length;
      const e = subgraph.edges?.length || 0;
      setGraphStatus(`Фрагмент графа: ${n} узлов, ${e} связей · колёсико — масштаб, перетаскивание — панорама`);
    } catch (err) {
      console.error("renderGraph:", err);
      graphEl.innerHTML =
        "<p class='graph-placeholder'>Не удалось отобразить граф — обновите страницу</p>";
      setGraphStatus("Ошибка отрисовки графа");
    }
  };

  if (graphEl.offsetParent === null) {
    requestAnimationFrame(() => requestAnimationFrame(mount));
  } else {
    mount();
  }
}

function focusGraphNode(nodeId) {
  if (!nodeId || !network) return;
  try {
    network.selectNodes([nodeId]);
    network.focus(nodeId, { scale: 1.15, animation: { duration: 400, easingFunction: "easeInOutQuad" } });
    graphEl.closest(".graph-section")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    console.warn("focusGraphNode:", err);
  }
}

const CITATION_LABELS = {
  experiment: "Эксперимент",
  document: "Документ",
  image: "Рисунок",
};

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function citationMetaLine(c) {
  const parts = [];
  if (c.chunk_id) parts.push(c.chunk_id);
  else if (c.id && c.type === "document") parts.push(c.id);
  if (c.id && c.type === "experiment") parts.push(c.id);
  if (c.page_hint) parts.push(`стр. ${c.page_hint}`);
  if (c.page) parts.push(`стр. ${c.page}`);
  if (c.score != null) parts.push(`score ${c.score}`);
  if (c.excerpt_type === "vision") parts.push("Vision");
  else if (c.excerpt_type === "chunk") parts.push("фрагмент");
  if (c.doc_type) parts.push(c.doc_type);
  if (c.doc_id && c.type === "image") parts.push(c.doc_id);
  return parts.join(" · ");
}

function renderCitations(citations) {
  if (!citationsEl) return;
  lastRenderedCitations = citations || [];
  const imageSlides = slidesFromCitations(lastRenderedCitations);
  citationsEl.innerHTML = "";
  if (!citations?.length) {
    citationsEl.innerHTML = '<p class="citations-empty">Нет привязанных источников</p>';
    return;
  }

  for (const c of citations) {
    const card = document.createElement("article");
    card.className = `source-card citation-card citation-card--${c.type || "document"}`;
    card.setAttribute("role", "listitem");

    const head = document.createElement("div");
    head.className = "citation-head";
    const badge = document.createElement("span");
    badge.className = "source-badge citation-badge";
    badge.textContent = CITATION_LABELS[c.type] || c.type || "Источник";
    const title = document.createElement("p");
    title.className = "source-card-title citation-title";
    title.textContent = c.title || c.id || "—";
    head.appendChild(badge);
    head.appendChild(title);
    card.appendChild(head);

    const metaLine = citationMetaLine(c);
    if (metaLine) {
      const meta = document.createElement("p");
      meta.className = "citation-meta";
      meta.textContent = metaLine;
      card.appendChild(meta);
    }

    if (c.snippet && c.type !== "image") {
      const snippet = document.createElement("blockquote");
      snippet.className = `source-snippet citation-snippet${c.excerpt_type === "vision" ? " citation-snippet--vision source-snippet--vision" : ""}`;
      snippet.textContent = c.snippet;
      card.appendChild(snippet);
    }

    if (c.type === "image" && c.image_url) {
      const mediaUrl = normalizeMediaUrl(c.image_url);
      const slideIndex = imageSlides.findIndex((s) => s.url === mediaUrl);
      card.appendChild(
        buildSourceImageBlock(c, imageSlides, slideIndex >= 0 ? slideIndex : 0, {
          showAnnotation: true,
          showKeyPoints: true,
          showCaption: false,
        })
      );
    }

    const actions = document.createElement("div");
    actions.className = "citation-actions";
    if (c.type === "experiment" && c.id) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "citation-btn";
      btn.textContent = "На графе";
      btn.addEventListener("click", () => {
        switchTab("main");
        focusGraphNode(c.id);
      });
      actions.appendChild(btn);
    }
    if (c.type === "document" && c.id) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "citation-btn";
      btn.textContent = "Спросить про документ";
      btn.addEventListener("click", () => {
        switchTab("dialog");
        sendMessage(`Что в документе «${c.title || c.id}» по теме последнего вопроса?`);
      });
      actions.appendChild(btn);
    }
    if (c.type === "image") {
      if (c.image_url) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "citation-btn";
        btn.textContent = "Увеличить";
        btn.addEventListener("click", () => {
          const mediaUrl = normalizeMediaUrl(c.image_url);
          const slideIndex = imageSlides.findIndex((s) => s.url === mediaUrl);
          const caption = `${c.title || c.id || "Рисунок"}${c.page ? ` · стр. ${c.page}` : ""}`;
          openImageLightbox(
            mediaUrl,
            caption,
            c.librarian_annotation || c.snippet || "",
            imageSlides,
            slideIndex >= 0 ? slideIndex : 0
          );
        });
        actions.appendChild(btn);
      }
      const label = c.doc_title ? `из «${c.doc_title}»` : c.doc_id || "";
      if (label) {
        const hint = document.createElement("span");
        hint.className = "citation-meta";
        hint.textContent = label;
        actions.appendChild(hint);
      }
    }
    if (actions.childNodes.length) card.appendChild(actions);

    citationsEl.appendChild(card);
  }
}

function renderIngestResult(data) {
  if (!ingestResultEl) return;
  const extraction = data.extraction || {};
  const parsed = data.parsed || {};
  const exps = extraction.experiments || [];
  const vision = extraction.image_analysis || {};
  const analyses = vision.image_analyses || [];

  ingestResultEl.hidden = false;
  ingestResultEl.innerHTML = "";

  const title = document.createElement("h4");
  title.textContent = `Загружено: ${parsed.title || "PDF"}`;
  ingestResultEl.appendChild(title);

  const grid = document.createElement("div");
  grid.className = "ingest-result-grid";
  const rows = [
    ["Страниц обработано", parsed.pages_parsed ?? "—"],
    ["Картинок в PDF", parsed.images_count ?? 0],
    ["Vision (описано)", `${parsed.vision_images_used ?? 0} · ${parsed.vision_provider || "—"}`],
    ["CLIP проиндексировано", parsed.images_indexed ?? 0],
    ["Экспериментов в граф", exps.length],
    ["Куратор", extraction.extraction_method || "—"],
  ];
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "ingest-result-row";
    row.innerHTML = `<span>${escapeHtml(label)}</span><span>${escapeHtml(String(value))}</span>`;
    grid.appendChild(row);
  }
  ingestResultEl.appendChild(grid);

  if (exps[0]) {
    const exp = exps[0];
    const expLine = document.createElement("p");
    expLine.className = "citation-meta";
    expLine.textContent = [
      exp.id || exp.experiment_id,
      exp.process,
      exp.property_value,
    ]
      .filter(Boolean)
      .join(" · ");
    ingestResultEl.appendChild(expLine);
  }

  if (analyses.length) {
    const visionTitle = document.createElement("p");
    visionTitle.className = "citation-meta";
    visionTitle.textContent = "Фрагменты Vision (таблицы / графики):";
    ingestResultEl.appendChild(visionTitle);
    for (const row of analyses.slice(0, 3)) {
      const block = document.createElement("div");
      block.className = "ingest-vision-block";
      const page = row.page ? `, стр. ${row.page}` : "";
      block.textContent = `[${row.image_name || "image"}${page}]\n${(row.analysis || "").slice(0, 400)}`;
      ingestResultEl.appendChild(block);
    }
  }

  const actions = document.createElement("div");
  actions.className = "ingest-actions";
  const askBtn = document.createElement("button");
  askBtn.type = "button";
  askBtn.className = "btn-secondary";
  askBtn.textContent = "Спросить в диалоге";
  askBtn.addEventListener("click", () => {
    switchTab("dialog");
    const topic = exps[0]?.process || parsed.title || "этот отчёт";
    sendMessage(`Что известно по материалам из отчёта «${parsed.title}»? Процесс: ${topic}.`);
  });
  actions.appendChild(askBtn);

  if ((parsed.images_indexed || 0) > 0) {
    const clipBtn = document.createElement("button");
    clipBtn.type = "button";
    clipBtn.className = "btn-secondary";
    clipBtn.textContent = "Поиск по рисункам";
    clipBtn.addEventListener("click", async () => {
      try {
        const q = encodeURIComponent("график извлечения никеля");
        const res = await fetch(`/api/search/images?q=${q}&limit=3`);
        const payload = await res.json();
        const hits = (payload.results || [])
          .map((h) => `• ${h.metadata?.alt || h.id} (score ${h.score?.toFixed?.(3) ?? h.score})`)
          .join("\n");
        uploadStatusEl.textContent = hits || "CLIP: ничего не найдено";
      } catch (err) {
        uploadStatusEl.textContent = `CLIP: ${err.message}`;
      }
    });
    actions.appendChild(clipBtn);
  }
  ingestResultEl.appendChild(actions);
}

async function sendMessage(text) {
  appendMessage("user", text);
  const loading = document.createElement("div");
  loading.className = "msg assistant loading";
  loading.textContent = "Ищу в графе и документах…";
  messagesEl.appendChild(loading);

  const historyPayload = chatHistory.map(({ role, content }) => ({ role, content }));

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        history: historyPayload,
        conversation_id: currentConversationId,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    loading.remove();

    if (data.conversation_id) currentConversationId = data.conversation_id;

    chatHistory.push({ role: "user", content: text });
    chatHistory.push({ role: "assistant", content: data.message });
    while (chatHistory.length > MAX_HISTORY_MESSAGES) {
      chatHistory.shift();
    }

    const meta = data.needs_clarification
      ? `требуется уточнение · реплика ${data.turn || ""}`
      : data.llm_used
        ? `ответ сформулирован LLM · реплика ${data.turn || ""}`
        : `ответ из графа (без LLM) · реплика ${data.turn || ""}`;
    appendMessage("assistant", data.message, meta.trim(), data.citations);
    appendClarificationOptions(data.clarification_options);
    updateDialogInfo(data.turn);
    try {
      renderCitations(data.citations);
      renderGraph(data.subgraph);
      if (data.conversation_id) {
        saveSubgraphForConversation(data.conversation_id, data.subgraph);
      }
    } catch (renderErr) {
      console.error("UI render error:", renderErr);
      warnRenderFailure();
    }
    await loadConversations();
  } catch (err) {
    loading.remove();
    console.error("Chat request failed:", err);
    appendMessage(
      "assistant",
      "Ошибка запроса. Проверьте, что сервер запущен и config.env настроен."
    );
  }
}

function warnRenderFailure() {
  if (graphEl.querySelector(".graph-placeholder")) return;
  graphEl.innerHTML =
    "<p class='graph-placeholder'>Ответ получен, но фрагмент графа не отобразился. Обновите страницу.</p>";
}

async function loadVisionStatus() {
  if (!visionStatusEl) return;
  try {
    const res = await fetch("/api/vision/status");
    const data = await res.json();
    const v = data.available ? `${data.provider} (${data.model || "ok"})` : data.message || "недоступен";
    const clip = data.clip?.available
      ? `CLIP ${data.clip.model}`
      : data.clip?.message || "CLIP выкл.";
    visionStatusEl.textContent = `Vision: ${v} · ${clip}`;
  } catch {
    visionStatusEl.textContent = "Vision: статус недоступен";
  }
}

async function uploadFile(formEl, endpoint) {
  const fileInput = formEl.querySelector('input[type="file"]');
  if (!fileInput.files?.length) {
    uploadStatusEl.textContent = "Выберите файл";
    return;
  }
  uploadStatusEl.textContent = "Загрузка…";
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  let url = endpoint;
  if (endpoint.includes("/ingest/pdf")) {
    const analyze = document.getElementById("pdf-analyze-images")?.checked !== false;
    const indexImg = document.getElementById("pdf-index-images")?.checked !== false;
    const qs = new URLSearchParams({
      analyze_images: String(analyze),
      index_images: String(indexImg),
    });
    url = `${endpoint}?${qs}`;
  }
  try {
    const res = await fetch(url, { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "ошибка");
    if (endpoint.includes("xlsx")) {
      uploadStatusEl.textContent = `Загружено экспериментов: ${data.experiments_loaded ?? "?"}`;
      if (ingestResultEl) ingestResultEl.hidden = true;
    } else {
      const p = data.parsed || {};
      const ex = data.extraction?.experiments?.length ?? 0;
      const parts = [
        `PDF: ${p.images_count ?? 0} картинок`,
        p.vision_provider ? `vision=${p.vision_provider} (${p.vision_images_used ?? 0})` : null,
        p.images_indexed != null ? `CLIP=${p.images_indexed}` : null,
        `экспериментов: ${ex}`,
      ].filter(Boolean);
      uploadStatusEl.textContent = parts.join(" · ");
      renderIngestResult(data);
    }
    fileInput.value = "";
    loadStatus();
    loadGraphDetail();
    loadVisionStatus();
  } catch (err) {
    uploadStatusEl.textContent = `Ошибка: ${err.message}`;
  }
}

function renderDemoQuestions() {
  if (!demoQuestionsEl) return;

  let globalNum = 0;

  DEMO_QUESTIONS.forEach((group, groupIdx) => {
    const section = document.createElement("section");
    section.className = "demo-category";

    const head = document.createElement("div");
    head.className = "demo-category-head";

    const badge = document.createElement("span");
    badge.className = "demo-category-badge";
    badge.textContent = String(groupIdx + 1);

    const title = document.createElement("span");
    title.className = "demo-category-title";
    title.textContent = group.title;

    const hint = document.createElement("span");
    hint.className = "demo-category-hint";
    hint.textContent = group.hint;

    head.appendChild(badge);
    head.appendChild(title);
    head.appendChild(hint);

    const cards = document.createElement("div");
    cards.className = "demo-cards";

    for (const item of group.items) {
      globalNum += 1;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `example demo-card${item.gaps ? " btn-gaps" : ""}${item.clarify ? " btn-clarify" : ""}${item.multimodal ? " btn-multimodal" : ""}`;
      btn.dataset.q = item.q;
      if (item.freshDialog) btn.dataset.fresh = "1";
      btn.title = item.q;
      btn.innerHTML = `
        <span class="demo-num">${globalNum}</span>
        <span class="demo-card-body">
          <span class="demo-card-label">${escapeHtml(item.label)}</span>
          <span class="demo-card-q">${escapeHtml(item.q)}</span>
        </span>`;
      cards.appendChild(btn);
    }

    section.appendChild(head);
    section.appendChild(cards);
    demoQuestionsEl.appendChild(section);
  });
}

function sendDemoQuestion(text, options = {}) {
  switchTab("dialog");
  const run = async () => {
    if (options.freshDialog) {
      await createConversation(false);
    }
    input.value = "";
    sendMessage(text);
  };
  run();
}

function showWelcome() {
  appendMessage(
    "assistant",
    "Здравствуйте! Я помогаю находить эксперименты, команды и пробелы в исследованиях.\n\n" +
      "Задайте вопрос здесь или откройте вкладку **Демо** — там 20 сценариев (в т.ч. 4 по рисункам GIAB). Граф и источники — на вкладке **Главная**. Можно уточнять: «сравни», «свести в таблицу»."
  );
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendMessage(text);
});

demoQuestionsEl?.addEventListener("click", (e) => {
  const btn = e.target.closest(".example");
  if (!btn?.dataset.q) return;
  sendDemoQuestion(btn.dataset.q, { freshDialog: btn.dataset.fresh === "1" });
});

document.getElementById("open-demo-tab")?.addEventListener("click", () => switchTab("demo"));
document.getElementById("open-dialog-tab")?.addEventListener("click", () => switchTab("dialog"));
document.getElementById("open-main-tab")?.addEventListener("click", () => switchTab("main"));
toggleOfflineBtn?.addEventListener("click", toggleOfflineMode);
runtimeModeEl?.addEventListener("click", () => switchTab("llm"));

messagesEl.addEventListener("click", (e) => {
  const btn = e.target.closest(".clarification-chip");
  if (!btn?.dataset.q) return;
  sendMessage(btn.dataset.q);
});

newDialogBtn?.addEventListener("click", resetDialog);

conversationListEl?.addEventListener("click", (e) => {
  const btn = e.target.closest(".conversation-item");
  if (!btn?.dataset.id) return;
  loadConversation(btn.dataset.id);
});

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.querySelectorAll('input[name="llm-provider"]').forEach((radio) => {
  radio.addEventListener("change", updateLlmFieldsVisibility);
});

document.querySelectorAll('input[name="llm-answer-mode"]').forEach((radio) => {
  radio.addEventListener("change", async () => {
    updateLlmFieldsVisibility();
    if (suppressRuntimeAutoApply) return;
    const answer_mode = getSelectedAnswerMode();
    const search_mode = answer_mode === "rule" ? "keyword" : getSelectedSearchMode();
    try {
      await applyRuntimeConfig({
        answer_mode,
        search_mode,
        provider: getSelectedLlmProvider(),
        ollama_model: llmOllamaModelEl?.value,
        openai_model: llmOpenaiModelEl?.value?.trim(),
      });
      showRuntimeToast(
        answer_mode === "rule" ? "LLM отключён" : "LLM включён — нажмите «Применить» для провайдера"
      );
    } catch (err) {
      showRuntimeToast(`Ошибка: ${err.message}`, true);
    }
  });
});

document.querySelectorAll('input[name="search-mode"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    document.querySelectorAll(".work-mode-card").forEach((c) => c.classList.remove("selected"));
    document.querySelectorAll('input[name="work-mode"]').forEach((r) => { r.checked = false; });
  });
});

document.getElementById("llm-save")?.addEventListener("click", saveLlmConfig);
document.getElementById("llm-probe")?.addEventListener("click", probeLlmConfig);

document.getElementById("reload-seed")?.addEventListener("click", async () => {
  uploadStatusEl.textContent = "Перезагрузка…";
  try {
    const res = await fetch("/api/admin/reload", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error("reload failed");
    uploadStatusEl.textContent = `OK: ${data.graph?.entities ?? "?"} сущностей`;
    loadStatus();
    loadGraphDetail();
  } catch (err) {
    uploadStatusEl.textContent = `Ошибка: ${err.message}`;
  }
});

document.getElementById("upload-xlsx").addEventListener("submit", (e) => {
  e.preventDefault();
  uploadFile(e.target, "/api/ingest/xlsx");
});

document.getElementById("upload-pdf").addEventListener("submit", (e) => {
  e.preventDefault();
  uploadFile(e.target, "/api/ingest/pdf");
});

document.getElementById("graph-fit")?.addEventListener("click", () => fitGraph(network));
document.getElementById("graph-zoom-in")?.addEventListener("click", () => zoomGraph(network, 1.25));
document.getElementById("graph-zoom-out")?.addEventListener("click", () => zoomGraph(network, 0.8));
document.getElementById("graph-expand")?.addEventListener("click", openGraphModal);

document.getElementById("graph-modal-fit")?.addEventListener("click", () => fitGraph(modalNetwork, 50));
document.getElementById("graph-modal-zoom-in")?.addEventListener("click", () => zoomGraph(modalNetwork, 1.25));
document.getElementById("graph-modal-zoom-out")?.addEventListener("click", () => zoomGraph(modalNetwork, 0.8));
document.getElementById("graph-modal-close")?.addEventListener("click", closeGraphModal);
graphModalEl?.querySelector("[data-close-graph-modal]")?.addEventListener("click", closeGraphModal);
document.getElementById("image-modal-close")?.addEventListener("click", closeImageLightbox);
document.getElementById("image-modal-prev")?.addEventListener("click", () => stepLightbox(-1));
document.getElementById("image-modal-next")?.addEventListener("click", () => stepLightbox(1));
imageModalEl?.querySelector("[data-close-image-modal]")?.addEventListener("click", closeImageLightbox);
document.addEventListener("keydown", (e) => {
  const lightboxOpen = imageModalEl && !imageModalEl.hidden;
  const graphOpen = graphModalEl && !graphModalEl.hidden;
  if (e.key === "Escape") {
    if (lightboxOpen) closeImageLightbox();
    else if (graphOpen) closeGraphModal();
    return;
  }
  if (!lightboxOpen || lightboxSlides.length < 2) return;
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    stepLightbox(-1);
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    stepLightbox(1);
  }
});

renderDemoQuestions();
loadStatus();
loadGraphDetail();
refreshOfflineUiFromServer();

async function initApp() {
  try {
    const res = await fetch("/api/conversations");
    const items = res.ok ? await res.json() : [];
    if (items.length > 0) {
      await loadConversation(items[0].id);
    } else {
      await createConversation(true);
    }
  } catch (err) {
    console.error("initApp:", err);
    await createConversation(true);
  }
}

initApp();
