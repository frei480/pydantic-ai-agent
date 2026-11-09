"use strict";

/* =================================================================
   Docs AI Agent — vanilla JS фронтенд
   Стор: список чатов (сайдбар) + текстовый чат со стримингом SSE.
   ================================================================= */

const $ = (sel) => document.querySelector(sel);
const chatsEl = $("#chat-list");
const messagesEl = $("#messages");
const titleEl = $("#chat-title");
const statusEl = $("#status");
const backendHealthEl = $("#backend-health");
const modelHealthEl = $("#model-health");
const inputEl = $("#input");
const sendEl = $("#send");
const newChatEl = $("#new-chat");

const state = {
  chats: [],
  currentId: null,
  busy: false,
};

/* ---------------- markdown (минималистичный) ---------------- */

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderInline(text) {
  let s = escapeHtml(text);
  s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}

function renderMarkdown(src) {
  // 1) блоки ```...```
  const parts = src.split(/```/);
  let html = "";
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      // языковой маркер: первая строка
      const nl = parts[i].indexOf("\n");
      let body;
      if (nl === -1) body = parts[i];
      else body = parts[i].slice(nl + 1);
      html += "<pre><code>" + escapeHtml(body.replace(/\n$/, "")) + "</code></pre>";
    } else {
      html += renderBlock(parts[i]);
    }
  }
  return html;
}

function renderBlock(block) {
  const lines = block.split("\n");
  let html = "";
  let listOpen = false;
  for (const raw of lines) {
    const line = raw.trimEnd();
    const li = line.match(/^\s*(?:[-*]|\d+[.)])\s+(.*)$/);
    if (li) {
      if (!listOpen) { html += "<ul>"; listOpen = true; }
      html += "<li>" + renderInline(li[1]) + "</li>";
      continue;
    }
    if (listOpen) { html += "</ul>"; listOpen = false; }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h && h[2]) {
      const level = Math.min(h[1].length + 2, 5);
      html += `<h${level}>` + renderInline(h[2]) + `</h${level}>`;
      continue;
    }
    if (!line.trim()) continue;
    html += "<p>" + renderInline(line) + "</p>";
  }
  if (listOpen) html += "</ul>";
  return html;
}

/* ---------------- API ---------------- */

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function setHealthIndicator(el, state, label, title) {
  el.className = `health-indicator ${state}`;
  el.querySelector(".health-label").textContent = label;
  el.title = title;
}

let healthCheckRunning = false;

async function checkHealth() {
  if (healthCheckRunning) return;
  healthCheckRunning = true;
  setHealthIndicator(backendHealthEl, "checking", "Backend: проверка", "Проверка backend");
  setHealthIndicator(modelHealthEl, "checking", "Модель: проверка", "Проверка модели");

  const request = async (path, timeoutMs) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await api(path, { signal: controller.signal, cache: "no-store" });
    } finally {
      clearTimeout(timeout);
    }
  };

  try {
    await request("/api/health", 5000);
    setHealthIndicator(backendHealthEl, "ok", "Backend: работает", "Backend доступен");

    try {
      const model = await request("/api/health/model", 15000);
      if (model.status === "ok") {
        setHealthIndicator(
          modelHealthEl,
          "ok",
          `Модель: отвечает (${model.model})`,
          `${model.model}: ${model.detail}`
        );
      } else {
        setHealthIndicator(
          modelHealthEl,
          "down",
          `Модель: недоступна (${model.model})`,
          model.detail
        );
      }
    } catch (err) {
      setHealthIndicator(modelHealthEl, "down", "Модель: ошибка проверки", err.message);
    }
  } catch (err) {
    setHealthIndicator(backendHealthEl, "down", "Backend: недоступен", err.message);
    setHealthIndicator(modelHealthEl, "down", "Модель: нет соединения", "Backend недоступен");
  } finally {
    healthCheckRunning = false;
  }
}

async function loadChats() {
  state.chats = await api("/api/chats");
  renderSidebar();
}

function renderSidebar() {
  chatsEl.innerHTML = "";
  for (const chat of state.chats) {
    const item = document.createElement("div");
    item.className = "chat-item" + (chat.id === state.currentId ? " active" : "");
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = chat.title;
    title.addEventListener("click", () => selectChat(chat.id));
    const del = document.createElement("button");
    del.className = "del";
    del.title = "Удалить чат";
    del.textContent = "✕";
    del.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Удалить чат?")) return;
      await api(`/api/chats/${chat.id}`, { method: "DELETE" });
      if (state.currentId === chat.id) state.currentId = null;
      await loadChats();
      if (!state.currentId) showEmpty();
    });
    item.append(title, del);
    chatsEl.appendChild(item);
  }
}

/* ---------------- чат ---------------- */

function showEmpty() {
  titleEl.textContent = "Новый чат";
  messagesEl.innerHTML = `
    <div class="empty-state">
      Помощник по API-документации. Задайте вопрос -<br>
      агент найдёт справку, проверит себя и напишет рабочий код.
      <div class="hints">
        <span data-q="Как создать сплайн на 2D-сцене через API?">Пример: сплайн на сцене</span>
        <span data-q="Как кодом создать слой в T-FLEX DOCs, связанный с параметром детали?">Пример: слой T-FLEX DOCs</span>
        <span data-q="Найди в документации все методы класса DocDocument.">Пример: методы класса</span>
      </div>
    </div>`;
  messagesEl.querySelectorAll(".hints span").forEach((el) =>
    el.addEventListener("click", () => {
      inputEl.value = el.dataset.q;
      inputEl.focus();
      autoGrow();
    })
  );
}

async function selectChat(id) {
  if (state.busy) return;
  state.currentId = id;
  renderSidebar();
  const data = await api(`/api/chats/${id}/messages`);
  titleEl.textContent = data.chat.title;
  messagesEl.innerHTML = "";
  if (!data.messages.length) { showEmpty(); return; }
  for (const m of data.messages) addMessage(m.role, m.content, { save: false });
  scrollBottom();
}

function addMessage(role, content, { save = true, cursor = false } = {}) {
  // удалить empty-state, если он был
  const empty = messagesEl.querySelector(".empty-state");
  if (empty) empty.remove();

  const div = document.createElement("div");
  div.className = `msg ${role}`;
  if (role === "user") {
    div.textContent = content;
  } else {
    div.innerHTML = renderMarkdown(content) + (cursor ? '<span id="stream-cursor" style="opacity:.5">▍</span>' : "");
  }
  messagesEl.appendChild(div);
  const activity = document.createElement("div");
  activity.className = "activity";
  messagesEl.insertBefore(activity, div);
  if (save) scrollBottom();
  return { div, activity };
}

function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setStatus(text) {
  if (text) { statusEl.textContent = text; statusEl.hidden = false; }
  else { statusEl.textContent = ""; statusEl.hidden = true; }
}

/* ---------------- отправка со стримингом ---------------- */

const PHASE_LABEL = {
  research: "🔎 Поиск в документации…",
  critique: "🧐 Проверка качества…",
  refine: "🔁 Уточнение поиска…",
  write: "✍️ Составление ответа…",
};

async function sendMessage() {
  const content = inputEl.value.trim();
  if (!content || state.busy) return;
  inputEl.value = "";
  autoGrow();
  state.busy = true;
  sendEl.disabled = true;

  try {
    let chatId = state.currentId;
    if (!chatId) {
      const chat = await api("/api/chats", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: content.slice(0, 60) }),
      });
      chatId = chat.id;
      state.currentId = chatId;
    }
    await loadChats();
    titleEl.textContent = content.slice(0, 60);
    addMessage("user", content);

    const res = await fetch(`/api/chats/${chatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Ошибка сервера");

    const { div, activity } = addMessage("assistant", "", { cursor: true });
    const cursor = div.querySelector("#stream-cursor");
    let text = "";
    let activityLines = [];
    let draftSeen = false;

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    const appendActivity = (line, { rawHtml = false } = {}) => {
      if (!rawHtml) line = escapeHtml(line);
      activityLines.push({ line, rawHtml });
      if (activityLines.length > 6) {
        // сворачиваем длинный лог в details
        activity.innerHTML =
          `<details><summary>🔧 активность агента (${activityLines.length})</summary><pre>` +
          escapeHtml(activityLines.map((x) => x.line).join("\n")) +
          "</pre></details>";
      } else {
        activity.innerHTML = activityLines
          .map(({ line }) => `<div class="line">${line}</div>`)
          .join("");
      }
      scrollBottom();
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const dataLine = chunk.split("\n").find((l) => l.startsWith("data:"));
        if (!dataLine) continue;
        let ev;
        try { ev = JSON.parse(dataLine.slice(5)); } catch { continue; }
        handleEvent(ev);
      }
    }

    function handleEvent(ev) {
      switch (ev.type) {
        case "start":
          if (ev.chat && ev.chat.title) titleEl.textContent = ev.chat.title;
          break;
        case "phase":
          setStatus(PHASE_LABEL[ev.phase] || "…" + (ev.round && ev.round > 1 ? ` (итерация ${ev.round})` : ""));
          if (ev.phase === "research") appendActivity(`— ${PHASE_LABEL.research}`);
          if (ev.phase === "write") setStatus(PHASE_LABEL.write);
          break;
        case "tool":
          appendActivity("🔧 " + ev.detail);
          break;
        case "draft":
          // черновик исследователя: достаточно одной строки индикации в логе
          if (!draftSeen) {
            draftSeen = true;
            appendActivity("📝 исследователь составляет черновик…");
          }
          break;
        case "critique": {
          const cls = ev.sufficient ? "ok" : "gap";
          const label = ev.sufficient ? "критик: достаточно" : "критик: недостаточно";
          const missing = (ev.missing || []).slice(0, 3).join("; ");
          appendActivity(
            `<span class="critique-badge ${cls}">${label}</span>` + escapeHtml(ev.comments || missing),
            { rawHtml: true }
          );
          break;
        }
        case "text": {
          text += ev.text;
          div.innerHTML = renderMarkdown(text) + '<span id="stream-cursor" style="opacity:.5">▍</span>';
          scrollBottom();
          break;
        }
        case "error":
          text += `\n\n**Ошибка:** ${ev.message}`;
          div.innerHTML = renderMarkdown(text);
          break;
        case "done":
          break;
      }
    }

    if (cursor) cursor.remove();
    div.innerHTML = renderMarkdown(text);
    await loadChats();
  } catch (err) {
    addMessage("assistant", `**Ошибка:** ${err.message}`);
  } finally {
    state.busy = false;
    sendEl.disabled = false;
    inputEl.focus();
    setStatus("");
  }
}

/* ---------------- ввод ---------------- */

function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, window.innerHeight * 0.4) + "px";
}

inputEl.addEventListener("input", autoGrow);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
$("#composer").addEventListener("submit", (e) => { e.preventDefault(); sendMessage(); });
newChatEl.addEventListener("click", () => {
  if (state.busy) return;
  state.currentId = null;
  renderSidebar();
  showEmpty();
  inputEl.focus();
});

/* ---------------- старт ---------------- */

(async function init() {
  checkHealth();
  setInterval(checkHealth, 60_000);
  await loadChats().catch(() => {});
  showEmpty();
  inputEl.focus();
})();
