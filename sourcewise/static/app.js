const paths = {
  brand: '<path d="M3 7l9-4 9 4-9 4-9-4zM3 12l9 4 9-4M3 17l9 4 9-4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.4"/><rect x="14" y="3" width="7" height="7" rx="1.4"/><rect x="3" y="14" width="7" height="7" rx="1.4"/><rect x="14" y="14" width="7" height="7" rx="1.4"/>',
  library: '<rect x="3" y="4" width="5" height="16" rx="1"/><rect x="9" y="4" width="5" height="16" rx="1"/><path d="m15 5 4-1 3 15-4 1zM4 16h3m3 0h3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18-3-3-3-15 0-18z"/>',
  video: '<rect x="3" y="5" width="18" height="14" rx="4"/><path d="m10 9 5 3-5 3z"/>',
  file: '<path d="M6 3h8l4 4v14H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM14 3v5h4M8 13h7m-7 4h6"/>',
  code: '<path d="m7 7-5 5 5 5m10-10 5 5-5 5m-3-13-4 16"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.2 9a2.85 2.85 0 1 1 4.9 2c-1.15 1-2.1 1.3-2.1 2.5m0 3.1h.01"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5"/>',
  spark: '<path d="M12 2c1.15 6.35 3.65 8.85 10 10-6.35 1.15-8.85 3.65-10 10-1.15-6.35-3.65-8.85-10-10 6.35-1.15 8.85-3.65 10-10z"/>',
  inbox: '<path d="M4 5h16l2 9v5H2v-5l2-9zM2 14h6l1.5 2h5l1.5-2h6"/>',
  link: '<path d="m10 14 4-4m-6 5-1 1a3 3 0 0 1-4-4l4-4a3 3 0 0 1 4 0m2 8a3 3 0 0 0 4 0l4-4a3 3 0 0 0-4-4l-1 1"/>',
  upload: '<path d="M12 16V4m-5 5 5-5 5 5M4 15v5h16v-5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  download: '<path d="M12 4v12m-5-5 5 5 5-5M4 17v3h16v-3"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5"/>',
  chat: '<path d="M20 11a7 7 0 0 1-7 7H8l-4 3v-5a7 7 0 0 1-1-4V9a5 5 0 0 1 5-5h7a5 5 0 0 1 5 5zM8 11h.01m4 0h.01m4 0h.01"/>',
  send: '<path d="m4 4 16 8-16 8 3-8-3-8zM7 12h13"/>',
  retry: '<path d="M5 12a7 7 0 1 1 2 5m-2-5V6m0 6h6"/>',
};

