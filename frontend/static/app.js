const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("input");
const citationsEl = document.getElementById("citations");
const statsEl = document.getElementById("stats");
const searchStatusEl = document.getElementById("search-status");
const llmStatusEl = document.getElementById("llm-status");
const graphEl = document.getElementById("graph");
const uploadStatusEl = document.getElementById("upload-status");

let network = null;

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/^• (.+)$/gm, "<li>$1</li>");
  if (html.includes("<li>")) {
    html = html.replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>");
  }
  html = html.replace(/\n/g, "<br>");
  return html;
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
  if (!subgraph || !subgraph.nodes?.length) {
    graphEl.innerHTML =
      "<p class='graph-placeholder'>Задайте вопрос — здесь появится фрагмент графа</p>";
    return;
  }

  const typeColors = {
    Experiment: "#3d9a8b",
    Material: "#6b8cce",
    Mode: "#c9a227",
    Property: "#c76b6b",
    Team: "#9b7ed9",
    Equipment: "#7ed99b",
    Conclusion: "#e8eef5",
    Document: "#8b9cb3",
    Topic: "#555",
  };

  const nodes = new vis.DataSet(
    subgraph.nodes.map((n) => ({
      id: n.id,
      label: n.label.length > 24 ? n.label.slice(0, 22) + "…" : n.label,
      color: typeColors[n.type] || "#888",
      font: { color: "#fff", size: 11 },
    }))
  );

  const edges = new vis.DataSet(
    subgraph.edges.map((e) => ({
      id: e.id,
      from: e.source,
      to: e.target,
      label: e.label.replace(/_/g, " "),
      arrows: "to",
      font: { size: 9, align: "middle", color: "#8b9cb3" },
      color: { color: "#2d3a4d" },
    }))
  );

  if (network) network.destroy();
  network = new vis.Network(
    graphEl,
    { nodes, edges },
    {
      physics: { stabilization: true, barnesHut: { gravitationalConstant: -3000 } },
      interaction: { hover: true },
    }
  );
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

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    loading.remove();
    const meta = data.llm_used ? "ответ сформулирован LLM" : "ответ из графа (без LLM)";
    appendMessage("assistant", data.message, meta);
    renderCitations(data.citations);
    renderGraph(data.subgraph);
  } catch (_) {
    loading.remove();
    appendMessage("assistant", "Ошибка запроса. Проверьте, что сервер запущен и config.env настроен.");
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
  try {
    const res = await fetch(endpoint, { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "ошибка");
    uploadStatusEl.textContent = endpoint.includes("xlsx")
      ? `Загружено экспериментов: ${data.experiments_loaded ?? "?"}`
      : "PDF обработан и добавлен в граф";
    fileInput.value = "";
    loadStatus();
  } catch (err) {
    uploadStatusEl.textContent = `Ошибка: ${err.message}`;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendMessage(text);
});

document.querySelectorAll(".example").forEach((btn) => {
  btn.addEventListener("click", () => {
    const q = btn.dataset.q;
    input.value = q;
    sendMessage(q);
  });
});

document.getElementById("upload-xlsx").addEventListener("submit", (e) => {
  e.preventDefault();
  uploadFile(e.target, "/api/ingest/xlsx");
});

document.getElementById("upload-pdf").addEventListener("submit", (e) => {
  e.preventDefault();
  uploadFile(e.target, "/api/ingest/pdf");
});

loadStatus();
