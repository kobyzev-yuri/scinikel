const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("input");
const citationsEl = document.getElementById("citations");
const statsEl = document.getElementById("stats");
const graphEl = document.getElementById("graph");

let network = null;

function appendMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function loadStats() {
  try {
    const res = await fetch("/api/graph/stats");
    const data = await res.json();
    statsEl.textContent = `Граф: ${data.entities} сущностей, ${data.relations} связей`;
  } catch (_) {
    statsEl.textContent = "";
  }
}

function renderGraph(subgraph) {
  if (!subgraph || !subgraph.nodes?.length) {
    graphEl.innerHTML = "<p style='padding:1rem;color:#8b9cb3;font-size:0.85rem'>Задайте вопрос — здесь появится фрагмент графа</p>";
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
    const data = await res.json();
    loading.remove();
    appendMessage("assistant", data.message);
    renderCitations(data.citations);
    renderGraph(data.subgraph);
  } catch (err) {
    loading.remove();
    appendMessage("assistant", "Ошибка запроса. Проверьте, что сервер запущен.");
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

loadStats();