function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ""}</svg>`;
}

const types = {
  website: { title: "Website", icon: "globe", label: "Website URL", placeholder: "https://example.com/article", hint: "Use a publicly accessible page with readable text." },
  youtube: { title: "YouTube", icon: "video", label: "YouTube URL", placeholder: "https://www.youtube.com/watch?v=…", hint: "Uses captions when available, with audio transcription as a fallback." },
  pdf: { title: "PDF", icon: "file", label: "PDF document", hint: "Upload a PDF up to 25 MB. Scanned pages can be read with OCR." },
  github: { title: "GitHub code", icon: "code", label: "GitHub file URL", placeholder: "https://github.com/owner/repo/blob/main/app.py", hint: "Use a file link or upload code to get a code map and interview questions." },
};
const state = {
  type: "website", upload: false, file: null, library: [], filter: "all", page: "", id: null,
  detail: null, tab: "overview", nodeId: null, poll: null, pending: new Set(),
};
const $ = (selector) => document.querySelector(selector);
const ids = ["home-view", "library-view", "detail-view"];
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

document.querySelectorAll("[data-icon]").forEach((element) => element.innerHTML = icon(element.dataset.icon));

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) {
    const message = typeof result.detail === "string" ? result.detail : "Check the input and try again.";
    throw new Error(message);
  }
  return result;
}

function post(body) {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

let toastTimeout;
function toast(message) {
  clearTimeout(toastTimeout);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  toastTimeout = setTimeout(() => { $("#toast").hidden = true; }, 4800);
}

function labelName(type) {
  return types[type]?.title || "Source";
}

function showError(selector, message) {
  const target = $(selector);
  if (!target) return;
  target.hidden = !message;
  target.textContent = message || "";
}

function setType(type, moveFocus = false) {
  const previous = state.type;
  state.type = type;
  if (previous !== type) {
    state.upload = false;
    state.file = null;
    $("#source-url").value = "";
    $("#source-file").value = "";
  }
  for (const tab of document.querySelectorAll("[data-kind]")) {
    const active = tab.dataset.kind === type;
    tab.classList.toggle("selected", active);
    tab.setAttribute("aria-selected", active);
    tab.tabIndex = active ? 0 : -1;
  }
  const meta = types[type];
  const fileMode = type === "pdf" || state.upload;
  $("#source-form").setAttribute("aria-labelledby", `tab-${type}`);
  $("#url-wrap").hidden = fileMode;
  $("#source-url").disabled = fileMode;
  $("#source-url").placeholder = meta.placeholder || "";
  $("#dropzone").hidden = !fileMode;
  $("#source-file").disabled = !fileMode;
  $("#source-file").accept = type === "pdf" ? ".pdf,application/pdf" : type === "youtube" ? "audio/*,video/*,.mkv,.opus" : "";
  $("#form-label").innerHTML = `<label for="${fileMode ? "source-file" : "source-url"}">${fileMode && type !== "pdf" ? (type === "youtube" ? "Audio or video file" : "Code file") : meta.label}</label>`;
  $("#file-label").textContent = state.file?.name || (type === "pdf" ? "Choose a PDF or drop it here" : (type === "youtube" ? "Choose media or drop it here" : "Choose a code file or drop it here"));
  $("#source-hint").innerHTML = `${icon("info")} ${state.upload ? (type === "youtube" ? "Upload a local recording up to 100 MB and two hours." : "Upload a UTF-8 source file up to 200 KB.") : meta.hint}`;
  $("#toggle-upload").hidden = !["youtube", "github"].includes(type);
  $("#toggle-upload").textContent = type === "youtube" ? (state.upload ? "Use a YouTube link" : "Upload audio or video") : (state.upload ? "Use a GitHub link" : "Upload a code file");
  showError("#form-error");
  if (moveFocus) $(`#tab-${type}`).focus();
}

function formatDate(date) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(date));
}

function sourceRow(item) {
  return `<button class="source-row" data-open="${esc(item.id)}">
    <span class="source-square ${esc(item.kind)}">${icon(types[item.kind]?.icon || "file")}</span>
    <span class="row-copy"><strong>${esc(item.title)}</strong><small>${esc(labelName(item.kind))} · ${formatDate(item.created)}</small></span>
    <span class="state-label ${esc(item.status)}">${{ ready: "Ready", failed: "Needs attention", queued: "Queued", processing: "Processing" }[item.status]}</span>
    <span class="row-chevron">${icon("chevron")}</span></button>`;
}

function emptyState(title, text) {
  return `<div class="empty-state"><span>${icon("inbox")}</span><strong>${title}</strong><p>${text}</p></div>`;
}

function renderLibrary() {
  $("#library-count").textContent = state.library.length;
  $("#recent-list").innerHTML = state.library.slice(0, 3).map(sourceRow).join("") ||
    emptyState("Your recent sources will appear here", "Add a link or try an example to get started.");
  const query = $("#library-search").value.trim().toLowerCase();
  const items = state.library.filter((item) => (state.filter === "all" || item.kind === state.filter) &&
    (!query || `${item.title} ${item.url} ${item.filename}`.toLowerCase().includes(query)));
  $("#library-list").innerHTML = items.map(sourceRow).join("") ||
    emptyState("No sources found", "Add a new source or change the search filters.");
}

async function refreshLibrary() {
  try {
    state.library = await api("/api/sources");
    renderLibrary();
  } catch (error) {
    toast(error.message);
  }
}

