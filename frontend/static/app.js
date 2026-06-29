const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("input");
const demoQuestionsEl = document.getElementById("demo-questions");
const citationsEl = document.getElementById("citations");
const statsEl = document.getElementById("stats");
const searchStatusEl = document.getElementById("search-status");
const llmStatusEl = document.getElementById("llm-status");
const graphEl = document.getElementById("graph");
const graphModalEl = document.getElementById("graph-modal");
const graphModalCanvasEl = document.getElementById("graph-modal-canvas");
const uploadStatusEl = document.getElementById("upload-status");
const dialogInfoEl = document.getElementById("dialog-info");
const newDialogBtn = document.getElementById("new-dialog");
const conversationListEl = document.getElementById("conversation-list");
const graphDetailEl = document.getElementById("graph-detail");
const graphStatusEl = document.getElementById("graph-status");

const SUBGRAPH_STORAGE_PREFIX = "scinikel:subgraph:";

function parseMessageMeta(meta = "") {
  const [kind, center] = (meta || "").split(":", 2);
  return { kind: kind || meta, center: center?.startsWith("EXP-") ? center : null };
}

function formatMessageMeta(meta = "") {
  const { kind } = parseMessageMeta(meta);
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

    const { center } = parseMessageMeta(msg.meta);
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
    stabilization: { iterations: 150, fit: true },
    barnesHut: {
      gravitationalConstant: -12000,
      centralGravity: 0.15,
      springLength: 160,
      springConstant: 0.04,
      avoidOverlap: 0.25,
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

function fitGraph(net, padding = 40) {
  if (!net) return;
  net.fit({ animation: { duration: 350, easingFunction: "easeInOutQuad" }, padding });
}

function zoomGraph(net, factor) {
  if (!net) return;
  const scale = net.getScale() * factor;
  net.moveTo({ scale: Math.min(2.5, Math.max(0.15, scale)) });
}

function mountGraph(container, subgraph, currentNetwork) {
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
  net.once("stabilizationIterationsDone", () => fitGraph(net));
  net.on("doubleClick", () => fitGraph(net));
  return net;
}

function openGraphModal() {
  if (!lastSubgraph?.nodes?.length) return;
  graphModalEl.hidden = false;
  document.body.style.overflow = "hidden";
  modalNetwork = mountGraph(graphModalCanvasEl, lastSubgraph, modalNetwork);
  setTimeout(() => fitGraph(modalNetwork, 50), 80);
}

function closeGraphModal() {
  graphModalEl.hidden = true;
  document.body.style.overflow = "";
  if (modalNetwork) {
    modalNetwork.destroy();
    modalNetwork = null;
  }
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
    for (const msg of data.messages) {
      appendMessage(msg.role, msg.content, formatMessageMeta(msg.meta));
      chatHistory.push({ role: msg.role, content: msg.content });
    }
    updateDialogInfo(Math.ceil(chatHistory.length / 2));
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
  if (tabName === "knowledge") loadGraphDetail();
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

function renderTextBlock(text) {
  let html = escapeHtml(text);
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

function appendMessage(role, text, meta = "") {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  if (role === "assistant") {
    div.innerHTML = renderMarkdown(text);
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

async function loadStatus() {
  try {
    const [graphRes, statusRes] = await Promise.all([
      fetch("/api/graph/stats"),
      fetch("/api/assistant/status"),
    ]);
    const graph = await graphRes.json();
    const status = await statusRes.json();
    statsEl.textContent = `Граф: ${graph.entities} сущностей, ${graph.relations} связей`;
    searchStatusEl.textContent = `Поиск: ${status.search_backend}`;
    searchStatusEl.className = `badge ${status.search_backend === "qdrant+e5" ? "ok" : "warn"}`;
    llmStatusEl.textContent = status.llm_enabled
      ? `LLM: ${status.llm_model}`
      : "LLM: rule-based";
    llmStatusEl.className = `badge ${status.llm_enabled ? "ok" : "warn"}`;
  } catch (_) {
    statsEl.textContent = "Сервер недоступен";
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
      "<p class='graph-placeholder'>Задайте вопрос — здесь появится фрагмент графа</p>";
    setGraphStatus("Задайте вопрос — здесь появится фрагмент графа");
    return;
  }

  switchTab("dialog");

  const mount = () => {
    if (typeof vis === "undefined") {
      graphEl.innerHTML =
        "<p class='graph-placeholder'>Библиотека vis.js не загрузилась — обновите страницу (Ctrl+F5)</p>";
      setGraphStatus("Ошибка: vis.js недоступен");
      return;
    }
    try {
      network = mountGraph(graphEl, subgraph, network);
      if (!graphModalEl.hidden && modalNetwork) {
        modalNetwork = mountGraph(graphModalCanvasEl, subgraph, modalNetwork);
      }
      const n = subgraph.nodes.length;
      const e = subgraph.edges?.length || 0;
      setGraphStatus(`Фрагмент графа: ${n} узлов, ${e} связей · колёсико — масштаб, перетаскивание — панорама`);
      graphEl.closest(".graph-section")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
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

function renderCitations(citations) {
  citationsEl.innerHTML = "";
  if (!citations?.length) {
    citationsEl.innerHTML = "<li>—</li>";
    return;
  }
  for (const c of citations) {
    const li = document.createElement("li");
    li.textContent = `[${c.type}] ${c.title || c.id}`;
    citationsEl.appendChild(li);
  }
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
    appendMessage("assistant", data.message, meta.trim());
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

async function uploadFile(formEl, endpoint) {
  const fileInput = formEl.querySelector('input[type="file"]');
  if (!fileInput.files?.length) {
    uploadStatusEl.textContent = "Выберите файл";
    return;
  }
  uploadStatusEl.textContent = "Загрузка…";
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  try {
    const res = await fetch(endpoint, { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "ошибка");
    uploadStatusEl.textContent = endpoint.includes("xlsx")
      ? `Загружено экспериментов: ${data.experiments_loaded ?? "?"}`
      : "PDF обработан и добавлен в граф";
    fileInput.value = "";
    loadStatus();
    loadGraphDetail();
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
      btn.className = `example demo-card${item.gaps ? " btn-gaps" : ""}${item.clarify ? " btn-clarify" : ""}`;
      btn.dataset.q = item.q;
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

function sendDemoQuestion(text) {
  switchTab("dialog");
  input.value = "";
  sendMessage(text);
}

function showWelcome() {
  appendMessage(
    "assistant",
    "Здравствуйте! Я помогаю находить эксперименты, команды и пробелы в исследованиях.\n\n" +
      "Задайте свой вопрос или откройте вкладку **Демо** — там 16 нумерованных сценариев для презентации. Можно уточнять в диалоге: «сравни», «свести в таблицу»."
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
  sendDemoQuestion(btn.dataset.q);
});

document.getElementById("open-demo-tab")?.addEventListener("click", () => switchTab("demo"));

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
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && graphModalEl && !graphModalEl.hidden) closeGraphModal();
});

renderDemoQuestions();
loadStatus();
loadGraphDetail();

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