function page(pageName, crumb) {
  state.page = pageName;
  ids.forEach((id) => { document.getElementById(id).hidden = id !== `${pageName}-view`; });
  $("#breadcrumb-page").textContent = crumb;
  document.querySelectorAll(".sidebar .nav-item").forEach((item) => {
    const match = item.dataset.sourceNav ? pageName === "library" && state.filter === item.dataset.sourceNav :
      item.dataset.nav === (pageName === "detail" ? "library" : pageName) && (pageName !== "library" || state.filter === "all");
    item.classList.toggle("selected", match);
    if (match) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  $("#sidebar").classList.remove("open");
  $("#menu-toggle").setAttribute("aria-expanded", "false");
}

function navigate(hash) {
  const route = hash ? `#${hash}` : "";
  if (location.hash === route) routePage();
  else location.hash = route;
}

let focusAfterRoute;
function focusNew() {
  focusAfterRoute = () => {
    $("#add-panel").scrollIntoView({ block: "center" });
    $(state.type === "pdf" || state.upload ? "#source-file" : "#source-url").focus({ preventScroll: true });
  };
  navigate("");
}

function routePage() {
  clearTimeout(state.poll);
  const [view, arg] = location.hash.slice(1).split("/");
  if (view === "source" && /^[a-f0-9]{24}$/.test(arg || "")) {
    const changed = state.id !== arg || state.page !== "detail";
    state.id = arg;
    if (changed) {
      state.tab = "overview";
      state.nodeId = null;
      state.detail = null;
      $("#detail-view").innerHTML = '<div class="panel process-panel"><h2>Opening source</h2><div class="loading-track"></div></div>';
      scrollTo(0, 0);
    }
    page("detail", "Source");
    loadDetail(arg);
  } else if (view === "library") {
    state.id = null;
    state.filter = types[arg] ? arg : "all";
    $("#library-filter").value = state.filter;
    page("library", labelName(state.filter) === "Source" ? "Source library" : labelName(state.filter));
    renderLibrary();
    refreshLibrary();
  } else {
    state.id = null;
    page("home", "Overview");
    renderLibrary();
    refreshLibrary();
  }
  if (focusAfterRoute) {
    const action = focusAfterRoute;
    focusAfterRoute = null;
    action();
  }
}

$("#ingest-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const kind = state.type;
  const withFile = kind === "pdf" || state.upload;
  const url = $("#source-url").value.trim();
  if (withFile ? !state.file : !url) {
    showError("#form-error", withFile ? "Choose a file to analyze." : "Paste a URL to analyze.");
    return;
  }
  const body = new FormData();
  body.set("kind", kind);
  if (withFile) body.set("file", state.file);
  else body.set("url", url);
  const button = $("#analyze-button");
  button.disabled = true;
  button.innerHTML = `${icon("spark")} Submitting…`;
  showError("#form-error");
  try {
    const result = await api("/api/sources", { method: "POST", body });
    $("#source-url").value = "";
    $("#source-file").value = "";
    state.file = null;
    setType(kind);
    await refreshLibrary();
    navigate(`source/${result.id}`);
  } catch (error) {
    showError("#form-error", error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = `${icon("spark")} Analyze source`;
  }
});

$("#source-file").addEventListener("change", (event) => {
  state.file = event.target.files[0] || null;
  setType(state.type);
});
const drop = $("#dropzone");
drop.addEventListener("dragover", (event) => { event.preventDefault(); drop.classList.add("drag"); });
drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
drop.addEventListener("drop", (event) => {
  event.preventDefault();
  drop.classList.remove("drag");
  if (event.dataTransfer.files[0]) {
    state.file = event.dataTransfer.files[0];
    setType(state.type);
  }
});
$("#toggle-upload").addEventListener("click", () => {
  state.upload = !state.upload;
  state.file = null;
  $("#source-file").value = "";
  setType(state.type);
});
$("#source-tabs").addEventListener("keydown", (event) => {
  const keys = Object.keys(types);
  const index = keys.indexOf(state.type);
  const choices = { ArrowRight: (index + 1) % keys.length, ArrowLeft: (index + keys.length - 1) % keys.length, Home: 0, End: keys.length - 1 };
  if (event.key in choices) {
    event.preventDefault();
    setType(keys[choices[event.key]], true);
  }
});

function externalUrl(raw) {
  try {
    const href = new URL(raw);
    return ["http:", "https:"].includes(href.protocol) ? href.href : "";
  } catch { return ""; }
}

function refs(items) {
  const references = items.filter((id) => /^S\d+$/.test(id));
  return references.length ? `<span class="ref-group">${references.map((id) =>
    `<button class="cite" data-cite="${id}" aria-label="Open citation ${id.slice(1)}">${id.slice(1)}</button>`).join("")}</span>` : "";
}

function passageText(text, code, className = "") {
  return code ? `<pre class="${className}">${esc(text)}</pre>` : `<p class="${className}">${esc(text)}</p>`;
}

function linkFor(passage) {
  const href = externalUrl(passage.url);
  return href ? `<a class="source-link" href="${esc(href)}" target="_blank" rel="noopener noreferrer">Open in original source</a>` : "";
}

function showCitation(id) {
  const passage = state.detail?.result?.passages.find((value) => value.id === id);
  if (!passage) return;
  const dialog = $("#citation-dialog");
  const code = Boolean(state.detail.result.code);
  dialog.innerHTML = `<form method="dialog" class="dialog-heading"><h2>${esc(passage.label)}</h2><button class="icon-button" aria-label="Close">${icon("close")}</button></form>
    ${passageText(passage.text, code, code ? "dialog-passage code-passage" : "dialog-passage")}${linkFor(passage)}`;
  dialog.showModal();
}

function sourceHeading(record, ready) {
  const url = externalUrl(record.url);
  return `<header class="source-header">
    <button class="text-button back-button" data-nav="library">${icon("chevron")} Source library</button>
    <div class="source-title-row">
      <div class="source-title-group"><span class="source-square ${esc(record.kind)}">${icon(types[record.kind].icon)}</span>
        <div><h1>${esc(record.title)}</h1><p>${esc(labelName(record.kind))}${ready ? ` · ${esc(record.result.method)} · ${record.result.passages.length} passages` : ""}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Original source</a>` : ""}</p></div>
      </div>
      <div class="source-actions">
        ${ready ? `<a class="secondary" href="/api/sources/${record.id}/summary.txt">${icon("download")} Summary</a>` : ""}
        ${ready || record.status === "failed" ? `<button class="icon-button" data-delete aria-label="Delete source" title="Delete source">${icon("trash")}</button>` : ""}
      </div>
    </div></header>`;
}

function renderDetail(record) {
  const root = $("#detail-view");
  $("#breadcrumb-page").textContent = record.title;
  if (record.status !== "ready") {
    const failed = record.status === "failed";
    root.innerHTML = `${sourceHeading(record, false)}<div class="panel process-panel" role="status">
      <span class="section-icon violet">${icon(failed ? "info" : "spark")}</span>
      <h2>${failed ? "This source needs attention" : "Analyzing your source"}</h2><p>${esc(record.error || record.stage)}</p>
      ${failed ? `<button class="primary" data-retry>${icon("retry")} Retry source</button>${record.kind === "youtube" && !record.filename ? ` <button class="secondary" data-upload-media>${icon("upload")} Upload audio or video</button>` : ""}` : '<div class="loading-track"></div><p>You can open other sources while this runs.</p>'}
      </div>`;
    return;
  }
  const tabs = [["overview", "Summary"], ["passages", "Source text"]];
  if (record.result.code) tabs.push(["graph", "Code map"], ["interview", "Interview prep"]);
  root.innerHTML = `${sourceHeading(record, true)}<div class="reading-layout">
      <section class="panel reading-panel"><nav class="detail-tabs" aria-label="Source views">${tabs.map(([tab, title]) =>
        `<button data-tab="${tab}" aria-pressed="${state.tab === tab}">${title}</button>`).join("")}</nav><div id="detail-content" class="detail-content"></div></section>
      <section class="panel chat-panel" aria-labelledby="chat-title">
        <div class="chat-head"><span class="section-icon violet">${icon("chat")}</span><div><h2 id="chat-title">Ask this source</h2><p>Answers are grounded in this source.</p></div></div>
        <div class="chat-log" id="chat-log" role="log" aria-live="polite"></div>
        <form class="chat-form" id="chat-form"><label class="input-wrap"><span class="sr-only">Ask a question</span><input id="question" placeholder="Ask a question about this source…" maxlength="1000" required></label><button class="primary send-button" type="submit" aria-label="Send question">${icon("send")}</button></form>
        <p id="chat-error" class="chat-error inline-error" role="alert" hidden></p>
      </section></div>`;
  renderTab();
  renderChat();
  $("#chat-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("#question");
    if (input.value.trim().length < 2) {
      showError("#chat-error", "Enter a question with at least two characters.");
      return;
    }
    const question = input.value;
    input.value = "";
    ask(question);
  });
}

function renderTab() {
  const result = state.detail.result;
  const panel = $("#detail-content");
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    const active = tab.dataset.tab === state.tab;
    tab.classList.toggle("selected", active);
    tab.setAttribute("aria-pressed", active);
  });
  if (state.tab === "passages") {
    panel.innerHTML = `<h2>Source passages</h2><p class="graph-meta">Open a passage to see the evidence used in answers.</p>
      <div class="passages">${result.passages.map((p) => `<details class="passage"><summary>${esc(p.label)}</summary>${passageText(p.text, Boolean(result.code))}${linkFor(p)}</details>`).join("")}</div>`;
  } else if (state.tab === "graph") {
    panel.innerHTML = `<h2>Code map</h2><p class="graph-meta">${result.code.nodes.length} sections across ${result.code.line_count} lines. Select a section to read how it works.</p>
      <div class="graph-scroller"><div class="graph-board" id="graph-board"></div></div>
      <p class="graph-meta">Solid links connect continued sections. Dashed links indicate possible calls identified in the file.</p><div id="graph-selection" class="graph-selection"></div>`;
    renderGraph();
  } else if (state.tab === "interview") {
    panel.innerHTML = `<h2>Interview prep</h2><p class="graph-meta">Practice explaining the code out loud, then check the suggested answer.</p>
      <div class="passages">${result.code.interview.map((item) => `<details class="interview-item"><summary>${esc(item.question)}</summary><p>${esc(item.answer)} ${refs(item.citations)}</p></details>`).join("")}</div>`;
  } else {
    const summary = result.summary;
    panel.innerHTML = `${result.notes.map((note) => `<p class="reading-note">${esc(note)}</p>`).join("")}
      <div class="summary-title"><span class="section-icon violet">${icon("spark")}</span><h2>Overview</h2><span class="mode-tag">${esc(summary.mode)}</span></div>
      <p class="summary-text">${esc(summary.overview)} ${refs(summary.citations)}</p>
      ${summary.items.length ? `<h3 class="takeaway-heading">Key takeaways</h3><ul class="summary-items">${summary.items.map((item) => `<li>${esc(item.text)} ${refs(item.citations)}</li>`).join("")}</ul>` : ""}`;
  }
}

function renderGraph() {
  const code = state.detail.result.code;
  const board = $("#graph-board");
  const width = Math.max(430, board.clientWidth);
  const columns = width >= 620 ? 3 : 2;
  const step = width / columns;
  const rowHeight = 70;
  const height = Math.ceil(code.nodes.length / columns) * rowHeight + 15;
  const nodes = new Map();
  const fragment = document.createDocumentFragment();
  const canvas = document.createElement("canvas");
  // Cap each backing canvas to browser-safe dimensions; repeat vertically for long files.
  board.style.height = `${height}px`;
  code.nodes.forEach((node, index) => {
    const point = { x: (index % columns) * step + 12, y: Math.floor(index / columns) * rowHeight + 13,
      w: step - 24, h: 46 };
    nodes.set(node.id, point);
    const button = document.createElement("button");
    button.className = "graph-node";
    button.dataset.node = node.id;
    button.title = `${node.name} · ${node.label}`;
    button.style.cssText = `left:${point.x}px;top:${point.y}px;width:${point.w}px;height:${point.h}px`;
    button.innerHTML = `<strong>${esc(node.name)}</strong><small>${esc(node.label)}</small>`;
    fragment.append(button);
  });
  for (let y = 0; y < height; y += 3000) {
    const sheet = canvas.cloneNode();
    sheet.width = width;
    sheet.height = Math.min(3000, height - y);
    sheet.style.top = `${y}px`;
    sheet.setAttribute("aria-hidden", "true");
    const context = sheet.getContext("2d");
    if (!context) continue;
    context.translate(0, -y);
    for (const edge of code.edges) {
      const from = nodes.get(edge.from);
      const to = nodes.get(edge.to);
      if (Math.max(from.y, to.y) + 65 < y || Math.min(from.y, to.y) > y + sheet.height + 65) continue;
      context.strokeStyle = edge.kind === "continues" ? "#8e6bcf" : "#a996cc";
      context.lineWidth = 1.35;
      context.setLineDash(edge.kind === "continues" ? [] : [4, 3]);
      context.beginPath();
      context.moveTo(from.x + from.w / 2, from.y + from.h / 2);
      const via = Math.max(from.y, to.y) + 57;
      context.bezierCurveTo(from.x + from.w + 12, via, to.x - 12, via, to.x + to.w / 2, to.y + to.h / 2);
      context.stroke();
    }
    board.append(sheet);
  }
  board.append(fragment);
  selectGraphNode(state.nodeId || code.nodes[0].id);
}

function selectGraphNode(id, scroll = false) {
  const code = state.detail.result.code;
  const node = code.nodes.find((item) => item.id === id);
  if (!node) return;
  state.nodeId = id;
  const passage = state.detail.result.passages.find((item) => item.id === node.passage);
  const links = code.edges.filter((edge) => edge.from === id || edge.to === id);
  document.querySelectorAll(".graph-node").forEach((button) => button.setAttribute("aria-pressed", button.dataset.node === id));
  if (scroll) {
    const board = $("#graph-board");
    const button = board.querySelector(`[data-node="${id}"]`);
    board.parentElement.scrollTo({ top: Math.max(0, button.offsetTop - 15), left: Math.max(0, button.offsetLeft - 15) });
  }
  $("#graph-selection").innerHTML = `<div class="passage"><h3>${esc(node.name)}</h3><p>${esc(node.kind)} · ${esc(node.label)} · ${esc(node.mode)} ${refs([node.passage])}</p>
    <p>${esc(node.explanation)}</p>${links.length ? `<div class="graph-links">${links.map((edge) => {
      const target = code.nodes.find((item) => item.id === (edge.from === id ? edge.to : edge.from));
      const relation = edge.kind === "continues" ? (edge.from === id ? "Continues in" : "Continues") : (edge.from === id ? "May call" : "May be called by");
      return `<button class="secondary" data-jump-node="${target.id}">${relation} ${esc(target.name)}</button>`;
    }).join("")}</div>` : ""}<details><summary>Read these lines</summary>${passageText(passage.text, true)}${linkFor(passage)}</details></div>`;
}

function renderChat(pendingQuestion = "") {
  const log = $("#chat-log");
  if (!log) return;
  const history = state.detail.history || [];
  const intro = `<div class="chat-intro"><span class="section-icon violet">${icon("chat")}</span><h3>Start with a question</h3>
    <p>Ask for a plain-language explanation or details you want to revisit.</p><div class="suggestions">
    ${(state.detail.result.code ? ["What is the purpose of this file?", "What are the key takeaways?"] : ["What is the main idea?", "What are the key takeaways?"]).map((question) =>
      `<button data-question="${esc(question)}">${esc(question)}</button>`).join("")}</div></div>`;
  log.innerHTML = history.map((item) => `<div class="message question">${esc(item.question)}</div><div class="message answer">${esc(item.answer)} ${refs(item.citations)}</div>`).join("") ||
    (pendingQuestion || state.pending.has(state.id) ? "" : intro);
  if (pendingQuestion) log.insertAdjacentHTML("beforeend", `<div class="message question">${esc(pendingQuestion)}</div>`);
  if (state.pending.has(state.id)) log.insertAdjacentHTML("beforeend", '<div class="message answer">Looking for evidence…</div>');
  $("#chat-form button").disabled = state.pending.has(state.id);
  log.scrollTop = log.scrollHeight;
}

async function ask(question) {
  const id = state.id;
  if (!id || state.pending.has(id)) return;
  state.pending.add(id);
  showError("#chat-error");
  renderChat(question);
  let answer;
  let errorMessage = "";
  try {
    answer = await api(`/api/sources/${id}/questions`, post({ question }));
  } catch (error) {
    errorMessage = error.message;
  } finally {
    state.pending.delete(id);
  }
  if (state.id !== id || !state.detail?.result) return;
  if (answer) state.detail.history = [...(state.detail.history || []), answer];
  renderChat();
  if (errorMessage) {
    $("#question").value = question;
    showError("#chat-error", errorMessage);
  }
}

async function loadDetail(id) {
  try {
    const record = await api(`/api/sources/${id}`);
    if (state.id !== id) return;
    const prev = state.detail;
    state.detail = record;
    if (!prev || prev.status !== record.status || prev.stage !== record.stage) renderDetail(record);
    if (["queued", "processing"].includes(record.status)) {
      state.poll = setTimeout(() => loadDetail(id), 1000);
    } else {
      refreshLibrary();
    }
  } catch (error) {
    if (state.id === id) $("#detail-view").innerHTML = `<div class="panel process-panel"><h2>Could not open source</h2><p>${esc(error.message)}</p><button class="secondary" data-nav="library">Source library</button></div>`;
  }
}

async function tryDemo(button) {
  button.disabled = true;
  try {
    const result = await api("/api/samples", post({ demo: button.dataset.demo }));
    await refreshLibrary();
    navigate(`source/${result.id}`);
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
}

function confirmDeletion() {
  const dialog = $("#delete-dialog");
  const id = state.id;
  dialog.returnValue = "cancel";
  dialog.showModal();
  dialog.addEventListener("close", async () => {
    if (dialog.returnValue !== "delete") return;
    try {
      await api(`/api/sources/${id}`, { method: "DELETE" });
      await refreshLibrary();
      if (state.id === id) navigate("library");
      toast("Source deleted.");
    } catch (error) {
      toast(error.message);
    }
  }, { once: true });
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const data = button.dataset;
  if (data.kind) setType(data.kind);
  else if (data.nav) navigate(data.nav === "home" ? "" : "library");
  else if (data.sourceNav) navigate(`library/${data.sourceNav}`);
  else if (data.open) navigate(`source/${data.open}`);
  else if (data.demo) tryDemo(button);
  else if (data.tab) { state.tab = data.tab; renderTab(); }
  else if (data.cite) showCitation(data.cite);
  else if (data.node || data.jumpNode) selectGraphNode(data.node || data.jumpNode, Boolean(data.jumpNode));
  else if (data.question) ask(data.question);
  else if (data.delete !== undefined) confirmDeletion();
  else if (data.uploadMedia !== undefined) {
    setType("youtube");
    state.upload = true;
    setType("youtube");
    focusNew();
  } else if (data.retry !== undefined) {
    const id = state.id;
    button.disabled = true;
    try {
      await api(`/api/sources/${id}/retry`, { method: "POST" });
      if (state.id === id) loadDetail(id);
    } catch (error) {
      toast(error.message);
      button.disabled = false;
    }
  }
});

$("#library-search").addEventListener("input", renderLibrary);
$("#library-filter").addEventListener("change", (event) => navigate(event.target.value === "all" ? "library" : `library/${event.target.value}`));
$("#sidebar-add").addEventListener("click", focusNew);
$("#library-add").addEventListener("click", focusNew);
function focusSearch() {
  focusAfterRoute = () => $("#library-search").focus();
  navigate("library");
}
$("#search-shortcut").addEventListener("click", focusSearch);
$("#help-button").addEventListener("click", () => $("#help-dialog").showModal());
$("#menu-toggle").addEventListener("click", () => {
  const open = $("#sidebar").classList.toggle("open");
  $("#menu-toggle").setAttribute("aria-expanded", open);
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    focusSearch();
  }
});
let resizing;
window.addEventListener("resize", () => {
  clearTimeout(resizing);
  resizing = setTimeout(() => {
    if (state.tab === "graph" && $("#graph-board")) renderTab();
  }, 160);
});
window.addEventListener("hashchange", routePage);

async function initialize() {
  setType("website");
  try {
    const health = await api("/api/health");
    $("#ai-label").textContent = health.ai_enabled ? `${health.ai_mode || "AI provider"} configured` : "Extractive mode";
  } catch {
    $("#ai-label").textContent = "Workspace service unavailable";
  }
  routePage();
}

initialize();
