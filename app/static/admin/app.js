const CUSTOM_MODEL_VALUE = "__custom__";

/** Ordered library source ids attached while the agent dialog is open. */
let draftAttachedIds = [];
/** Draft while the data-source dialog is open. */
let draftLibrarySource = null;
/** EasyMDE instances for prompt / source description fields. */
const promptEditors = { system: null, default: null, sourceDescription: null };

/** Draft avatar while the agent dialog is open. */
let draftAvatar = {
  preset: null,
  url: null,
  file: null,
  objectUrl: null,
  clearImage: false,
};

const AVATAR_PRESETS = [
  { id: "moss", emoji: "🌿", label: "Moss" },
  { id: "signal", emoji: "⚡", label: "Signal" },
  { id: "sky", emoji: "✦", label: "Sky" },
  { id: "coral", emoji: "◈", label: "Coral" },
  { id: "violet", emoji: "◇", label: "Violet" },
  { id: "sand", emoji: "◎", label: "Sand" },
];

/** In-flight / last result for model dropdown fetches. */
const modelFetchState = {
  token: 0,
  models: [],
  source: null,
  error: null,
  loading: false,
};

/** Searchable model combobox UI state. */
const modelComboState = {
  open: false,
  activeIndex: -1,
  filtered: [],
  selectedId: null,
  query: "",
};

const CRON_PRESETS = {
  every_minute: "* * * * *",
  every_5: "*/5 * * * *",
  every_15: "*/15 * * * *",
  hourly: "0 * * * *",
};

const WEEKDAY_LABELS = {
  0: "Sun",
  1: "Mon",
  2: "Tue",
  3: "Wed",
  4: "Thu",
  5: "Fri",
  6: "Sat",
};

const WEEKDAY_ORDER = ["1", "2", "3", "4", "5", "6", "0"];

const _htmlBlobUrls = new Set();

const state = {
  view: "agents",
  agents: [],
  sources: [],
  agentTemplates: [],
  selectedAgentId: null,
  selectedSourceId: null,
  logs: [],
  selectedExecutionId: null,
  selectedExecution: null,
  health: null,
  editingAgentId: null,
  editingSourceId: null,
  runAgentId: null,
  pollTimer: null,
  activityPollTimer: null,
  activityItems: [],
  activityCount: 0,
  attachFilter: "",
  chatAgentId: null,
  chatOpenedFrom: "agents",
  chatId: null,
  chatMessages: [],
  chatAttachments: [],
  chatSending: false,
  chatAbortController: null,
  chatStreamingText: "",
  chatStreamStarted: false,
  chatStreamGeneratingHtml: false,
  chatStreamTools: [],
  allSessions: [],
  /** "all" | "agent" — sidebar agent-scope filter. */
  chatSessionsFilter: "all",
  /** "all" | "runs" | "chats" — session type filter. */
  chatSessionsKind: "all",
  /** Free-text search over session title / agent name. */
  chatSessionsQuery: "",
  /** "newest" | "oldest" */
  chatSessionsSort: "newest",
  usage: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function toast(message, kind = "ok") {
  const el = $("#toast");
  el.hidden = false;
  el.className = `toast ${kind}`;
  el.textContent = message;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.hidden = true;
  }, 3200);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
    ...options,
  });
  if (res.status === 204) return null;
  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!res.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : Array.isArray(data?.detail)
          ? data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
          : res.statusText;
    const err = new Error(detail || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

/** Primary admin timestamp: d/m/y H:m (24h, no seconds). */
function fmtTime(value) {
  if (!value) return "—";
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    const d = date.getDate();
    const m = date.getMonth() + 1;
    const y = date.getFullYear();
    const h = String(date.getHours()).padStart(2, "0");
    const min = String(date.getMinutes()).padStart(2, "0");
    return `${d}/${m}/${y} ${h}:${min}`;
  } catch {
    return String(value);
  }
}

function fmtRelative(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const diffMs = Date.now() - date.getTime();
  const abs = Math.abs(diffMs);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  let label;
  if (abs < minute) label = "just now";
  else if (abs < hour) {
    const n = Math.round(abs / minute);
    label = `${n}m ago`;
  } else if (abs < day) {
    const n = Math.round(abs / hour);
    label = `${n}h ago`;
  } else if (abs < 7 * day) {
    const n = Math.round(abs / day);
    label = `${n}d ago`;
  } else {
    return fmtTime(value);
  }
  return label;
}

function formatDurationSeconds(total) {
  const s = Math.max(0, Math.floor(Number(total) || 0));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

/** Primary d/m/y H:m with optional muted relative secondary. */
function fmtTimePrimary(value, { relative = true } = {}) {
  if (!value) return "—";
  const primary = escapeHtml(fmtTime(value));
  if (!relative) return primary;
  const rel = fmtRelative(value);
  if (!rel || rel === "—" || rel === fmtTime(value)) return primary;
  return `${primary}<br /><span class="muted">${escapeHtml(rel)}</span>`;
}

function agentInitials(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase();
  return (parts[0].slice(0, 1) + parts[1].slice(0, 1)).toUpperCase();
}

function avatarPresetMeta(presetId) {
  return AVATAR_PRESETS.find((p) => p.id === presetId) || null;
}

/**
 * Render a circular agent avatar (image, preset emoji, or initials).
 * `agentOrName` may be an agent object or a plain name string.
 */
function renderAgentAvatar(agentOrName, { size = "" } = {}) {
  const agent =
    agentOrName && typeof agentOrName === "object" ? agentOrName : null;
  const name = agent ? agent.name : String(agentOrName || "");
  const sizeClass = size ? ` ${size}` : "";
  const initials = escapeHtml(agentInitials(name));
  const url = agent?.avatar_url || null;
  const preset = agent?.avatar_preset || null;
  const presetMeta = avatarPresetMeta(preset);

  if (url) {
    return `<span class="agent-avatar${sizeClass}" title="${escapeHtml(name)}"><img src="${escapeHtml(url)}" alt="" /></span>`;
  }
  if (presetMeta) {
    return `<span class="agent-avatar${sizeClass} preset-${escapeHtml(presetMeta.id)}" title="${escapeHtml(name)}"><span class="avatar-emoji">${presetMeta.emoji}</span></span>`;
  }
  return `<span class="agent-avatar${sizeClass}" title="${escapeHtml(name)}">${initials}</span>`;
}

function resetDraftAvatar() {
  if (draftAvatar.objectUrl) {
    URL.revokeObjectURL(draftAvatar.objectUrl);
  }
  draftAvatar = {
    preset: null,
    url: null,
    file: null,
    objectUrl: null,
    clearImage: false,
  };
}

function hydrateDraftAvatar(agent = null) {
  resetDraftAvatar();
  if (!agent) return;
  draftAvatar.preset = agent.avatar_preset || null;
  draftAvatar.url = agent.avatar_url || null;
}

function draftAvatarPreviewAgent(name) {
  const previewUrl = draftAvatar.objectUrl || (!draftAvatar.clearImage ? draftAvatar.url : null);
  return {
    name: name || "Agent",
    avatar_url: previewUrl,
    avatar_preset: previewUrl ? null : draftAvatar.preset,
  };
}

function mountAvatarHtml(el, html) {
  if (!el) return el;
  const wrap = document.createElement("div");
  wrap.innerHTML = html.trim();
  const next = wrap.firstElementChild;
  if (!next) return el;
  if (el.id) next.id = el.id;
  el.replaceWith(next);
  return next;
}

function renderAvatarEditor() {
  const preview = $("#agent-avatar-preview");
  const presetsEl = $("#agent-avatar-presets");
  const clearBtn = $("#agent-avatar-clear");
  const form = $("#agent-form");
  if (!preview || !presetsEl) return;

  const name = form?.name?.value?.trim() || "Agent";
  mountAvatarHtml(
    preview,
    renderAgentAvatar(draftAvatarPreviewAgent(name), { size: "lg" }),
  );

  const hasImage = Boolean(
    draftAvatar.objectUrl || (draftAvatar.url && !draftAvatar.clearImage),
  );
  if (clearBtn) {
    clearBtn.hidden = !hasImage && !draftAvatar.preset;
  }

  presetsEl.innerHTML = [
    `<button type="button" class="avatar-preset-btn initials-btn ${!draftAvatar.preset && !hasImage ? "active" : ""}" data-preset="" title="Initials" aria-label="Use initials">${escapeHtml(agentInitials(name))}</button>`,
    ...AVATAR_PRESETS.map(
      (p) =>
        `<button type="button" class="avatar-preset-btn ${draftAvatar.preset === p.id && !hasImage ? "active" : ""} preset-${p.id}" data-preset="${p.id}" title="${escapeHtml(p.label)}" aria-label="${escapeHtml(p.label)}">${p.emoji}</button>`,
    ),
  ].join("");

  $$("#agent-avatar-presets [data-preset]").forEach((btn) => {
    btn.onclick = () => {
      const preset = btn.dataset.preset || null;
      if (draftAvatar.objectUrl) {
        URL.revokeObjectURL(draftAvatar.objectUrl);
        draftAvatar.objectUrl = null;
      }
      draftAvatar.file = null;
      draftAvatar.clearImage = Boolean(draftAvatar.url);
      draftAvatar.preset = preset;
      const fileInput = $("#agent-avatar-file");
      if (fileInput) fileInput.value = "";
      renderAvatarEditor();
    };
  });
}

async function persistAgentAvatar(agentId) {
  if (draftAvatar.file) {
    const body = new FormData();
    body.append("file", draftAvatar.file);
    const res = await fetch(`/agents/${agentId}/avatar`, {
      method: "POST",
      body,
      headers: { Accept: "application/json" },
    });
    const text = await res.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { detail: text };
      }
    }
    if (!res.ok) {
      throw new Error(
        typeof data?.detail === "string" ? data.detail : res.statusText,
      );
    }
    return data;
  }
  if (draftAvatar.clearImage && draftAvatar.url && !draftAvatar.preset) {
    await api(`/agents/${agentId}/avatar`, { method: "DELETE" });
  }
  return null;
}

function confirmDialog({
  title = "Confirm",
  message,
  confirmLabel = "Delete",
  danger = true,
} = {}) {
  return new Promise((resolve) => {
    const dialog = $("#confirm-dialog");
    const form = $("#confirm-form");
    const titleEl = $("#confirm-dialog-title");
    const msgEl = $("#confirm-dialog-message");
    const okBtn = $("#confirm-dialog-ok");
    if (!dialog || !form || !msgEl) {
      resolve(window.confirm(message));
      return;
    }
    titleEl.textContent = title;
    msgEl.textContent = message;
    okBtn.textContent = confirmLabel;
    okBtn.className = danger ? "danger-btn" : "primary-btn";
    okBtn.value = "confirm";

    const onClose = () => {
      dialog.removeEventListener("close", onClose);
      resolve(dialog.returnValue === "confirm");
    };
    dialog.addEventListener("close", onClose);
    dialog.returnValue = "";
    dialog.showModal();
  });
}

function promptRenameDialog(currentTitle = "") {
  return new Promise((resolve) => {
    const dialog = $("#rename-dialog");
    const form = $("#rename-form");
    const input = $("#rename-input");
    if (!dialog || !form || !input) {
      resolve(window.prompt("Rename session", currentTitle));
      return;
    }
    input.value = currentTitle || "";
    const onClose = () => {
      dialog.removeEventListener("close", onClose);
      if (dialog.returnValue === "confirm") {
        resolve(input.value);
      } else {
        resolve(null);
      }
    };
    dialog.addEventListener("close", onClose);
    dialog.returnValue = "";
    dialog.showModal();
    requestAnimationFrame(() => {
      input.focus();
      input.select();
    });
  });
}

/** Display label for agents / templates: `{name} - {role}`. */
function formatAgentLabel(agentOrTemplate, fallback = "Unknown agent") {
  if (!agentOrTemplate) return fallback;
  const name = agentOrTemplate.name || fallback;
  const role = (agentOrTemplate.role || "").trim();
  return role ? `${name} - ${role}` : name;
}

function agentName(agentId) {
  const agent = state.agents.find((a) => a.id === agentId);
  return formatAgentLabel(agent);
}

function chatAgent() {
  return state.agents.find((a) => a.id === state.chatAgentId) || null;
}

/** When true, history updates are suppressed (route restore / popstate). */
let suppressUrlSync = false;

const ADMIN_VIEWS = new Set([
  "agents",
  "chat",
  "activity",
  "sources",
  "executions",
  "system",
]);

/**
 * Build the canonical admin path (+ query) for the current view/selections.
 * Examples:
 *   /admin/agents
 *   /admin/sources/{sourceId}
 *   /admin/chat/{agentId}/{chatId}
 *   /admin/executions?agent={agentId}
 */
function buildAdminUrl() {
  switch (state.view) {
    case "sources":
      return state.selectedSourceId
        ? `/admin/sources/${encodeURIComponent(state.selectedSourceId)}`
        : "/admin/sources";
    case "activity":
      return "/admin/activity";
    case "chat":
      if (state.chatAgentId && state.chatId) {
        return `/admin/chat/${encodeURIComponent(state.chatAgentId)}/${encodeURIComponent(state.chatId)}`;
      }
      if (state.chatAgentId) {
        return `/admin/chat/${encodeURIComponent(state.chatAgentId)}`;
      }
      return "/admin/chat";
    case "executions": {
      if (state.selectedAgentId) {
        return `/admin/executions?agent=${encodeURIComponent(state.selectedAgentId)}`;
      }
      return "/admin/executions";
    }
    case "system":
      return "/admin/system";
    case "agents":
    default:
      return "/admin/agents";
  }
}

function currentLocationKey() {
  return `${location.pathname}${location.search}`;
}

function syncUrl({ replace = false } = {}) {
  if (suppressUrlSync) return;
  const next = buildAdminUrl();
  if (currentLocationKey() === next) return;
  if (replace) {
    history.replaceState({ view: state.view }, "", next);
  } else {
    history.pushState({ view: state.view }, "", next);
  }
}

/**
 * Parse path-based admin routes under /admin/...
 * Supports:
 *   /admin/ | /admin/agents
 *   /admin/sources[/{id}]
 *   /admin/sessions → Chat (legacy redirect)
 *   /admin/chat[/{agentId}[/{chatId}]] or ?agent=[&kind=]
 *   /admin/executions[?agent=]
 *   /admin/system
 */
function parseAdminRoute() {
  const raw = location.pathname.replace(/\/+$/, "") || "/";
  let rest = "";
  if (raw === "/admin") rest = "";
  else if (raw.startsWith("/admin/")) rest = raw.slice("/admin/".length);
  else return { view: "agents", agentId: null, chatId: null, sourceId: null };

  const parts = rest.split("/").filter(Boolean).map((p) => {
    try {
      return decodeURIComponent(p);
    } catch {
      return p;
    }
  });
  const params = new URLSearchParams(location.search);
  const head = (parts[0] || "agents").toLowerCase();
  const kindParam = (params.get("kind") || params.get("filter") || "").toLowerCase();
  const sessionsKind =
    kindParam === "runs" || kindParam === "chats" || kindParam === "all"
      ? kindParam
      : null;

  if (!parts.length || head === "agents") {
    return { view: "agents", agentId: null, chatId: null, sourceId: null };
  }
  if (head === "sources") {
    return {
      view: "sources",
      agentId: null,
      chatId: null,
      sourceId: parts[1] || null,
    };
  }
  // Legacy Sessions URL → Chat (optional ?kind=runs|chats).
  if (head === "sessions") {
    return {
      view: "chat",
      agentId: null,
      chatId: null,
      sourceId: null,
      sessionsKind: sessionsKind || "all",
    };
  }
  // Legacy Reports gallery URL → Chat (reports are session-only).
  if (head === "reports") {
    return { view: "chat", agentId: null, chatId: null, sourceId: null };
  }
  if (head === "activity") {
    return { view: "activity", agentId: null, chatId: null, sourceId: null };
  }
  if (head === "chat") {
    return {
      view: "chat",
      agentId: parts[1] || params.get("agent") || null,
      chatId: parts[2] || null,
      sourceId: null,
      sessionsKind,
    };
  }
  if (head === "executions") {
    return {
      view: "executions",
      agentId: params.get("agent") || null,
      chatId: null,
      sourceId: null,
    };
  }
  if (head === "system") {
    return { view: "system", agentId: null, chatId: null, sourceId: null };
  }
  return { view: "agents", agentId: null, chatId: null, sourceId: null };
}

/** Apply route ids into state before data loads (view UI updated separately). */
function applyRouteIds(route) {
  if (route.view === "sources" && route.sourceId) {
    state.selectedSourceId = route.sourceId;
  }
  if (route.view === "executions" && route.agentId) {
    state.selectedAgentId = route.agentId;
  }
  if (route.view === "chat") {
    if (route.agentId) state.chatAgentId = route.agentId;
    if (route.chatId) state.chatId = route.chatId;
    if (
      route.sessionsKind === "all" ||
      route.sessionsKind === "runs" ||
      route.sessionsKind === "chats"
    ) {
      state.chatSessionsKind = route.sessionsKind;
    }
  }
}

/**
 * Restore view + deep selections after agents/sessions/sources are loaded.
 */
async function restoreFromRoute(route, { replaceUrl = false } = {}) {
  const view = ADMIN_VIEWS.has(route.view) ? route.view : "agents";
  suppressUrlSync = true;
  try {
    if (view === "chat") {
      state.chatOpenedFrom = "agents";
      if (route.agentId) {
        const agent = state.agents.find((a) => a.id === route.agentId);
        if (!agent) {
          toast("Agent from URL not found", "error");
          state.chatAgentId = null;
          prepareNewChatContext();
          setView("chat");
        } else {
          state.chatAgentId = agent.id;
          if (route.chatId) {
            prepareNewChatContext();
            setView("chat");
            await loadAllSessions().catch(() => {});
            await selectChat(route.chatId, { skipUrl: true });
          } else {
            // Agent selected, no session in URL — leave a blank/new context.
            prepareNewChatContext();
            setView("chat");
            await loadAllSessions().catch(() => {});
            renderChatPanel();
          }
        }
      } else {
        prepareNewChatContext();
        setView("chat");
        await loadAllSessions()
          .then(() => render())
          .catch((e) => toast(e.message, "error"));
      }
    } else if (view === "sources") {
      if (
        route.sourceId &&
        state.sources.some((s) => s.id === route.sourceId)
      ) {
        state.selectedSourceId = route.sourceId;
      }
      setView("sources");
    } else if (view === "executions") {
      if (route.agentId && state.agents.some((a) => a.id === route.agentId)) {
        state.selectedAgentId = route.agentId;
      }
      setView("executions");
      await refreshSelectedLogs();
    } else if (view === "activity") {
      setView("activity");
      await loadActivity().catch((e) => toast(e.message, "error"));
    } else {
      setView(view);
    }
  } finally {
    suppressUrlSync = false;
  }
  syncUrl({ replace: replaceUrl });
}

async function onPopState() {
  const route = parseAdminRoute();
  applyRouteIds(route);
  try {
    await restoreFromRoute(route, { replaceUrl: true });
  } catch (err) {
    toast(err.message || "Failed to restore route", "error");
  }
}

function setView(view, { skipUrl = false } = {}) {
  state.view = view;
  $$(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });
  $$(".view").forEach((section) => {
    section.classList.toggle("active", section.id === `view-${view}`);
  });
  const agent = chatAgent();
  const titles = {
    agents: ["Agents", "Create, configure, and run agents on this harness."],
    chat: agent
      ? ["Chat", formatAgentLabel(agent)]
      : ["Chat", "Pick an agent or open a session to start a conversation."],
    activity: [
      "Activity",
      "In-flight agent runs and chat streams on this harness.",
    ],
    sources: [
      "Data sources",
      "Library of SQL, NoSQL, and file sources agents can attach.",
    ],
    executions: ["Executions", "Inspect runs, tool traces, and HTML reports."],
    system: ["System", "Harness health, usage, and service status."],
  };
  const [title, sub] = titles[view] || ["Console", ""];
  $("#view-title").textContent = title;
  $("#view-sub").textContent = sub;
  renderTopActions();
  render();
  if (!skipUrl) syncUrl();
}

function renderTopActions() {
  const box = $("#top-actions");
  if (state.view === "agents") {
    box.innerHTML = `<button type="button" class="primary-btn" id="btn-new-agent">New agent</button>`;
    $("#btn-new-agent").onclick = () => openAgentDialog();
  } else if (state.view === "chat") {
    box.innerHTML = `<button type="button" class="ghost-btn" id="btn-chat-back-agents">← Agents</button>`;
    $("#btn-chat-back-agents").onclick = () => setView("agents");
  } else if (state.view === "activity") {
    box.innerHTML = `<button type="button" class="ghost-btn" id="btn-reload-activity">Reload</button>`;
    $("#btn-reload-activity").onclick = () =>
      loadActivity()
        .then(() => render())
        .catch((e) => toast(e.message, "error"));
  } else if (state.view === "sources") {
    box.innerHTML = `<button type="button" class="primary-btn" id="btn-new-source">New data source</button>`;
    $("#btn-new-source").onclick = () => openSourceDialog();
  } else if (state.view === "executions") {
    box.innerHTML = `<button type="button" class="ghost-btn" id="btn-reload-logs">Reload logs</button>`;
    $("#btn-reload-logs").onclick = () => refreshSelectedLogs();
  } else {
    box.innerHTML = "";
  }
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function ensureMonthdayGrid() {
  const grid = $("#cron-monthday-grid");
  if (!grid || grid.childElementCount) return;
  grid.innerHTML = Array.from({ length: 31 }, (_, i) => {
    const day = String(i + 1);
    const checked = day === "1" ? " checked" : "";
    return `<label class="day-check"><input type="checkbox" name="cron_monthday" value="${day}"${checked} /> ${day}</label>`;
  }).join("");
}

function parseIntList(field, { min, max }) {
  if (!field || field === "*") return null;
  const parts = field.split(",").map((p) => p.trim()).filter(Boolean);
  if (!parts.length) return null;
  const values = [];
  for (const part of parts) {
    if (!/^\d{1,2}$/.test(part)) return null;
    const n = Number(part);
    if (n < min || n > max) return null;
    values.push(String(n));
  }
  return [...new Set(values)];
}

function sortWeekdays(days) {
  return [...days].sort(
    (a, b) => WEEKDAY_ORDER.indexOf(a) - WEEKDAY_ORDER.indexOf(b),
  );
}

function sortMonthdays(days) {
  return [...days].sort((a, b) => Number(a) - Number(b));
}

function getCheckedValues(name) {
  return $$(`input[name="${name}"]:checked`).map((el) => el.value);
}

function setCheckedValues(name, values, { fallback } = {}) {
  const set = new Set((values || []).map(String));
  const inputs = $$(`input[name="${name}"]`);
  inputs.forEach((input) => {
    input.checked = set.has(input.value);
  });
  if (!inputs.some((input) => input.checked) && fallback != null) {
    const fb = inputs.find((input) => input.value === String(fallback));
    if (fb) fb.checked = true;
  }
}

function parseCronSchedule(cron) {
  if (!cron || !String(cron).trim()) {
    return { preset: "off" };
  }
  const value = String(cron).trim();
  for (const [preset, expr] of Object.entries(CRON_PRESETS)) {
    if (expr === value) return { preset };
  }

  const parts = value.split(/\s+/);
  if (parts.length === 5) {
    const [minute, hour, dom, month, dow] = parts;
    if (/^\d{1,2}$/.test(minute) && /^\d{1,2}$/.test(hour) && month === "*") {
      const time = `${pad2(hour)}:${pad2(minute)}`;
      if (dom === "*" && dow === "*") {
        return { preset: "daily", time };
      }
      const weekdays = parseIntList(dow, { min: 0, max: 6 });
      if (dom === "*" && weekdays) {
        return { preset: "weekly", time, weekdays: sortWeekdays(weekdays) };
      }
      const monthdays = parseIntList(dom, { min: 1, max: 31 });
      if (dow === "*" && monthdays) {
        return {
          preset: "monthly",
          time,
          monthdays: sortMonthdays(monthdays),
        };
      }
    }
  }
  return { preset: "custom", custom: value };
}

function buildCronFromUi() {
  const preset = $("#cron-preset").value;
  if (preset === "off") return null;
  if (CRON_PRESETS[preset]) return CRON_PRESETS[preset];

  if (preset === "daily") {
    const [hh, mm] = ($("#cron-time").value || "09:00").split(":");
    return `${Number(mm)} ${Number(hh)} * * *`;
  }

  if (preset === "weekly") {
    const days = sortWeekdays(getCheckedValues("cron_weekday"));
    if (!days.length) return null;
    const [hh, mm] = ($("#cron-weekly-time").value || "09:00").split(":");
    return `${Number(mm)} ${Number(hh)} * * ${days.join(",")}`;
  }

  if (preset === "monthly") {
    const days = sortMonthdays(getCheckedValues("cron_monthday"));
    if (!days.length) return null;
    const [hh, mm] = ($("#cron-monthly-time").value || "09:00").split(":");
    return `${Number(mm)} ${Number(hh)} ${days.join(",")} * *`;
  }

  const custom = $("#cron-custom").value.trim();
  return custom || null;
}

function describeCron(cron, { uiHint = false } = {}) {
  if (!cron) {
    if (uiHint) {
      const preset = $("#cron-preset")?.value;
      if (preset === "weekly") return "weekly (select at least one day)";
      if (preset === "monthly") return "monthly (select at least one day)";
    }
    return "off";
  }
  const parsed = parseCronSchedule(cron);
  switch (parsed.preset) {
    case "every_minute":
      return "every minute";
    case "every_5":
      return "every 5 minutes";
    case "every_15":
      return "every 15 minutes";
    case "hourly":
      return "hourly (at :00)";
    case "daily":
      return `daily at ${parsed.time} UTC`;
    case "weekly": {
      const labels = (parsed.weekdays || [])
        .map((d) => WEEKDAY_LABELS[d] || d)
        .join(", ");
      return `${labels || "weekly"} at ${parsed.time} UTC`;
    }
    case "monthly": {
      const days = (parsed.monthdays || []).join(", ");
      return `monthly on ${days || "—"} at ${parsed.time} UTC`;
    }
    case "custom":
      return `custom · ${cron}`;
    default:
      return cron;
  }
}

function syncCronUiVisibility() {
  ensureMonthdayGrid();
  const preset = $("#cron-preset").value;
  $("#cron-daily-wrap").hidden = preset !== "daily";
  $("#cron-weekly-wrap").hidden = preset !== "weekly";
  $("#cron-monthly-wrap").hidden = preset !== "monthly";
  $("#cron-custom-wrap").hidden = preset !== "custom";
  if (preset === "weekly" && !getCheckedValues("cron_weekday").length) {
    setCheckedValues("cron_weekday", ["1"]);
  }
  if (preset === "monthly" && !getCheckedValues("cron_monthday").length) {
    setCheckedValues("cron_monthday", ["1"]);
  }
  const cron = buildCronFromUi();
  $("#cron-preview").textContent = `Schedule: ${describeCron(cron, { uiHint: true })}`;
}

function applyCronToUi(cron) {
  ensureMonthdayGrid();
  const parsed = parseCronSchedule(cron);
  $("#cron-preset").value = parsed.preset;
  if (parsed.preset === "daily") {
    $("#cron-time").value = parsed.time || "09:00";
  } else if (parsed.preset === "weekly") {
    setCheckedValues("cron_weekday", parsed.weekdays || ["1"], { fallback: "1" });
    $("#cron-weekly-time").value = parsed.time || "09:00";
  } else if (parsed.preset === "monthly") {
    setCheckedValues("cron_monthday", parsed.monthdays || ["1"], { fallback: "1" });
    $("#cron-monthly-time").value = parsed.time || "09:00";
  } else if (parsed.preset === "custom") {
    $("#cron-custom").value = parsed.custom || cron || "";
  } else {
    $("#cron-custom").value = "";
  }
  syncCronUiVisibility();
}

function setModelFetchHint(message, { loading = false } = {}) {
  const hint = $("#model-fetch-hint");
  if (!hint) return;
  if (!message) {
    hint.hidden = true;
    hint.textContent = "";
    return;
  }
  hint.hidden = false;
  hint.textContent = message;
  hint.dataset.loading = loading ? "1" : "0";
}

function normalizeModelEntries(models) {
  return (models || []).map((m) =>
    typeof m === "string"
      ? { id: m, name: m }
      : { id: m.id, name: m.name || m.id },
  );
}

function modelMatchesQuery(model, query) {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    model.id.toLowerCase().includes(q) ||
    (model.name || "").toLowerCase().includes(q)
  );
}

function setModelComboOpen(open) {
  const input = $("#agent-model-input");
  const list = $("#agent-model-list");
  if (!input || !list) return;
  modelComboState.open = open;
  list.hidden = !open;
  input.setAttribute("aria-expanded", open ? "true" : "false");
  if (!open) {
    modelComboState.activeIndex = -1;
  }
}

function syncCustomModelWrap({ forceCustom = false } = {}) {
  const selectedId = modelComboState.selectedId;
  const useCustom =
    forceCustom ||
    selectedId === CUSTOM_MODEL_VALUE ||
    ($("#agent-model-input")?.value || "").trim() === "Custom model…";
  const wrap = $("#custom-model-wrap");
  const customInput = $("#agent-custom-model");
  if (!wrap || !customInput) return;
  wrap.hidden = !useCustom;
  customInput.required = useCustom;
  if (useCustom && selectedId && selectedId !== CUSTOM_MODEL_VALUE) {
    // Preserve a known-unknown model id into the custom field once.
    if (!customInput.value) customInput.value = selectedId;
  }
}

function selectModelOption(model, { keepOpen = false } = {}) {
  const input = $("#agent-model-input");
  if (!input) return;
  if (!model || model.id === CUSTOM_MODEL_VALUE) {
    modelComboState.selectedId = CUSTOM_MODEL_VALUE;
    input.value = "Custom model…";
    modelComboState.query = "";
    syncCustomModelWrap({ forceCustom: true });
    if (!keepOpen) setModelComboOpen(false);
    return;
  }
  modelComboState.selectedId = model.id;
  input.value = model.id;
  modelComboState.query = "";
  syncCustomModelWrap();
  if (!keepOpen) setModelComboOpen(false);
}

function renderModelListItems() {
  const list = $("#agent-model-list");
  if (!list) return;
  const items = modelComboState.filtered;
  if (!items.length) {
    list.innerHTML =
      '<li class="model-combobox-empty">No matches — choose Custom model… or keep typing an id</li>';
    return;
  }
  list.innerHTML = items
    .map((m, i) => {
      const isCustom = m.id === CUSTOM_MODEL_VALUE;
      const active = i === modelComboState.activeIndex;
      const name =
        !isCustom && m.name && m.name !== m.id
          ? `<span class="opt-name">${escapeHtml(m.name)}</span>`
          : "";
      return `<li class="model-combobox-option${
        isCustom ? " is-custom" : ""
      }" role="option" data-index="${i}" data-id="${escapeHtml(
        m.id,
      )}" aria-selected="${active ? "true" : "false"}"><span class="opt-id">${escapeHtml(
        isCustom ? "Custom model…" : m.id,
      )}</span>${name}</li>`;
    })
    .join("");
}

function refreshModelComboFilter({ open = true } = {}) {
  const models = normalizeModelEntries(modelFetchState.models);
  const filterQ = modelComboState.query;
  const filtered = models.filter((m) => modelMatchesQuery(m, filterQ));
  // Cap DOM size for huge OpenRouter catalogs while typing.
  const capped = filtered.slice(0, 200);
  capped.push({ id: CUSTOM_MODEL_VALUE, name: "Custom model…" });
  modelComboState.filtered = capped;
  if (modelComboState.activeIndex >= capped.length) {
    modelComboState.activeIndex = capped.length ? 0 : -1;
  }
  renderModelListItems();
  if (open) setModelComboOpen(true);
}

function renderModelSelect(models, selectedModel = null) {
  const entries = normalizeModelEntries(models);
  modelFetchState.models = entries;
  const ids = entries.map((m) => m.id);
  const known = selectedModel && ids.includes(selectedModel);
  const useCustom = Boolean(selectedModel && !known);
  const preferred = known
    ? selectedModel
    : useCustom
      ? CUSTOM_MODEL_VALUE
      : ids[0] || null;

  modelComboState.query = "";
  modelComboState.activeIndex = -1;

  if (preferred === CUSTOM_MODEL_VALUE || useCustom) {
    selectModelOption({ id: CUSTOM_MODEL_VALUE }, { keepOpen: false });
    if (selectedModel) {
      $("#agent-custom-model").value = selectedModel;
    }
  } else if (preferred) {
    const match = entries.find((m) => m.id === preferred) || {
      id: preferred,
      name: preferred,
    };
    selectModelOption(match, { keepOpen: false });
  } else {
    const input = $("#agent-model-input");
    if (input) input.value = "";
    modelComboState.selectedId = null;
    syncCustomModelWrap();
  }
  refreshModelComboFilter({ open: false });
  setModelComboOpen(false);
}

async function fetchProviderModels(provider, apiKey = "", baseUrl = "") {
  const params = new URLSearchParams();
  const key = (apiKey || "").trim();
  if (key) params.set("api_key", key);
  const url = (baseUrl || "").trim();
  if (url) params.set("base_url", url);
  const qs = params.toString();
  const path = `/providers/${encodeURIComponent(provider)}/models${
    qs ? `?${qs}` : ""
  }`;
  return api(path);
}

function syncProviderUi() {
  const provider = $("#agent-provider")?.value || "openai";
  const isOllama = provider === "ollama";
  const endpointWrap = $("#agent-base-url-wrap");
  if (endpointWrap) endpointWrap.hidden = !isOllama;

  const apiKey = $("#agent-api-key");
  const editing = Boolean(state.editingAgentId);
  if (apiKey) {
    apiKey.required = !editing && !isOllama;
    if (!editing) {
      apiKey.placeholder = isOllama ? "(optional for ollama)" : "sk-…";
    }
  }

  const hint = $("#api-key-hint");
  if (!hint) return;
  if (isOllama) {
    hint.textContent = editing
      ? "Ollama does not need an API key. Leave blank to keep any stored value."
      : "Ollama does not need an API key. Leave blank for local inference.";
  } else if (editing) {
    // openAgentDialog sets a more specific edit hint; keep a sensible default here.
    if (!hint.textContent.includes("Current:")) {
      hint.textContent =
        "Leave blank to keep the existing key. Enter a value only to rotate it. For openai/anthropic/google, a key also unlocks the live model list.";
    }
  } else {
    hint.textContent =
      "Required for new agents. Stored on the agent, not in harness env. Paste a key to refresh the live model list (OpenRouter works without one).";
  }
}

async function populateModelSelect(provider, selectedModel = null) {
  const input = $("#agent-model-input");
  const token = ++modelFetchState.token;
  modelFetchState.loading = true;
  modelFetchState.error = null;
  if (input) input.disabled = true;
  setModelFetchHint("Loading models…", { loading: true });

  // Keep current selection usable while loading.
  if (!modelFetchState.models.length) {
    renderModelSelect([], selectedModel);
  }

  try {
    const apiKey = $("#agent-api-key")?.value || "";
    const baseUrl =
      provider === "ollama" ? $("#agent-base-url")?.value || "" : "";
    const data = await fetchProviderModels(provider, apiKey, baseUrl);
    if (token !== modelFetchState.token) return;
    const models = Array.isArray(data?.models) ? data.models : [];
    modelFetchState.models = models;
    modelFetchState.source = data?.source || "live";
    renderModelSelect(models, selectedModel);
    const source = modelFetchState.source === "fallback" ? "fallback" : "live";
    if (!models.length) {
      setModelFetchHint(`0 models (${source}) — type a custom model id`);
    } else {
      setModelFetchHint(`${models.length} models (${source})`);
    }
  } catch (err) {
    if (token !== modelFetchState.token) return;
    modelFetchState.error = err.message || String(err);
    modelFetchState.models = [];
    modelFetchState.source = "error";
    renderModelSelect([], selectedModel);
    setModelFetchHint(
      `Could not load models (${modelFetchState.error}). Type a custom model id.`,
    );
  } finally {
    if (token === modelFetchState.token) {
      modelFetchState.loading = false;
      if (input) input.disabled = false;
    }
  }
}

function syncModelUi() {
  syncCustomModelWrap();
}

function readModelName() {
  if (modelComboState.selectedId === CUSTOM_MODEL_VALUE) {
    return $("#agent-custom-model").value.trim();
  }
  const typed = ($("#agent-model-input")?.value || "").trim();
  if (!typed || typed === "Custom model…") {
    return $("#agent-custom-model")?.value.trim() || "";
  }
  // If the typed value isn't in the list, treat it as a custom id.
  const known = normalizeModelEntries(modelFetchState.models).some(
    (m) => m.id === typed,
  );
  if (!known && modelComboState.selectedId !== typed) {
    return typed;
  }
  return modelComboState.selectedId || typed;
}

function moveModelComboActive(delta) {
  const len = modelComboState.filtered.length;
  if (!len) return;
  if (!modelComboState.open) refreshModelComboFilter({ open: true });
  let next = modelComboState.activeIndex + delta;
  if (modelComboState.activeIndex < 0) next = delta > 0 ? 0 : len - 1;
  if (next < 0) next = len - 1;
  if (next >= len) next = 0;
  modelComboState.activeIndex = next;
  renderModelListItems();
  const active = $("#agent-model-list [aria-selected='true']");
  active?.scrollIntoView({ block: "nearest" });
}

function commitModelComboActive() {
  const input = $("#agent-model-input");
  const item = modelComboState.filtered[modelComboState.activeIndex];
  if (item) {
    selectModelOption(item);
    return;
  }
  const typed = (input?.value || "").trim();
  if (!typed || typed === "Custom model…") {
    selectModelOption({ id: CUSTOM_MODEL_VALUE });
    return;
  }
  const known = normalizeModelEntries(modelFetchState.models).find(
    (m) => m.id === typed,
  );
  if (known) {
    selectModelOption(known);
    return;
  }
  // Free-typed id not in the fetched list — accept as custom without forcing the secondary field.
  modelComboState.selectedId = typed;
  if (input) input.value = typed;
  syncCustomModelWrap();
  setModelComboOpen(false);
}

function wireModelCombobox() {
  const input = $("#agent-model-input");
  const list = $("#agent-model-list");
  const root = $("#agent-model-combobox");
  if (!input || !list || !root) return;

  input.addEventListener("focus", () => {
    modelComboState.query = "";
    modelComboState.activeIndex = -1;
    refreshModelComboFilter({ open: true });
    // Select all so typing replaces the current id instead of appending.
    requestAnimationFrame(() => input.select());
  });

  input.addEventListener("input", () => {
    modelComboState.selectedId = null;
    modelComboState.query = input.value.trim();
    modelComboState.activeIndex = 0;
    syncCustomModelWrap();
    refreshModelComboFilter({ open: true });
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveModelComboActive(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveModelComboActive(-1);
    } else if (event.key === "Enter") {
      if (modelComboState.open) {
        event.preventDefault();
        commitModelComboActive();
      }
    } else if (event.key === "Escape") {
      if (modelComboState.open) {
        event.preventDefault();
        setModelComboOpen(false);
      }
    }
  });

  list.addEventListener("mousedown", (event) => {
    const option = event.target.closest(".model-combobox-option");
    if (!option) return;
    event.preventDefault();
    const idx = Number(option.dataset.index);
    const item = modelComboState.filtered[idx];
    if (item) selectModelOption(item);
  });

  document.addEventListener("click", (event) => {
    if (!root.contains(event.target)) setModelComboOpen(false);
  });
}

function newSourceId() {
  if (crypto?.randomUUID) return crypto.randomUUID();
  return `src_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function emptyLibrarySource(type = "sql") {
  return {
    id: newSourceId(),
    title: "",
    description: "",
    type,
    config: defaultConfigForType(type),
    _connection_string_set: false,
    _ssh_password_set: false,
    _ssh_private_key_set: false,
    _files: null,
    _filesLoading: false,
  };
}

function hydrateLibrarySource(source) {
  const type = source?.type || "sql";
  const base = defaultConfigForType(type);
  const cfg = source?.config || {};
  if (type === "sql" || type === "nosql") {
    const ssh = { ...base.ssh, ...(cfg.ssh || {}) };
    return {
      id: source.id || newSourceId(),
      title: source.title || "",
      description: source.description || "",
      type,
      config: {
        engine: cfg.engine || base.engine,
        connection_string: "",
        ssh: {
          ...ssh,
          password: "",
          private_key: "",
          remote_port: ssh.remote_port ?? "",
        },
      },
      _connection_string_set: Boolean(cfg.connection_string_set),
      _ssh_password_set: Boolean(cfg.ssh?.password_set),
      _ssh_private_key_set: Boolean(cfg.ssh?.private_key_set),
      _files: null,
      _filesLoading: false,
    };
  }
  return {
    id: source.id || newSourceId(),
    title: source.title || "",
    description: source.description || "",
    type: "files",
    config: { path_prefix: cfg.path_prefix || "" },
    _connection_string_set: false,
    _ssh_password_set: false,
    _ssh_private_key_set: false,
    _files: null,
    _filesLoading: false,
  };
}

function defaultConfigForType(type) {
  if (type === "sql") {
    return {
      engine: "postgresql",
      connection_string: "",
      ssh: {
        enabled: false,
        host: "",
        port: 22,
        username: "",
        auth: "password",
        password: "",
        private_key: "",
        remote_host: "",
        remote_port: "",
      },
    };
  }
  if (type === "nosql") {
    return {
      engine: "mongodb",
      connection_string: "",
      ssh: {
        enabled: false,
        host: "",
        port: 22,
        username: "",
        auth: "password",
        password: "",
        private_key: "",
        remote_host: "",
        remote_port: "",
      },
    };
  }
  return { path_prefix: "" };
}

function destroyPromptEditors() {
  for (const key of Object.keys(promptEditors)) {
    if (promptEditors[key]) {
      try {
        promptEditors[key].toTextArea();
      } catch {
        /* ignore */
      }
      promptEditors[key] = null;
    }
  }
}

function initPromptEditors() {
  destroyPromptEditors();
  if (typeof EasyMDE === "undefined") return;
  const shared = {
    spellChecker: false,
    status: false,
    minHeight: "140px",
    renderingConfig: { singleLineBreaks: false },
  };
  promptEditors.system = new EasyMDE({
    element: $("#agent-system-prompt"),
    ...shared,
    placeholder: "System prompt (markdown)",
  });
  promptEditors.default = new EasyMDE({
    element: $("#agent-default-prompt"),
    ...shared,
    minHeight: "110px",
    placeholder: "Default prompt for cron / Run now (markdown)",
  });
}

function initSourceDescriptionEditor() {
  if (promptEditors.sourceDescription) {
    try {
      promptEditors.sourceDescription.toTextArea();
    } catch {
      /* ignore */
    }
    promptEditors.sourceDescription = null;
  }
  if (typeof EasyMDE === "undefined") return;
  const el = $("#source-description");
  if (!el) return;
  promptEditors.sourceDescription = new EasyMDE({
    element: el,
    spellChecker: false,
    status: false,
    minHeight: "120px",
    renderingConfig: { singleLineBreaks: false },
    placeholder: "What this source is and what agents can do with it (markdown)",
  });
}

function readPromptValue(which) {
  const editor = promptEditors[which];
  if (editor) return editor.value();
  if (which === "sourceDescription") {
    return $("#source-description")?.value || "";
  }
  const el = which === "system" ? $("#agent-system-prompt") : $("#agent-default-prompt");
  return el?.value || "";
}

function setPromptValue(which, value) {
  const editor = promptEditors[which];
  if (editor) {
    editor.value(value || "");
    return;
  }
  if (which === "sourceDescription") {
    const el = $("#source-description");
    if (el) el.value = value || "";
    return;
  }
  const el = which === "system" ? $("#agent-system-prompt") : $("#agent-default-prompt");
  if (el) el.value = value || "";
}

function excerpt(text, max = 140) {
  const clean = String(text || "")
    .replace(/\s+/g, " ")
    .trim();
  if (clean.length <= max) return clean;
  return `${clean.slice(0, max - 1)}…`;
}

function hydrateAttachedIds(agent) {
  if (agent?.source_ids?.length) {
    draftAttachedIds = [...agent.source_ids];
    return;
  }
  // Legacy embedded sources → attach by id when still present on response summaries
  draftAttachedIds = (agent?.sources || []).map((s) => s.id).filter(Boolean);
}

function renderAttachSourcesList() {
  const list = $("#attach-sources-list");
  if (!list) return;
  const q = (state.attachFilter || "").trim().toLowerCase();
  const items = state.sources.filter((src) => {
    if (!q) return true;
    const hay = `${src.title} ${src.type} ${src.description || ""}`.toLowerCase();
    return hay.includes(q);
  });
  if (!state.sources.length) {
    list.innerHTML = `<p class="muted">No library sources yet. <button type="button" class="ghost-btn" id="attach-goto-sources">Open Data sources</button></p>`;
    $("#attach-goto-sources")?.addEventListener("click", () => {
      destroyPromptEditors();
      $("#agent-dialog").close();
      setView("sources");
    });
    return;
  }
  if (!items.length) {
    list.innerHTML = `<p class="muted">No sources match the filter.</p>`;
    return;
  }
  list.innerHTML = items
    .map((src) => {
      const checked = draftAttachedIds.includes(src.id) ? " checked" : "";
      return `
        <label class="attach-item">
          <input type="checkbox" data-source-id="${escapeHtml(src.id)}"${checked} />
          <span>
            <strong>${escapeHtml(src.title)}</strong>
            <span class="chip">${escapeHtml(src.type)}</span>
            <span class="muted attach-desc">${escapeHtml(excerpt(src.description || "No description"))}</span>
          </span>
        </label>`;
    })
    .join("");

  $$('input[type="checkbox"][data-source-id]', list).forEach((input) => {
    input.addEventListener("change", () => {
      const id = input.dataset.sourceId;
      if (input.checked) {
        if (!draftAttachedIds.includes(id)) draftAttachedIds.push(id);
      } else {
        draftAttachedIds = draftAttachedIds.filter((x) => x !== id);
      }
    });
  });
}

function syncLibrarySourceFromDom() {
  const root = $("#source-form-body");
  const src = draftLibrarySource;
  if (!root || !src) return;
  src.title = $('[data-field="title"]', root)?.value?.trim() || "";
  src.description = readPromptValue("sourceDescription");
  const type = $('[data-field="type"]', root)?.value || src.type;
  if (type !== src.type) {
    src.type = type;
    src.config = defaultConfigForType(type);
    src._files = null;
    return;
  }
  if (type === "sql" || type === "nosql") {
    src.config.engine = $('[data-field="engine"]', root)?.value || src.config.engine;
    src.config.connection_string =
      $('[data-field="connection_string"]', root)?.value || "";
    const ssh = src.config.ssh || defaultConfigForType(type).ssh;
    ssh.enabled = Boolean($('[data-field="ssh_enabled"]', root)?.checked);
    ssh.host = $('[data-field="ssh_host"]', root)?.value || "";
    ssh.port = Number($('[data-field="ssh_port"]', root)?.value || 22);
    ssh.username = $('[data-field="ssh_username"]', root)?.value || "";
    ssh.auth = $('[data-field="ssh_auth"]', root)?.value || "password";
    ssh.password = $('[data-field="ssh_password"]', root)?.value || "";
    ssh.private_key = $('[data-field="ssh_private_key"]', root)?.value || "";
    ssh.remote_host = $('[data-field="ssh_remote_host"]', root)?.value || "";
    const rp = $('[data-field="ssh_remote_port"]', root)?.value;
    ssh.remote_port = rp === "" || rp == null ? "" : Number(rp);
    src.config.ssh = ssh;
  } else {
    src.config.path_prefix = $('[data-field="path_prefix"]', root)?.value || "";
  }
}

function buildLibrarySourcePayload() {
  syncLibrarySourceFromDom();
  const src = draftLibrarySource;
  if (!src?.title?.trim()) throw new Error("Title is required");
  if (src.type === "files") {
    return {
      title: src.title.trim(),
      description: (src.description || "").trim(),
      type: "files",
      config: {
        path_prefix: (src.config.path_prefix || "").trim() || null,
      },
    };
  }
  const ssh = src.config.ssh || {};
  const sshPayload = {
    enabled: Boolean(ssh.enabled),
    host: (ssh.host || "").trim() || null,
    port: Number(ssh.port || 22),
    username: (ssh.username || "").trim() || null,
    auth: ssh.auth || "password",
    password: (ssh.password || "").trim() || null,
    private_key: (ssh.private_key || "").trim() || null,
    remote_host: (ssh.remote_host || "").trim() || null,
    remote_port:
      ssh.remote_port === "" || ssh.remote_port == null
        ? null
        : Number(ssh.remote_port),
  };
  const conn = (src.config.connection_string || "").trim();
  return {
    title: src.title.trim(),
    description: (src.description || "").trim(),
    type: src.type,
    config: {
      engine: src.config.engine,
      ...(conn ? { connection_string: conn } : {}),
      ssh: sshPayload,
    },
  };
}

function renderDbSourceFields(src) {
  const ssh = src.config.ssh || {};
  const engineOptions =
    src.type === "sql"
      ? ["postgresql", "mysql", "sqlite"]
      : ["mongodb"];
  const connHint = src._connection_string_set
    ? "Configured — leave blank to keep, or paste a new value to rotate."
    : "Connection URL (stored on the library source).";
  const sshBlock = ssh.enabled
    ? `
      <label>
        SSH host
        <input data-field="ssh_host" value="${escapeHtml(ssh.host || "")}" placeholder="bastion.example.com" />
      </label>
      <label>
        SSH port
        <input data-field="ssh_port" type="number" value="${escapeHtml(ssh.port ?? 22)}" />
      </label>
      <label>
        SSH username
        <input data-field="ssh_username" value="${escapeHtml(ssh.username || "")}" />
      </label>
      <label>
        SSH auth
        <select data-field="ssh_auth">
          <option value="password" ${ssh.auth === "password" ? "selected" : ""}>password</option>
          <option value="key" ${ssh.auth === "key" ? "selected" : ""}>key</option>
        </select>
      </label>
      ${
        ssh.auth === "key"
          ? `<label class="span-2">
              Private key ${src._ssh_private_key_set ? "(set — leave blank to keep)" : ""}
              <textarea data-field="ssh_private_key" rows="3" placeholder="-----BEGIN …-----"></textarea>
            </label>`
          : `<label class="span-2">
              SSH password ${src._ssh_password_set ? "(set — leave blank to keep)" : ""}
              <input data-field="ssh_password" type="password" autocomplete="off" />
            </label>`
      }
      <label>
        Remote DB host (optional)
        <input data-field="ssh_remote_host" value="${escapeHtml(ssh.remote_host || "")}" placeholder="from bastion" />
      </label>
      <label>
        Remote DB port (optional)
        <input data-field="ssh_remote_port" type="number" value="${escapeHtml(ssh.remote_port ?? "")}" />
      </label>
      <p class="hint span-2">SSH tunneling will be used at runtime when enabled (direct non-SSH connections work today).</p>
    `
    : `<input type="hidden" data-field="ssh_host" value="${escapeHtml(ssh.host || "")}" />
       <input type="hidden" data-field="ssh_port" value="${escapeHtml(ssh.port ?? 22)}" />
       <input type="hidden" data-field="ssh_username" value="${escapeHtml(ssh.username || "")}" />
       <input type="hidden" data-field="ssh_auth" value="${escapeHtml(ssh.auth || "password")}" />
       <input type="hidden" data-field="ssh_password" value="" />
       <input type="hidden" data-field="ssh_private_key" value="" />
       <input type="hidden" data-field="ssh_remote_host" value="${escapeHtml(ssh.remote_host || "")}" />
       <input type="hidden" data-field="ssh_remote_port" value="${escapeHtml(ssh.remote_port ?? "")}" />`;

  return `
    <label>
      Engine
      <select data-field="engine">
        ${engineOptions
          .map(
            (e) =>
              `<option value="${e}" ${src.config.engine === e ? "selected" : ""}>${e}</option>`,
          )
          .join("")}
      </select>
    </label>
    <label class="span-2">
      Connection string
      <input
        data-field="connection_string"
        type="password"
        autocomplete="off"
        placeholder="${src._connection_string_set ? "•••• configured" : "postgresql://user:pass@host:5432/db"}"
      />
      <span class="hint">${connHint}</span>
    </label>
    <label class="check span-2">
      <input type="checkbox" data-field="ssh_enabled" ${ssh.enabled ? "checked" : ""} />
      Use SSH tunnel
    </label>
    ${sshBlock}
  `;
}

function renderFilesSourceFields(src, editing) {
  const filesBlock = !editing
    ? `<p class="hint span-2">Save the source first, then reopen edit to upload files into <code>_library/${escapeHtml(src.id)}</code>.</p>`
    : renderFilesManager(src);
  return `
    <label class="span-2">
      Path prefix (optional)
      <input data-field="path_prefix" value="${escapeHtml(src.config.path_prefix || "")}" placeholder="notes/" />
      <span class="hint">Files live under <code>data/agent_workspaces/_library/{source_id}/</code> and are mounted for attached agents at <code>sources/{source_id}/</code>.</span>
    </label>
    ${filesBlock}
  `;
}

function renderFilesManager(src) {
  if (src._filesLoading) {
    return `<p class="hint span-2">Loading files…</p>`;
  }
  const rows = (src._files || [])
    .map(
      (f) => `
      <li class="source-file-row">
        <span class="mono">${escapeHtml(f.path)}</span>
        <span class="muted">${f.size} B</span>
        <span class="row-actions">
          ${
            f.is_text
              ? `<button type="button" class="ghost-btn" data-act="edit-file" data-path="${escapeHtml(f.path)}">Edit</button>`
              : ""
          }
          <button type="button" class="ghost-btn" data-act="delete-file" data-path="${escapeHtml(f.path)}">Delete</button>
        </span>
      </li>`,
    )
    .join("");
  return `
    <div class="span-2 source-files">
      <div class="sources-head">
        <span class="field-label">Files</span>
        <div class="row-actions">
          <button type="button" class="ghost-btn" data-act="refresh-files">Refresh</button>
        </div>
      </div>
      <label class="source-file-dropzone" data-dropzone>
        <span class="source-file-dropzone-label">Drop files here or click to upload</span>
        <span class="source-file-dropzone-hint muted">PDF, text, and other files supported</span>
        <input type="file" data-act="upload-file" multiple hidden />
      </label>
      <ul class="source-file-list">${rows || '<li class="muted">No files yet</li>'}</ul>
    </div>`;
}

function renderSourceFormBody() {
  const body = $("#source-form-body");
  const src = draftLibrarySource;
  if (!body || !src) return;
  const editing = Boolean(state.editingSourceId);
  const typeFields =
    src.type === "files"
      ? renderFilesSourceFields(src, editing)
      : renderDbSourceFields(src);
  body.innerHTML = `
    <div class="source-grid">
      <label>
        Title
        <input data-field="title" value="${escapeHtml(src.title)}" required maxlength="120" />
      </label>
      <label>
        Type
        <select data-field="type">
          <option value="sql" ${src.type === "sql" ? "selected" : ""}>sql</option>
          <option value="nosql" ${src.type === "nosql" ? "selected" : ""}>nosql</option>
          <option value="files" ${src.type === "files" ? "selected" : ""}>files</option>
        </select>
      </label>
      <label class="span-2">
        Description
        <textarea id="source-description" data-field="description" rows="4">${escapeHtml(src.description)}</textarea>
        <span class="hint">Markdown OK — explain what this source is and what agents can do with it.</span>
      </label>
      ${typeFields}
    </div>`;

  initSourceDescriptionEditor();
  setPromptValue("sourceDescription", src.description || "");

  $('[data-field="type"]', body)?.addEventListener("change", (event) => {
    syncLibrarySourceFromDom();
    src.type = event.target.value;
    src.config = defaultConfigForType(src.type);
    src._files = null;
    renderSourceFormBody();
  });
  $('[data-field="ssh_enabled"]', body)?.addEventListener("change", () => {
    syncLibrarySourceFromDom();
    renderSourceFormBody();
  });
  $('[data-field="ssh_auth"]', body)?.addEventListener("change", () => {
    syncLibrarySourceFromDom();
    renderSourceFormBody();
  });
  $('[data-act="refresh-files"]', body)?.addEventListener("click", () => {
    loadLibrarySourceFiles();
  });
  const uploadInput = $('[data-act="upload-file"]', body);
  const dropzone = $("[data-dropzone]", body);
  uploadInput?.addEventListener("change", async (event) => {
    const files = [...(event.target.files || [])];
    if (!files.length) return;
    await uploadLibrarySourceFiles(files);
    event.target.value = "";
  });
  if (dropzone) {
    let dragDepth = 0;
    dropzone.addEventListener("dragenter", (event) => {
      event.preventDefault();
      dragDepth += 1;
      dropzone.classList.add("is-dragover");
    });
    dropzone.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    });
    dropzone.addEventListener("dragleave", (event) => {
      event.preventDefault();
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) dropzone.classList.remove("is-dragover");
    });
    dropzone.addEventListener("drop", async (event) => {
      event.preventDefault();
      dragDepth = 0;
      dropzone.classList.remove("is-dragover");
      const files = [...(event.dataTransfer?.files || [])];
      if (!files.length) return;
      await uploadLibrarySourceFiles(files);
      if (uploadInput) uploadInput.value = "";
    });
  }
  $$('[data-act="edit-file"]', body).forEach((btn) => {
    btn.addEventListener("click", () => editLibrarySourceFile(btn.dataset.path));
  });
  $$('[data-act="delete-file"]', body).forEach((btn) => {
    btn.addEventListener("click", () => deleteLibrarySourceFile(btn.dataset.path));
  });

  if (editing && src.type === "files" && src._files === null && !src._filesLoading) {
    loadLibrarySourceFiles();
  }
}

async function loadLibrarySourceFiles() {
  const src = draftLibrarySource;
  if (!src || src.type !== "files" || !state.editingSourceId) return;
  src._filesLoading = true;
  renderSourceFormBody();
  try {
    src._files = await api(`/sources/${state.editingSourceId}/files`);
  } catch (err) {
    toast(err.message, "error");
    src._files = [];
  } finally {
    src._filesLoading = false;
    renderSourceFormBody();
  }
}

async function uploadLibrarySourceFiles(files) {
  for (const file of files) {
    await uploadLibrarySourceFile(file, { refresh: false });
  }
  await loadLibrarySourceFiles();
}

async function uploadLibrarySourceFile(file, { refresh = true } = {}) {
  if (!state.editingSourceId) return;
  const body = new FormData();
  body.append("file", file);
  try {
    const res = await fetch(`/sources/${state.editingSourceId}/files`, {
      method: "POST",
      body,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || res.statusText);
    }
    toast(`Uploaded ${file.name}`);
    if (refresh) await loadLibrarySourceFiles();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function editLibrarySourceFile(path) {
  if (!state.editingSourceId) return;
  try {
    const data = await api(
      `/sources/${state.editingSourceId}/files/${encodeURI(path)}`,
    );
    const next = prompt(`Edit ${path}`, data.content);
    if (next == null) return;
    await api(`/sources/${state.editingSourceId}/files/${encodeURI(path)}`, {
      method: "PUT",
      body: JSON.stringify({ content: next }),
    });
    toast("File updated");
    await loadLibrarySourceFiles();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function deleteLibrarySourceFile(path) {
  if (!state.editingSourceId) return;
  if (!confirm(`Delete file “${path}”?`)) return;
  try {
    await api(`/sources/${state.editingSourceId}/files/${encodeURI(path)}`, {
      method: "DELETE",
    });
    toast("File deleted");
    await loadLibrarySourceFiles();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function openSourceDialog(source = null) {
  state.editingSourceId = source?.id || null;
  let full = source;
  if (source?.id) {
    try {
      full = await api(`/sources/${source.id}`);
    } catch (err) {
      toast(err.message, "error");
      return;
    }
  }
  draftLibrarySource = full
    ? hydrateLibrarySource(full)
    : emptyLibrarySource("sql");
  $("#source-dialog-title").textContent = state.editingSourceId
    ? "Edit data source"
    : "New data source";
  const testEl = $("#source-test-result");
  if (testEl) {
    testEl.hidden = true;
    testEl.textContent = "";
    testEl.className = "hint source-test-result";
  }
  renderSourceFormBody();
  $("#source-dialog").showModal();
}

function closeSourceDialog() {
  if (promptEditors.sourceDescription) {
    try {
      promptEditors.sourceDescription.toTextArea();
    } catch {
      /* ignore */
    }
    promptEditors.sourceDescription = null;
  }
  draftLibrarySource = null;
  state.editingSourceId = null;
  const testEl = $("#source-test-result");
  if (testEl) {
    testEl.hidden = true;
    testEl.textContent = "";
    testEl.className = "hint source-test-result";
  }
  $("#source-dialog").close();
}

function showSourceTestResult(el, result) {
  if (!el) return;
  el.hidden = false;
  const latency =
    result.latency_ms != null ? ` (${result.latency_ms} ms)` : "";
  el.textContent = `${result.ok ? "OK" : "Failed"}: ${result.message}${latency}`;
  el.className = `hint source-test-result ${result.ok ? "ok" : "bad"}`;
}

async function testSavedSource(source) {
  if (!source?.id) return;
  const resultEl = $("#detail-source-test-result");
  try {
    const result = await api(`/sources/${source.id}/test`, { method: "POST" });
    showSourceTestResult(resultEl, result);
    toast(result.ok ? "Connection OK" : "Connection failed", result.ok ? "ok" : "error");
  } catch (err) {
    showSourceTestResult(resultEl, { ok: false, message: err.message });
    toast(err.message, "error");
  }
}

async function testDraftSource() {
  const resultEl = $("#source-test-result");
  try {
    const payload = buildLibrarySourcePayload();
    let result;
    if (state.editingSourceId) {
      result = await api(`/sources/${state.editingSourceId}/test`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    } else {
      result = await api("/sources/test", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    showSourceTestResult(resultEl, result);
    toast(result.ok ? "Connection OK" : "Connection failed", result.ok ? "ok" : "error");
  } catch (err) {
    showSourceTestResult(resultEl, { ok: false, message: err.message });
    toast(err.message, "error");
  }
}

async function saveSource(event) {
  event.preventDefault();
  try {
    const payload = buildLibrarySourcePayload();
    if (state.editingSourceId) {
      await api(`/sources/${state.editingSourceId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      toast("Data source updated");
    } else {
      const created = await api("/sources", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.selectedSourceId = created.id;
      toast("Data source created");
    }
    closeSourceDialog();
    await loadSources();
    render();
    if (state.view === "sources") syncUrl();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function deleteSource(source) {
  if (!source) return;
  if (!confirm(`Delete data source “${source.title}”?`)) return;
  try {
    await api(`/sources/${source.id}`, { method: "DELETE" });
    if (state.selectedSourceId === source.id) state.selectedSourceId = null;
    toast("Data source deleted");
    await loadSources();
    render();
    if (state.view === "sources") syncUrl();
  } catch (err) {
    toast(err.message, "error");
  }
}

function populateTemplateSelect() {
  const select = $("#agent-template-select");
  if (!select) return;
  const current = select.value;
  select.innerHTML = `<option value="">Blank</option>`;
  for (const t of state.agentTemplates) {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = formatAgentLabel(t, t.name || t.id);
    select.appendChild(opt);
  }
  select.value = [...select.options].some((o) => o.value === current) ? current : "";
  updateTemplateHint();
}

function updateTemplateHint() {
  const hint = $("#agent-template-hint");
  const select = $("#agent-template-select");
  if (!hint || !select) return;
  const template = state.agentTemplates.find((t) => t.id === select.value);
  hint.textContent = template
    ? template.description
    : "Templates autofill prompts and model suggestions. API key and schedule stay empty / Off.";
}

function applyAgentTemplate(templateId) {
  const form = $("#agent-form");
  if (!form || state.editingAgentId) return;

  if (!templateId) {
    form.name.value = "";
    form.role.value = "";
    form.provider.value = "openai";
    form.api_key.value = "";
    if (form.base_url) form.base_url.value = "";
    applyCronToUi(null);
    setPromptValue("system", "");
    setPromptValue("default", "");
    syncProviderUi();
    populateModelSelect(form.provider.value, null);
    updateTemplateHint();
    return;
  }

  const template = state.agentTemplates.find((t) => t.id === templateId);
  if (!template) return;

  form.name.value = template.name || "";
  form.role.value = template.role || "";
  form.provider.value = template.provider || "openai";
  // Explicitly leave secrets and schedule alone / cleared.
  form.api_key.value = "";
  if (form.base_url) form.base_url.value = "";
  applyCronToUi(null);
  setPromptValue("system", template.system_prompt || "");
  setPromptValue("default", template.default_prompt || "");
  syncProviderUi();
  populateModelSelect(form.provider.value, template.model_name || null);
  updateTemplateHint();
  renderAvatarEditor();
}

function openAgentDialog(agent = null) {
  state.editingAgentId = agent?.id || null;
  state.attachFilter = "";
  const form = $("#agent-form");
  const editing = Boolean(agent);
  $("#agent-dialog-title").textContent = editing ? "Edit agent" : "New agent";

  const picker = $("#agent-template-picker");
  const editNote = $("#agent-template-edit-note");
  const templateSelect = $("#agent-template-select");
  if (picker) picker.hidden = editing;
  if (editNote) editNote.hidden = !editing;
  if (templateSelect) {
    templateSelect.value = "";
    updateTemplateHint();
  }

  form.name.value = agent?.name || "";
  form.role.value = agent?.role || "";
  form.provider.value = agent?.provider || "openai";
  form.api_key.value = "";
  form.api_key.placeholder = editing
    ? "•••• (leave blank to keep)"
    : "sk-…";
  if (form.base_url) {
    form.base_url.value = agent?.base_url || "";
  }
  if (editing && agent?.api_key_set && agent?.api_key_preview) {
    $("#api-key-hint").textContent =
      `Current: ${agent.api_key_preview} — leave blank to keep. Enter a new value only to rotate it. For openai/anthropic/google, a key also unlocks the live model list.`;
  } else if (editing) {
    $("#api-key-hint").textContent =
      "Leave blank to keep the existing key. Enter a value only to rotate it. For openai/anthropic/google, a key also unlocks the live model list.";
  } else {
    $("#api-key-hint").textContent =
      "Required for new agents. Stored on the agent, not in harness env. Paste a key to refresh the live model list (OpenRouter works without one).";
  }
  syncProviderUi();
  populateModelSelect(form.provider.value, agent?.model_name || null);
  applyCronToUi(agent?.cron_schedule || null);
  hydrateAttachedIds(agent);
  hydrateDraftAvatar(agent);
  initPromptEditors();
  setPromptValue("system", agent?.system_prompt || "");
  setPromptValue("default", agent?.default_prompt || "");
  const handoffSel = $("#agent-handoff-select");
  if (handoffSel) {
    const selfId = agent?.id || "";
    handoffSel.innerHTML = [
      `<option value="">None</option>`,
      ...state.agents
        .filter((a) => a.id !== selfId)
        .map(
          (a) =>
            `<option value="${escapeHtml(a.id)}">${escapeHtml(formatAgentLabel(a))}</option>`,
        ),
    ].join("");
    handoffSel.value = agent?.handoff_agent_id || "";
  }
  const filter = $("#attach-sources-filter");
  if (filter) filter.value = "";
  renderAttachSourcesList();
  renderAvatarEditor();
  const fileInput = $("#agent-avatar-file");
  if (fileInput) fileInput.value = "";
  $("#agent-dialog").showModal();
}

function readAgentForm({ includeApiKey }) {
  const form = $("#agent-form");
  const model_name = readModelName();
  if (!model_name) {
    throw new Error("Model is required");
  }
  const cronPreset = $("#cron-preset").value;
  const cron_schedule = buildCronFromUi();
  if (
    (cronPreset === "weekly" || cronPreset === "monthly") &&
    !cron_schedule
  ) {
    throw new Error("Select at least one day for the schedule");
  }
  const system_prompt = readPromptValue("system").trim();
  if (!system_prompt) throw new Error("System prompt is required");
  const handoffVal = ($("#agent-handoff-select")?.value || "").trim();
  const provider = form.provider.value;
  const payload = {
    name: form.name.value.trim(),
    role: form.role.value.trim(),
    provider,
    model_name,
    cron_schedule,
    system_prompt,
    default_prompt: readPromptValue("default").trim() || null,
    enabled_tools: [],
    source_ids: [...draftAttachedIds],
    handoff_agent_id: handoffVal || null,
  };
  payload.base_url =
    provider === "ollama"
      ? (form.base_url?.value || "").trim() || null
      : null;
  // Image upload wins; otherwise persist the selected preset (or clear to initials).
  if (!draftAvatar.file) {
    payload.avatar_preset = draftAvatar.preset || null;
  }
  if (includeApiKey) {
    const key = form.api_key.value.trim();
    if (!key && provider !== "ollama") {
      throw new Error("API key is required");
    }
    payload.api_key = key;
  } else {
    const key = form.api_key.value.trim();
    if (key) payload.api_key = key;
  }
  return payload;
}

async function saveAgent(event) {
  event.preventDefault();
  try {
    let agentId = state.editingAgentId;
    if (state.editingAgentId) {
      const payload = readAgentForm({ includeApiKey: false });
      await api(`/agents/${state.editingAgentId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      await persistAgentAvatar(state.editingAgentId);
      toast("Agent updated");
    } else {
      const payload = readAgentForm({ includeApiKey: true });
      const created = await api("/agents", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      agentId = created.id;
      state.selectedAgentId = created.id;
      await persistAgentAvatar(created.id);
      toast("Agent created");
    }
    resetDraftAvatar();
    destroyPromptEditors();
    $("#agent-dialog").close();
    await loadAgents();
    if (agentId) state.selectedAgentId = agentId;
  } catch (err) {
    toast(err.message, "error");
  }
}

function openRunDialog(agent) {
  state.runAgentId = agent.id;
  $("#run-agent-label").textContent = formatAgentLabel(agent);
  $("#run-form").prompt.value = "";
  $("#run-dialog").showModal();
}

function isRunsSession(session) {
  return session?.title === "Agent runs";
}

function visibleChatSessions() {
  let sessions = state.allSessions || [];

  if (state.chatSessionsFilter === "agent") {
    if (!state.chatAgentId) return [];
    sessions = sessions.filter((s) => s.agent_id === state.chatAgentId);
  }

  if (state.chatSessionsKind === "runs") {
    sessions = sessions.filter(isRunsSession);
  } else if (state.chatSessionsKind === "chats") {
    sessions = sessions.filter((s) => !isRunsSession(s));
  }

  const q = (state.chatSessionsQuery || "").trim().toLowerCase();
  if (q) {
    sessions = sessions.filter((s) => {
      const title = String(s.title || "").toLowerCase();
      const name = String(agentName(s.agent_id) || "").toLowerCase();
      return title.includes(q) || name.includes(q);
    });
  }

  const dir = state.chatSessionsSort === "oldest" ? 1 : -1;
  return [...sessions].sort((a, b) => {
    const ta = Date.parse(a.updated_at || "") || 0;
    const tb = Date.parse(b.updated_at || "") || 0;
    return (ta - tb) * dir;
  });
}

function sessionUnreadCount(session) {
  const n = Number(session?.unread_count ?? session?.unread_runs) || 0;
  return n > 0 ? n : 0;
}

function sumUnreadCounts() {
  return (state.allSessions || []).reduce(
    (total, s) => total + sessionUnreadCount(s),
    0,
  );
}

function updateChatNavBadge() {
  const el = $("#nav-chat-count");
  if (!el) return;
  const n = sumUnreadCounts();
  if (n > 0) {
    el.hidden = false;
    el.textContent = String(n);
  } else {
    el.hidden = true;
    el.textContent = "0";
  }
}

function zeroSessionUnread(chatId) {
  const idx = (state.allSessions || []).findIndex((c) => c.id === chatId);
  if (idx < 0) return;
  state.allSessions[idx] = {
    ...state.allSessions[idx],
    unread_count: 0,
    unread_runs: 0,
  };
  updateChatNavBadge();
}

async function markChatRead(chatId) {
  if (!chatId) return;
  zeroSessionUnread(chatId);
  try {
    await api(`/chats/${chatId}/read`, { method: "POST", body: "{}" });
  } catch {
    /* ignore — local badge already cleared */
  }
}

function sessionSummary(chatId) {
  return (state.allSessions || []).find((c) => c.id === chatId) || null;
}

function syncChatAgentSelect() {
  const sel = $("#chat-agent-select");
  if (!sel) return;
  const sig = state.agents
    .map((a) => `${a.id}:${a.name}:${a.role || ""}`)
    .join(",");
  if (sel.dataset.agentSig !== sig) {
    sel.innerHTML = [
      `<option value="">Select agent…</option>`,
      ...state.agents.map(
        (a) =>
          `<option value="${escapeHtml(a.id)}">${escapeHtml(formatAgentLabel(a))}</option>`,
      ),
    ].join("");
    sel.dataset.agentSig = sig;
  }
  const valid = state.agents.some((a) => a.id === state.chatAgentId);
  sel.value = valid ? state.chatAgentId : "";
}

function syncChatFilterChips() {
  $$('.chat-filter-chips [data-filter]').forEach((btn) => {
    const filter = btn.dataset.filter || "all";
    btn.classList.toggle("active", filter === state.chatSessionsFilter);
  });
  $$('.chat-filter-chips [data-kind]').forEach((btn) => {
    const kind = btn.dataset.kind || "all";
    btn.classList.toggle("active", kind === state.chatSessionsKind);
  });
  const search = $("#chat-session-search");
  if (search && search.value !== state.chatSessionsQuery) {
    search.value = state.chatSessionsQuery || "";
  }
  const sort = $("#chat-session-sort");
  if (sort && sort.value !== state.chatSessionsSort) {
    sort.value = state.chatSessionsSort || "newest";
  }
}

function prepareNewChatContext() {
  if (state.chatAbortController) {
    state.chatAbortController.abort();
    state.chatAbortController = null;
  }
  state.chatId = null;
  state.chatMessages = [];
  state.chatAttachments = [];
  state.chatSending = false;
  state.chatStreamingText = "";
  state.chatStreamStarted = false;
  state.chatStreamGeneratingHtml = false;
  state.chatStreamTools = [];
  const input = $("#chat-input");
  if (input) input.value = "";
  const status = $("#chat-status");
  if (status) {
    status.hidden = true;
    status.textContent = "";
  }
}

function onChatAgentPickerChange(agentId) {
  const next = agentId || null;
  if (next === state.chatAgentId) return;
  state.chatAgentId = next;
  prepareNewChatContext();
  // Refresh header subtitle without leaving Chat.
  if (state.view === "chat") {
    const agent = chatAgent();
    $("#view-sub").textContent = agent
      ? formatAgentLabel(agent)
      : "Pick an agent or open a session to start a conversation.";
  }
  renderChatPanel();
  syncUrl();
}

async function openChat(agent, preferredChatId = null, from = "agents") {
  if (!agent) return;
  state.chatAgentId = agent.id;
  state.chatOpenedFrom = from;
  prepareNewChatContext();
  suppressUrlSync = true;
  setView("chat");
  try {
    await loadAllSessions();
    const forAgent = (state.allSessions || []).filter(
      (s) => s.agent_id === agent.id,
    );
    const preferred =
      preferredChatId || forAgent[0]?.id || null;
    if (preferred) {
      await selectChat(preferred, { skipUrl: true });
    } else {
      renderChatPanel();
    }
  } catch (err) {
    toast(err.message, "error");
    renderChatPanel();
  } finally {
    suppressUrlSync = false;
    syncUrl();
  }
}

async function createChat() {
  if (!state.chatAgentId) {
    toast("Select an agent first", "error");
    return;
  }
  try {
    const created = await api(`/agents/${state.chatAgentId}/chats`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    await loadAllSessions();
    await selectChat(created.id);
    toast("New session");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function selectChat(chatId, { skipUrl = false, scrollToMsg = null } = {}) {
  if (state.chatSending && state.chatId && state.chatId !== chatId) {
    cancelChatStream();
  }
  state.chatId = chatId;
  try {
    const chat = await api(`/chats/${chatId}`);
    state.chatAgentId = chat.agent_id;
    state.chatMessages = normalizeChatMessages(chat.messages || []);
    state.chatAttachments = chat.attachments || [];
    const summary = {
      id: chat.id,
      agent_id: chat.agent_id,
      title: chat.title,
      updated_at: chat.updated_at,
      message_count: (chat.messages || []).length,
      has_html: state.chatMessages.some((m) => m.html),
      unread_count: 0,
      unread_runs: 0,
    };
    const idx = (state.allSessions || []).findIndex((c) => c.id === chatId);
    if (idx >= 0) state.allSessions[idx] = { ...state.allSessions[idx], ...summary };
    else state.allSessions = [summary, ...(state.allSessions || [])];
    await markChatRead(chatId);
    if (state.view === "chat") {
      const agent = chatAgent();
      $("#view-sub").textContent = agent
        ? formatAgentLabel(agent)
        : "Pick an agent or open a session to start a conversation.";
    }
  } catch (err) {
    toast(err.message, "error");
    state.chatMessages = [];
    state.chatAttachments = [];
  }
  renderChatPanel();
  if (scrollToMsg != null) {
    const el = $(`[data-msg-idx="${scrollToMsg}"]`) || $(`.chat-report-card [data-html-idx="${scrollToMsg}"]`);
    const card = el?.closest?.(".chat-report-card") || $(`iframe[data-html-idx="${scrollToMsg}"]`)?.closest(".chat-report-card");
    if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
    else scrollLatestReportIntoView();
  } else if (state.chatMessages.some((m) => m.html)) {
    scrollLatestReportIntoView();
  }
  if (!skipUrl) syncUrl();
}

async function renameActiveChat() {
  if (!state.chatId) return;
  const current = sessionSummary(state.chatId)?.title || "Chat";
  const next = await promptRenameDialog(current);
  if (next == null) return;
  const title = next.trim();
  if (!title) {
    toast("Title is required", "error");
    return;
  }
  try {
    await api(`/chats/${state.chatId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
    await loadAllSessions();
    renderChatPanel();
    toast("Session renamed");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function deleteActiveChat() {
  if (!state.chatId) return;
  const title = sessionSummary(state.chatId)?.title || "this session";
  const ok = await confirmDialog({
    title: "Delete session",
    message: `Delete session “${title}”? This cannot be undone.`,
    confirmLabel: "Delete",
  });
  if (!ok) return;
  const deletedId = state.chatId;
  try {
    await api(`/chats/${deletedId}`, { method: "DELETE" });
    prepareNewChatContext();
    await loadAllSessions();
    renderChatPanel();
    syncUrl();
    toast("Session deleted");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function cancelChatStream() {
  const chatId = state.chatId;
  if (state.chatAbortController) {
    state.chatAbortController.abort();
  }
  if (chatId) {
    try {
      await api(`/chats/${chatId}/cancel`, { method: "POST", body: "{}" });
    } catch {
      /* best-effort */
    }
  }
}

/** Extract a full HTML document from assistant text (client fallback). */
function extractHtmlFromText(text) {
  if (!text) return null;
  const s = String(text);
  const fenced = s.match(
    /```(?:html)?\s*((?:<!DOCTYPE html[\s\S]*?<\/html>|<html[\s\S]*?<\/html>))\s*```/i,
  );
  if (fenced) return fenced[1].trim();
  const bare = s.match(/(<!DOCTYPE html[\s\S]*?<\/html>|<html[\s\S]*?<\/html>)/i);
  return bare ? bare[1].trim() : null;
}

function looksLikeHtmlStream(text) {
  const t = String(text || "").trimStart().toLowerCase();
  if (!t) return false;
  return (
    t.includes("<!doctype html") ||
    t.includes("<html") ||
    t.includes("```html") ||
    /<(?:head|body|table|style)\b/.test(t)
  );
}

/** Normalize API messages so html is always present when extractable. */
function normalizeChatMessages(messages) {
  return (messages || []).map((m) => {
    const html = m.html || extractHtmlFromText(m.content) || null;
    return html && html !== m.html ? { ...m, html } : m;
  });
}

function revokeHtmlBlobUrls() {
  for (const url of _htmlBlobUrls) {
    try {
      URL.revokeObjectURL(url);
    } catch {
      /* ignore */
    }
  }
  _htmlBlobUrls.clear();
}

/** Source of truth after any stream end — do not trust SSE done payloads for transcript. */
async function refreshChatMessagesFromServer() {
  if (!state.chatId) return;
  try {
    const chat = await api(`/chats/${state.chatId}`);
    state.chatMessages = normalizeChatMessages(chat.messages || []);
    state.chatAttachments = chat.attachments || [];
    if (chat.agent_id) state.chatAgentId = chat.agent_id;
  } catch {
    /* keep optimistic state */
  }
}

function scrollLatestReportIntoView() {
  const thread = $("#chat-messages");
  if (!thread) return;
  const cards = thread.querySelectorAll(".chat-report-card");
  const last = cards[cards.length - 1];
  if (last) {
    requestAnimationFrame(() => {
      last.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }
}

async function readSseStream(response, onEvent) {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let eventName = "message";
      const dataLines = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let data = {};
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        data = { message: dataLines.join("\n") };
      }
      onEvent(eventName, data);
    }
  }
}

async function sendChatMessage(event) {
  event.preventDefault();
  if (state.chatSending) return;
  const input = $("#chat-input");
  const content = (input.value || "").trim();
  if (!content) return;

  if (!state.chatAgentId) {
    toast("Select an agent first", "error");
    return;
  }

  if (!state.chatId) {
    try {
      const created = await api(`/agents/${state.chatAgentId}/chats`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      state.chatId = created.id;
      await loadAllSessions();
      syncUrl();
    } catch (err) {
      toast(err.message, "error");
      return;
    }
  }

  const controller = new AbortController();
  state.chatAbortController = controller;
  const streamingChatId = state.chatId;
  state.chatSending = true;
  state.chatStreamingText = "";
  state.chatStreamStarted = false;
  state.chatStreamGeneratingHtml = false;
  state.chatStreamTools = [];
  state.chatMessages = [
    ...state.chatMessages,
    { role: "user", content, timestamp: new Date().toISOString() },
  ];
  input.value = "";
  renderChatPanel();

  try {
    const res = await fetch(`/chats/${streamingChatId}/messages/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ content }),
      signal: controller.signal,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const errBody = await res.json();
        detail = errBody.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }

    await readSseStream(res, (eventName, data) => {
      // Server emits both `token` and `delta` aliases — only consume one.
      if (eventName === "token") {
        const piece = data.text || "";
        if (!piece) return;
        state.chatStreamingText += piece;
        if (looksLikeHtmlStream(state.chatStreamingText)) {
          state.chatStreamGeneratingHtml = true;
        }
        // Defer HTML report cards until after GET reload; hide raw HTML tokens.
        if (
          state.chatStreamingText.trim() &&
          !state.chatStreamGeneratingHtml
        ) {
          state.chatStreamStarted = true;
        }
        renderChatPanel();
      } else if (eventName === "tool") {
        const name = data.name || "?";
        const phase = data.phase === "end" ? "end" : "start";
        const label =
          phase === "end" ? `✓ ${name} done` : `Working… ${name}`;
        if (name === "write_html_report") {
          state.chatStreamGeneratingHtml = true;
        }
        const tools = state.chatStreamTools.slice();
        const existing = tools.findIndex(
          (t) => t.name === name && t.phase === "start",
        );
        if (phase === "end" && existing >= 0) {
          tools[existing] = { name, phase, label };
        } else {
          tools.push({ name, phase, label });
        }
        state.chatStreamTools = tools.slice(-8);
        renderChatPanel();
      } else if (eventName === "done") {
        // Clear ephemeral stream UI immediately; final transcript via GET.
        state.chatStreamingText = "";
        state.chatStreamStarted = false;
        state.chatStreamGeneratingHtml = false;
        state.chatStreamTools = [];
        renderChatPanel();
      } else if (eventName === "error") {
        const msg = data.message || "Chat stream failed";
        if (msg !== "Cancelled") toast(msg, "error");
        else toast("Cancelled", "error");
        state.chatStreamingText = "";
        state.chatStreamStarted = false;
        state.chatStreamGeneratingHtml = false;
        state.chatStreamTools = [];
        renderChatPanel();
      }
    });

    // Always reload messages from API — source of truth (includes html reports).
    await refreshChatMessagesFromServer();
    await loadAllSessions();
    if (state.chatId === streamingChatId) {
      await markChatRead(streamingChatId);
      renderChatPanel();
    }
    loadActivity().catch(() => {});
  } catch (err) {
    if (err?.name === "AbortError") {
      toast("Cancelled", "error");
    } else {
      toast(err.message || "Chat failed", "error");
    }
    await refreshChatMessagesFromServer();
  } finally {
    state.chatSending = false;
    state.chatAbortController = null;
    state.chatStreamingText = "";
    state.chatStreamStarted = false;
    state.chatStreamGeneratingHtml = false;
    state.chatStreamTools = [];
    renderChatPanel();
    if (state.chatMessages.some((m) => m.html)) scrollLatestReportIntoView();
    input.focus();
  }
}

function renderChatPanel() {
  const list = $("#chat-list");
  const thread = $("#chat-messages");
  const status = $("#chat-status");
  const sendBtn = $("#chat-send");
  const input = $("#chat-input");
  const countEl = $("#chat-session-count");
  const activeTitle = $("#chat-active-title");
  const activeUpdated = $("#chat-active-updated");
  const renameBtn = $("#chat-rename");
  const deleteBtn = $("#chat-delete");
  if (!list || !thread) return;

  syncChatAgentSelect();
  syncChatFilterChips();

  const sessions = visibleChatSessions();
  if (countEl) {
    countEl.textContent = sessions.length
      ? `${sessions.length} saved`
      : "none yet";
  }

  if (!sessions.length) {
    const emptyMsg =
      state.chatSessionsQuery.trim()
        ? "No sessions match your search."
        : state.chatSessionsKind === "runs"
          ? "No <strong>Agent runs</strong> sessions yet. Run an agent to populate this inbox."
          : state.chatSessionsKind === "chats" && state.chatSessionsFilter === "agent" && state.chatAgentId
            ? "No chat sessions for this agent yet. Click <strong>New session</strong> to start one."
            : state.chatSessionsKind === "chats"
              ? "No chat sessions yet (runs are hidden by the <strong>Chats</strong> filter)."
              : state.chatSessionsFilter === "agent" && !state.chatAgentId
                ? "Select an agent to filter sessions, or switch to <strong>All agents</strong>."
                : state.chatSessionsFilter === "agent"
                  ? "No sessions for this agent yet. Click <strong>New session</strong> to start one."
                  : "No saved sessions yet. Pick an agent and start chatting — conversations appear here.";
    list.innerHTML = `<li class="muted chat-list-empty">${emptyMsg}</li>`;
  } else {
    list.innerHTML = sessions
      .map((c) => {
        const msgs = Number(c.message_count) || 0;
        const msgLabel = msgs === 1 ? "1 msg" : `${msgs} msgs`;
        const agentLabel = agentName(c.agent_id);
        const unread = sessionUnreadCount(c);
        const unreadChip =
          unread > 0
            ? `<span class="chip chat-unread-chip">${unread > 99 ? "99+" : unread}</span>`
            : "";
        return `
      <li>
        <button type="button" class="chat-list-item ${c.id === state.chatId ? "active" : ""} ${unread > 0 ? "unread" : ""}" data-id="${c.id}" title="${escapeHtml(fmtTime(c.updated_at))}">
          <strong>${escapeHtml(c.title || "New session")}</strong>
          <span class="chat-list-agent">${escapeHtml(agentLabel)}</span>
          <span class="chat-list-meta">
            <span>${escapeHtml(fmtTime(c.updated_at))}</span>
            <span class="muted">${escapeHtml(fmtRelative(c.updated_at))}</span>
            <span class="chip">${escapeHtml(msgLabel)}</span>
            ${unreadChip}
          </span>
        </button>
      </li>`;
      })
      .join("");
    $$("#chat-list [data-id]").forEach((btn) => {
      btn.onclick = () => selectChat(btn.dataset.id);
    });
  }

  const active = sessionSummary(state.chatId);
  const agent = chatAgent();
  if (activeTitle) {
    if (state.chatId) {
      activeTitle.textContent = active?.title || "Session";
    } else if (agent) {
      activeTitle.textContent = `New chat with ${formatAgentLabel(agent)}`;
    } else {
      activeTitle.textContent = "New session";
    }
  }
  if (activeUpdated) {
    if (active?.updated_at) {
      activeUpdated.innerHTML = `${escapeHtml(fmtTime(active.updated_at))} <span class="muted">· ${escapeHtml(fmtRelative(active.updated_at))}</span>`;
    } else {
      activeUpdated.textContent = agent
        ? "Not saved until you send a message"
        : "Select an agent to begin";
    }
  }
  if (renameBtn) renameBtn.hidden = !state.chatId;
  if (deleteBtn) deleteBtn.hidden = !state.chatId;

  const avatarEl = $("#chat-agent-avatar");
  if (avatarEl) {
    if (agent) {
      mountAvatarHtml(avatarEl, renderAgentAvatar(agent, { size: "sm" }));
      const mounted = $("#chat-agent-avatar");
      if (mounted) mounted.hidden = false;
    } else if (avatarEl) {
      avatarEl.hidden = true;
      avatarEl.innerHTML = "";
      avatarEl.className = "agent-avatar sm";
    }
  }

  const pendingBubble = renderPendingChatBubbles();

  if (!state.chatAgentId && !state.chatId && !state.chatSending) {
    thread.innerHTML = `<div class="detail-empty">Select an agent above, or open a session from the left.</div>`;
  } else if (!state.chatId && !state.chatMessages.length && !state.chatSending) {
    thread.innerHTML = `<div class="detail-empty">New chat with <strong>${escapeHtml(formatAgentLabel(agent, "agent"))}</strong>. Send a message, or click <strong>New session</strong>.</div>`;
  } else if (!state.chatMessages.length && !state.chatSending) {
    thread.innerHTML = `<div class="detail-empty">Send a message to begin this session.</div>`;
  } else {
    const messagesHtml = state.chatMessages
      .map((m, idx) => renderChatMessageBubble(m, idx))
      .join("");
    thread.innerHTML = messagesHtml + pendingBubble;
    wireChatHtmlPreviews(thread);
    thread.scrollTop = thread.scrollHeight;
  }

  if (status) {
    if (state.chatSending) {
      status.hidden = false;
      const hasTools = (state.chatStreamTools || []).length > 0;
      if (state.chatStreamGeneratingHtml) {
        status.textContent = "Generating HTML report…";
      } else if (state.chatStreamStarted) {
        status.textContent = "Streaming reply…";
      } else if (hasTools) {
        status.textContent = "Working… using tools";
      } else {
        status.textContent = "Waiting for agent reply…";
      }
    } else {
      status.hidden = true;
      status.textContent = "";
    }
  }

  const attachBar = $("#chat-attachments");
  if (attachBar) {
    const atts = state.chatAttachments || [];
    if (!atts.length) {
      attachBar.hidden = true;
      attachBar.innerHTML = "";
    } else {
      attachBar.hidden = false;
      attachBar.innerHTML = atts
        .map(
          (a) =>
            `<span class="chip" title="${escapeHtml(a.path)}">${escapeHtml(a.name)}</span>`,
        )
        .join(" ");
    }
  }
  const attachLabel = $("#chat-attach-label");
  if (attachLabel) {
    attachLabel.hidden = !state.chatId || state.chatSending;
  }
  const noAgent = !state.chatAgentId;
  const cancelBtn = $("#chat-cancel");
  if (sendBtn) sendBtn.disabled = state.chatSending || noAgent;
  if (cancelBtn) {
    cancelBtn.hidden = !state.chatSending;
    cancelBtn.onclick = () => cancelChatStream();
  }
  if (input) {
    input.disabled = state.chatSending || noAgent;
    input.placeholder = noAgent
      ? "Select an agent to message…"
      : "Message the agent…";
  }
}

async function loadAllSessions() {
  state.allSessions = await api("/chats?limit=200");
  updateChatNavBadge();
}

async function submitRun(event) {
  event.preventDefault();
  const prompt = $("#run-form").prompt.value.trim();
  try {
    const body = prompt ? { prompt } : {};
    const accepted = await api(`/agents/${state.runAgentId}/run`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    $("#run-dialog").close();
    toast(`Run accepted · ${accepted.execution_id}`);
    state.selectedAgentId = state.runAgentId;
    state.selectedExecutionId = accepted.execution_id;
    setView("executions");
    await refreshSelectedLogs();
    startPolling(accepted.execution_id);
  } catch (err) {
    toast(err.message, "error");
  }
}

async function deleteAgent(agent) {
  const ok = await confirmDialog({
    title: "Delete agent",
    message: `Delete agent “${agent.name}”? This removes the agent config. Chat sessions for this agent may remain orphaned.`,
    confirmLabel: "Delete",
  });
  if (!ok) return;
  try {
    await api(`/agents/${agent.id}`, { method: "DELETE" });
    if (state.selectedAgentId === agent.id) {
      state.selectedAgentId = null;
      state.logs = [];
      state.selectedExecution = null;
    }
    if (state.chatAgentId === agent.id) {
      state.chatAgentId = null;
      prepareNewChatContext();
    }
    toast("Agent deleted");
    await loadAgents();
    loadAllSessions().catch(() => {});
  } catch (err) {
    toast(err.message, "error");
  }
}

async function loadAgents() {
  state.agents = await api("/agents");
  if (
    state.selectedAgentId &&
    !state.agents.some((a) => a.id === state.selectedAgentId)
  ) {
    state.selectedAgentId = null;
  }
  if (!state.selectedAgentId && state.agents.length) {
    state.selectedAgentId = state.agents[0].id;
  }
  render();
}

async function loadAgentTemplates() {
  try {
    state.agentTemplates = await api("/agent-templates");
  } catch {
    state.agentTemplates = [];
  }
  populateTemplateSelect();
}

async function refreshSelectedLogs() {
  if (!state.selectedAgentId) {
    state.logs = [];
    state.selectedExecution = null;
    render();
    return;
  }
  state.logs = await api(`/agents/${state.selectedAgentId}/logs?limit=50`);
  if (
    state.selectedExecutionId &&
    state.logs.some((l) => l.id === state.selectedExecutionId)
  ) {
    state.selectedExecution = await api(
      `/executions/${state.selectedExecutionId}`,
    );
  } else if (state.logs.length) {
    state.selectedExecutionId = state.logs[0].id;
    state.selectedExecution = await api(
      `/executions/${state.selectedExecutionId}`,
    );
  } else {
    state.selectedExecutionId = null;
    state.selectedExecution = null;
  }
  render();
}

async function selectAgent(agentId) {
  state.selectedAgentId = agentId;
  state.selectedExecutionId = null;
  state.selectedExecution = null;
  if (state.view === "agents") render();
  await refreshSelectedLogs();
}

async function selectExecution(executionId) {
  state.selectedExecutionId = executionId;
  state.selectedExecution = await api(`/executions/${executionId}`);
  render();
  if (state.selectedExecution.status === "running") {
    startPolling(executionId);
  } else {
    stopPolling();
  }
}

function startPolling(executionId) {
  stopPolling();
  state.pollTimer = setInterval(async () => {
    try {
      const exec = await api(`/executions/${executionId}`);
      state.selectedExecution = exec;
      if (state.view === "executions") renderExecutionDetail();
      if (exec.status !== "running") {
        stopPolling();
        state.logs = await api(`/agents/${exec.agent_id}/logs?limit=50`);
        if (state.view === "executions") render();
      }
    } catch {
      stopPolling();
    }
  }, 1500);
}

function stopPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function loadHealth() {
  try {
    state.health = await api("/health");
  } catch {
    state.health = { status: "down", mongo: "down" };
  }
  const pill = $("#health-pill");
  const label = $("#health-label");
  pill.classList.remove("ok", "degraded", "down");
  const status = state.health.status || "down";
  pill.classList.add(status === "ok" ? "ok" : status === "degraded" ? "degraded" : "down");
  label.textContent = `${status} · mongo ${state.health.mongo}`;
  if (state.view === "system") renderSystem();
}

function selectedAgent() {
  return state.agents.find((a) => a.id === state.selectedAgentId) || null;
}

function agentStatusBadge(agent) {
  const status = agent.status || (agent.api_key_set ? "ready" : "not_configured");
  const label = agent.status_label || status.replace(/_/g, " ");
  return `<span class="badge ${escapeHtml(status)}">${escapeHtml(label)}</span>`;
}

function agentPausedBadge(agent) {
  if (!agent?.paused) return "";
  return `<span class="badge paused">Paused</span>`;
}

async function setAgentPaused(agent, paused) {
  if (!agent) return;
  const action = paused ? "pause" : "resume";
  try {
    const updated = await api(`/agents/${agent.id}/${action}`, { method: "POST" });
    const idx = state.agents.findIndex((a) => a.id === agent.id);
    if (idx >= 0) state.agents[idx] = { ...state.agents[idx], ...updated };
    render();
    toast(paused ? "Agent paused — cron stopped" : "Agent resumed", "ok");
  } catch (err) {
    toast(err.message, "error");
  }
}

function agentStatusErrorSnip(agent, max = 72) {
  if (agent.status !== "error" || !agent.error_message) return "";
  return `<span class="status-error-snip" title="${escapeHtml(agent.error_message)}">${escapeHtml(excerpt(agent.error_message, max))}</span>`;
}

async function recheckAgentStatus(agentId) {
  try {
    const info = await api(`/agents/${agentId}/status/refresh`, { method: "POST" });
    const idx = state.agents.findIndex((a) => a.id === agentId);
    if (idx >= 0) {
      state.agents[idx] = {
        ...state.agents[idx],
        status: info.status,
        status_label: info.status_label,
        error_message: info.error_message,
        checked_at: info.checked_at,
      };
    }
    render();
    toast(
      info.status === "ready"
        ? "Provider check OK"
        : info.status_label || "Status updated",
      info.status === "error" ? "error" : "ok",
    );
  } catch (err) {
    toast(err.message, "error");
  }
}

/** Close every agent overflow menu (only one may be open). */
function closeAgentMenus() {
  $$(".agent-menu").forEach((menu) => {
    const trigger = menu.querySelector(".agent-menu-trigger");
    const panel = menu.querySelector(".agent-menu-panel");
    if (panel) panel.hidden = true;
    if (trigger) trigger.setAttribute("aria-expanded", "false");
  });
}

/**
 * Markup for the agent ⋮ overflow menu.
 * @param {object} agent
 * @param {{ runLabel?: string }} [opts]
 */
function agentOverflowMenuHtml(agent, { runLabel = "Run" } = {}) {
  const pauseLabel = agent.paused ? "Resume" : "Pause";
  return `
    <div class="agent-menu">
      <button
        type="button"
        class="icon-btn agent-menu-trigger"
        aria-label="More actions"
        aria-haspopup="menu"
        aria-expanded="false"
      >⋮</button>
      <ul class="agent-menu-panel" role="menu" hidden>
        <li role="none">
          <button type="button" role="menuitem" data-act="run">${escapeHtml(runLabel)}</button>
        </li>
        <li role="none">
          <button type="button" role="menuitem" data-act="pause">${escapeHtml(pauseLabel)}</button>
        </li>
        <li role="none">
          <button type="button" role="menuitem" data-act="edit">Edit</button>
        </li>
        <li role="none">
          <button type="button" role="menuitem" class="is-danger" data-act="delete">Delete</button>
        </li>
      </ul>
    </div>`;
}

/**
 * Wire open/close + action handlers for an agent overflow menu root.
 * @param {ParentNode} root
 * @param {object} agent
 */
function bindAgentOverflowMenu(root, agent) {
  const menu = root.querySelector(".agent-menu");
  if (!menu || menu.dataset.bound === "1") return;
  menu.dataset.bound = "1";
  const trigger = menu.querySelector(".agent-menu-trigger");
  const panel = menu.querySelector(".agent-menu-panel");
  if (!trigger || !panel) return;

  const setOpen = (open) => {
    if (open) {
      closeAgentMenus();
      const rect = trigger.getBoundingClientRect();
      panel.style.top = `${Math.round(rect.bottom + 6)}px`;
      panel.style.right = `${Math.round(window.innerWidth - rect.right)}px`;
      panel.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
    } else {
      panel.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }
  };

  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    setOpen(panel.hidden);
  });

  panel.addEventListener("click", (event) => {
    event.stopPropagation();
  });

  $$("[data-act]", panel).forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      const act = btn.dataset.act;
      setOpen(false);
      if (act === "run") openRunDialog(agent);
      else if (act === "pause") setAgentPaused(agent, !agent.paused);
      else if (act === "edit") openAgentDialog(agent);
      else if (act === "delete") deleteAgent(agent);
    });
  });
}

function wireAgentMenusOnce() {
  if (wireAgentMenusOnce._done) return;
  wireAgentMenusOnce._done = true;
  document.addEventListener("click", (event) => {
    if (event.target.closest(".agent-menu")) return;
    closeAgentMenus();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAgentMenus();
  });
  window.addEventListener("resize", closeAgentMenus);
  document.addEventListener(
    "scroll",
    (event) => {
      if (event.target.closest?.(".agent-menu")) return;
      closeAgentMenus();
    },
    true,
  );
}

function renderAgents() {
  wireAgentMenusOnce();
  const root = $("#view-agents");
  if (!state.agents.length) {
    root.innerHTML = `
      <div class="panel">
        <div class="empty">
          No agents yet. Create one, or run
          <code>python scripts/seed_demo.py</code>.
        </div>
      </div>`;
    return;
  }

  const agent = selectedAgent();
  root.innerHTML = `
    <div class="layout-split">
      <div class="panel">
        <div class="panel-head"><h3>Fleet</h3><span class="muted">${state.agents.length} agents</span></div>
        <div class="panel-body" style="padding:0">
          <table class="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Provider</th>
                <th>Cron</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${state.agents
                .map(
                  (a) => `
                <tr data-id="${a.id}" class="${a.id === state.selectedAgentId ? "selected" : ""}">
                  <td>
                    <div class="agent-name-cell">
                      ${renderAgentAvatar(a)}
                      <div>
                        <strong>${escapeHtml(formatAgentLabel(a))}</strong>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div class="status-cell">
                      ${agentStatusBadge(a)}
                      ${agentPausedBadge(a)}
                      ${agentStatusErrorSnip(a)}
                    </div>
                  </td>
                  <td>${escapeHtml(a.provider)} / ${escapeHtml(a.model_name)}</td>
                  <td>${escapeHtml(describeCron(a.cron_schedule))}</td>
                  <td class="row-actions" onclick="event.stopPropagation()">
                    <button type="button" class="ghost-btn" data-act="chat">Chat</button>
                    ${agentOverflowMenuHtml(a, { runLabel: "Run" })}
                  </td>
                </tr>`,
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
      <div class="panel" id="agent-detail-panel"></div>
    </div>`;

  $$("#view-agents tbody tr").forEach((row) => {
    row.addEventListener("click", () => selectAgent(row.dataset.id));
    const a = state.agents.find((x) => x.id === row.dataset.id);
    row.querySelector('[data-act="chat"]').onclick = (e) => {
      e.stopPropagation();
      openChat(a, null, "agents");
    };
    bindAgentOverflowMenu(row, a);
  });

  renderAgentDetail(agent);
}

function renderAgentDetail(agent) {
  wireAgentMenusOnce();
  const panel = $("#agent-detail-panel");
  if (!panel) return;
  if (!agent) {
    panel.innerHTML = `<div class="detail-empty">Select an agent</div>`;
    return;
  }
  const statusChecked = agent.checked_at
    ? `<span class="muted"> · checked ${escapeHtml(fmtTime(agent.checked_at))}</span>`
    : "";
  const statusErrorBlock =
    agent.status === "error" && agent.error_message
      ? `<p class="status-error-full mono-block">${escapeHtml(agent.error_message)}</p>`
      : "";

  panel.innerHTML = `
    <div class="panel-head">
      <div class="detail-title-with-avatar">
        ${renderAgentAvatar(agent, { size: "lg" })}
        <h3>${escapeHtml(formatAgentLabel(agent))}</h3>
      </div>
      <div class="row-actions">
        <button type="button" class="primary-btn" id="detail-chat">Chat</button>
        ${agentOverflowMenuHtml(agent, { runLabel: "Run now" })}
      </div>
    </div>
    <div class="panel-body">
      <dl class="kv">
        <div><dt>ID</dt><dd>${escapeHtml(agent.id)}</dd></div>
        <div><dt>Role</dt><dd>${escapeHtml(agent.role)}</dd></div>
        <div>
          <dt>Status</dt>
          <dd>
            ${agentStatusBadge(agent)} ${agentPausedBadge(agent)}${statusChecked}
            <button type="button" class="ghost-btn" id="detail-recheck" style="margin-left:0.5rem">Recheck</button>
            ${statusErrorBlock}
          </dd>
        </div>
        <div><dt>Provider</dt><dd>${escapeHtml(agent.provider)} · ${escapeHtml(agent.model_name)}</dd></div>
        ${
          agent.provider === "ollama"
            ? `<div><dt>Endpoint</dt><dd><code class="mono">${escapeHtml(
                agent.base_url || "OLLAMA_BASE_URL default",
              )}</code></dd></div>`
            : ""
        }
        <div><dt>API key</dt><dd>${
          agent.api_key_set
            ? `<code class="mono">${escapeHtml(agent.api_key_preview || "••••")}</code> <span class="muted">configured</span>`
            : agent.provider === "ollama"
              ? `<span class="muted">not required</span>`
              : `<span class="muted">missing</span>`
        }</dd></div>
        <div><dt>Schedule</dt><dd>${escapeHtml(describeCron(agent.cron_schedule))}${agent.cron_schedule ? ` <span class="muted">(${escapeHtml(agent.cron_schedule)})</span>` : ""}${agent.paused && agent.cron_schedule ? ` <span class="muted">(paused — cron not running)</span>` : ""}</dd></div>
        <div><dt>Updated</dt><dd>${escapeHtml(fmtTime(agent.updated_at))}</dd></div>
      </dl>
      <p class="muted" style="margin:1rem 0 0.35rem">Attached sources</p>
      ${
        (agent.sources || []).length
          ? `<ul class="attached-source-list">${agent.sources
              .map(
                (s) => `
            <li>
              <strong>${escapeHtml(s.title)}</strong>
              <span class="chip">${escapeHtml(s.type)}</span>
              <p class="muted">${escapeHtml(excerpt(s.description || "No description", 220))}</p>
            </li>`,
              )
              .join("")}</ul>`
          : `<p class="muted">None attached. Edit the agent to attach library sources.</p>`
      }
      <p class="muted" style="margin:1rem 0 0.35rem">System prompt</p>
      <pre class="mono-block">${escapeHtml(agent.system_prompt)}</pre>
      <p class="muted" style="margin:1rem 0 0.35rem">Default prompt</p>
      <pre class="mono-block">${escapeHtml(agent.default_prompt || "—")}</pre>
    </div>`;
  $("#detail-chat").onclick = () => openChat(agent, null, "agents");
  bindAgentOverflowMenu(panel, agent);
  const recheckBtn = $("#detail-recheck");
  if (recheckBtn) {
    recheckBtn.onclick = () => recheckAgentStatus(agent.id);
  }
}

function selectedSource() {
  return state.sources.find((s) => s.id === state.selectedSourceId) || null;
}

function renderSources() {
  const root = $("#view-sources");
  if (!state.sources.length) {
    root.innerHTML = `
      <div class="panel">
        <div class="empty">
          No data sources yet. Create one for the demo DB, or run
          <code>python scripts/seed_demo.py</code>.
        </div>
      </div>`;
    return;
  }

  const source = selectedSource();
  root.innerHTML = `
    <div class="layout-split">
      <div class="panel">
        <div class="panel-head"><h3>Library</h3><span class="muted">${state.sources.length} sources</span></div>
        <div class="panel-body" style="padding:0">
          <table class="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Type</th>
                <th>Updated</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${state.sources
                .map(
                  (s) => `
                <tr data-id="${s.id}" class="${s.id === state.selectedSourceId ? "selected" : ""}">
                  <td>
                    <strong>${escapeHtml(s.title)}</strong><br />
                    <span class="muted">${escapeHtml(excerpt(s.description || "", 80))}</span>
                  </td>
                  <td><span class="chip">${escapeHtml(s.type)}</span></td>
                  <td>${fmtTime(s.updated_at)}</td>
                  <td class="row-actions" onclick="event.stopPropagation()">
                    <button type="button" class="ghost-btn" data-act="edit">Edit</button>
                    <button type="button" class="danger-btn" data-act="delete">Delete</button>
                  </td>
                </tr>`,
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
      <div class="panel" id="source-detail-panel"></div>
    </div>`;

  $$("#view-sources tbody tr").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedSourceId = row.dataset.id;
      renderSources();
      syncUrl();
    });
    row.querySelector('[data-act="edit"]').onclick = (e) => {
      e.stopPropagation();
      const s = state.sources.find((x) => x.id === row.dataset.id);
      openSourceDialog(s);
    };
    row.querySelector('[data-act="delete"]').onclick = (e) => {
      e.stopPropagation();
      const s = state.sources.find((x) => x.id === row.dataset.id);
      deleteSource(s);
    };
  });

  renderSourceDetail(source);
}

function renderSourceDetail(source) {
  const panel = $("#source-detail-panel");
  if (!panel) return;
  if (!source) {
    panel.innerHTML = `<div class="detail-empty">Select a data source</div>`;
    return;
  }
  const cfg = source.config || {};
  const cfgLines =
    source.type === "files"
      ? `<div><dt>Path prefix</dt><dd>${escapeHtml(cfg.path_prefix || "—")}</dd></div>
         <div><dt>Files root</dt><dd><code>_library/${escapeHtml(source.id)}/</code></dd></div>`
      : `<div><dt>Engine</dt><dd>${escapeHtml(cfg.engine || "—")}</dd></div>
         <div><dt>Connection</dt><dd>${cfg.connection_string_set ? "configured" : "missing"}</dd></div>
         <div><dt>SSH</dt><dd>${cfg.ssh?.enabled ? "enabled" : "off"}</dd></div>`;

  const tablesSection =
    source.type === "sql"
      ? `<div class="schema-panel" style="margin-top:1.25rem">
          <div class="panel-head" style="padding:0 0 0.5rem;border:0">
            <h3 style="font-size:1rem">Tables</h3>
            <button type="button" class="ghost-btn" id="detail-source-schema-refresh">Refresh</button>
          </div>
          <div id="detail-source-schema" class="schema-tables">
            <p class="muted">Loading schema…</p>
          </div>
        </div>`
      : "";

  panel.innerHTML = `
    <div class="panel-head">
      <h3>${escapeHtml(source.title)}</h3>
      <div class="row-actions">
        <button type="button" class="ghost-btn" id="detail-source-test">Test connection</button>
        <button type="button" class="ghost-btn" id="detail-source-edit">Edit</button>
      </div>
    </div>
    <div class="panel-body">
      <dl class="kv">
        <div><dt>ID</dt><dd>${escapeHtml(source.id)}</dd></div>
        <div><dt>Type</dt><dd><span class="chip">${escapeHtml(source.type)}</span></dd></div>
        ${cfgLines}
        <div><dt>Updated</dt><dd>${fmtTime(source.updated_at)}</dd></div>
      </dl>
      <p class="hint" id="detail-source-test-result" hidden></p>
      <p class="muted" style="margin:1rem 0 0.35rem">Description</p>
      <pre class="mono-block">${escapeHtml(source.description || "—")}</pre>
      ${tablesSection}
    </div>`;
  $("#detail-source-edit").onclick = () => openSourceDialog(source);
  $("#detail-source-test").onclick = () => testSavedSource(source);
  if (source.type === "sql") {
    const refreshBtn = $("#detail-source-schema-refresh");
    if (refreshBtn) {
      refreshBtn.onclick = () => loadSourceSchema(source.id);
    }
    loadSourceSchema(source.id);
  }
}

function renderSchemaTables(schema) {
  const tables = schema?.tables || [];
  if (!tables.length) {
    return `<p class="muted">No tables found in this database.</p>`;
  }
  return `<ul class="schema-table-list">
    ${tables
      .map((t) => {
        const cols = t.columns || [];
        const count =
          t.row_count == null ? "" : ` · ${Number(t.row_count).toLocaleString()} rows`;
        const colSummary = cols.length
          ? cols
              .map(
                (c) =>
                  `<li><code>${escapeHtml(c.name)}</code> <span class="muted">${escapeHtml(c.data_type || "")}</span></li>`,
              )
              .join("")
          : `<li class="muted">No columns</li>`;
        return `<li>
          <details>
            <summary>
              <strong>${escapeHtml(t.name)}</strong>
              <span class="muted">${cols.length} columns${count}</span>
            </summary>
            <ul class="schema-col-list">${colSummary}</ul>
          </details>
        </li>`;
      })
      .join("")}
  </ul>`;
}

async function loadSourceSchema(sourceId) {
  const box = $("#detail-source-schema");
  if (!box) return;
  box.innerHTML = `<p class="muted">Loading schema…</p>`;
  try {
    const schema = await api(`/sources/${encodeURIComponent(sourceId)}/schema`);
    box.innerHTML = renderSchemaTables(schema);
  } catch (err) {
    box.innerHTML = `<p class="hint" style="color:var(--danger, #b33)">${escapeHtml(err.message || String(err))}</p>`;
  }
}

function renderExecutions() {
  const root = $("#view-executions");
  const agentOptions = state.agents
    .map(
      (a) =>
        `<option value="${a.id}" ${a.id === state.selectedAgentId ? "selected" : ""}>${escapeHtml(formatAgentLabel(a))}</option>`,
    )
    .join("");

  root.innerHTML = `
    <div class="panel" style="margin-bottom:1rem">
      <div class="panel-body" style="display:flex;gap:0.75rem;align-items:end;flex-wrap:wrap">
        <label style="min-width:220px">
          Agent
          <select id="exec-agent-select">${agentOptions || "<option value=''>No agents</option>"}</select>
        </label>
        <button type="button" class="ghost-btn" id="exec-refresh">Refresh</button>
      </div>
    </div>
    <div class="layout-split">
      <div class="panel">
        <div class="panel-head"><h3>Runs</h3><span class="muted">${state.logs.length}</span></div>
        <div class="panel-body" style="padding:0" id="exec-table-wrap"></div>
      </div>
      <div class="panel" id="exec-detail-panel"></div>
    </div>`;

  const select = $("#exec-agent-select");
  if (select) {
    select.onchange = async () => {
      state.selectedAgentId = select.value || null;
      state.selectedExecutionId = null;
      await refreshSelectedLogs();
      syncUrl();
    };
  }
  $("#exec-refresh").onclick = () => refreshSelectedLogs();
  renderExecTable();
  renderExecutionDetail();
}

function renderExecTable() {
  const wrap = $("#exec-table-wrap");
  if (!wrap) return;
  if (!state.logs.length) {
    wrap.innerHTML = `<div class="empty">No executions for this agent yet.</div>`;
    return;
  }
  wrap.innerHTML = `
    <table class="table">
      <thead>
        <tr><th>Status</th><th>Trigger</th><th>Started</th><th>ID</th></tr>
      </thead>
      <tbody>
        ${state.logs
          .map((log) => {
            const isStuck =
              log.status === "failed" &&
              String(log.error_message || "").startsWith("Stuck:");
            const statusLabel = isStuck ? "failed · stuck" : log.status;
            const elapsed =
              log.status === "running"
                ? formatDurationSeconds(
                    (Date.now() - new Date(log.start_time).getTime()) / 1000,
                  )
                : "";
            return `
          <tr data-id="${log.id}" class="${log.id === state.selectedExecutionId ? "selected" : ""}">
            <td class="status-cell ${isStuck ? "execution-stuck" : ""}">
              <span class="badge ${log.status}">${statusLabel}</span>
              ${elapsed ? `<span class="muted">elapsed ${elapsed}</span>` : ""}
            </td>
            <td><span class="badge ${log.trigger_type}">${log.trigger_type}</span></td>
            <td>${fmtTime(log.start_time)}</td>
            <td class="muted">${escapeHtml(log.id.slice(0, 8))}…</td>
          </tr>`;
          })
          .join("")}
      </tbody>
    </table>`;
  $$("tbody tr", wrap).forEach((row) => {
    row.onclick = () => selectExecution(row.dataset.id);
  });
}

function renderExecutionDetail() {
  const panel = $("#exec-detail-panel");
  if (!panel) return;
  const exec = state.selectedExecution;
  if (!exec) {
    panel.innerHTML = `<div class="detail-empty">Select a run to inspect</div>`;
    return;
  }
  const isStuck =
    exec.status === "failed" &&
    String(exec.error_message || "").startsWith("Stuck:");
  const statusLabel = isStuck ? "failed · stuck" : exec.status;
  const elapsed =
    exec.status === "running"
      ? formatDurationSeconds(
          (Date.now() - new Date(exec.start_time).getTime()) / 1000,
        )
      : "";
  const steps = (exec.tool_calls || [])
    .map(
      (step) => `
      <div class="step">
        <strong>${escapeHtml(step.step_type)}</strong>
        ${step.tool_name ? ` · ${escapeHtml(step.tool_name)}` : ""}
        <div class="muted">${fmtTime(step.timestamp)}</div>
        ${step.message ? `<div>${escapeHtml(step.message)}</div>` : ""}
        ${
          step.input != null
            ? `<pre class="mono-block" style="max-height:120px">${escapeHtml(formatJson(step.input))}</pre>`
            : ""
        }
        ${
          step.output != null
            ? `<pre class="mono-block" style="max-height:120px">${escapeHtml(formatJson(step.output))}</pre>`
            : ""
        }
      </div>`,
    )
    .join("");

  panel.innerHTML = `
    <div class="panel-head">
      <h3>Run detail</h3>
      <div class="row-actions">
        ${
          exec.status === "running"
            ? `<button type="button" class="danger-btn" id="btn-cancel-exec">Cancel</button>`
            : ""
        }
        <button type="button" class="ghost-btn" id="btn-open-in-chat">Open in Chat</button>
        ${
          exec.output_html
            ? `<button type="button" class="primary-btn" id="btn-open-report">Open HTML</button>`
            : ""
        }
      </div>
    </div>
    <div class="panel-body">
      <dl class="kv">
        <div><dt>Status</dt><dd class="${isStuck ? "execution-stuck" : ""}"><span class="badge ${exec.status}">${statusLabel}</span></dd></div>
        <div><dt>Trigger</dt><dd>${escapeHtml(exec.trigger_type)}</dd></div>
        <div><dt>Start</dt><dd>${fmtTime(exec.start_time)}</dd></div>
        ${elapsed ? `<div><dt>Elapsed</dt><dd>${elapsed}</dd></div>` : ""}
        <div><dt>End</dt><dd>${fmtTime(exec.end_time)}</dd></div>
        <div><dt>Execution</dt><dd>${escapeHtml(exec.id)}</dd></div>
      </dl>
      ${
        exec.error_message
          ? `<p class="muted" style="margin:1rem 0 0.35rem">Error</p><pre class="mono-block">${escapeHtml(exec.error_message)}</pre>`
          : ""
      }
      <p class="muted" style="margin:1rem 0 0.35rem">Output</p>
      <pre class="mono-block">${escapeHtml(exec.output_text || "—")}</pre>
      <p class="muted" style="margin:1rem 0 0.35rem">Trace (${(exec.tool_calls || []).length})</p>
      <div class="steps">${steps || '<div class="muted">No steps yet</div>'}</div>
    </div>`;

  const reportBtn = $("#btn-open-report");
  if (reportBtn) {
    reportBtn.onclick = () => openReport(exec.output_html);
  }
  const chatBtn = $("#btn-open-in-chat");
  if (chatBtn) {
    chatBtn.onclick = () => openExecutionInChat(exec);
  }
  const cancelBtn = $("#btn-cancel-exec");
  if (cancelBtn) {
    cancelBtn.onclick = async () => {
      try {
        await api(`/executions/${exec.id}/cancel`, {
          method: "POST",
          body: "{}",
        });
        toast("Cancel requested");
        await refreshSelectedLogs();
        await selectExecution(exec.id);
        loadActivity().catch(() => {});
      } catch (err) {
        toast(err.message, "error");
      }
    };
  }
}

async function openExecutionInChat(exec) {
  if (!exec?.agent_id) {
    toast("Execution has no agent", "error");
    return;
  }
  const agent =
    (state.agents || []).find((a) => a.id === exec.agent_id) ||
    (await api(`/agents/${exec.agent_id}`).catch(() => null));
  if (!agent) {
    toast("Agent not found", "error");
    return;
  }
  try {
    await loadAllSessions();
    const runsSession = (state.allSessions || []).find(
      (s) => s.agent_id === exec.agent_id && s.title === "Agent runs",
    );
    await openChat(agent, runsSession?.id || null, "executions");
    if (!runsSession) {
      toast("No Agent runs session yet — open after a run completes");
    }
  } catch (err) {
    toast(err.message, "error");
  }
}

function openReport(html) {
  const frame = $("#report-frame");
  if (!frame) return;
  try {
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    _htmlBlobUrls.add(url);
    frame.removeAttribute("srcdoc");
    frame.src = url;
  } catch {
    frame.srcdoc = html;
  }
  frame.style.minHeight = "360px";
  $("#report-dialog").showModal();
}

async function loadUsage() {
  try {
    state.usage = await api("/usage?days=7");
  } catch {
    state.usage = null;
  }
}

function renderSystem() {
  const h = state.health || {};
  const usage = state.usage;
  const usageRows = usage?.by_agent_day || [];
  const totals = usage?.totals || {};
  $("#view-system").innerHTML = `
    <div class="system-grid">
      <div class="stat"><div class="label">Status</div><div class="value">${escapeHtml(h.status || "—")}</div></div>
      <div class="stat"><div class="label">Mongo</div><div class="value">${escapeHtml(h.mongo || "—")}</div></div>
      <div class="stat"><div class="label">Scheduler</div><div class="value">${escapeHtml(h.scheduler || "—")}</div></div>
      <div class="stat"><div class="label">Agents</div><div class="value">${state.agents.length}</div></div>
      <div class="stat"><div class="label">Requests (7d)</div><div class="value">${escapeHtml(String(totals.request_count ?? "—"))}</div></div>
      <div class="stat"><div class="label">Service</div><div class="value" style="font-size:1rem">${escapeHtml(h.service || "coia-agent-harness")}</div></div>
    </div>
    <div class="panel" style="margin-top:1rem">
      <div class="panel-head"><h3>Usage (last ${escapeHtml(String(usage?.days ?? 7))} days)</h3></div>
      <div class="panel-body">
        ${
          usageRows.length
            ? `<table class="table"><thead><tr><th>Day</th><th>Agent</th><th>Model</th><th>Requests</th></tr></thead><tbody>
            ${usageRows
              .slice(0, 40)
              .map(
                (r) => `<tr>
                <td>${escapeHtml(r.day)}</td>
                <td>${escapeHtml(agentName(r.agent_id))}</td>
                <td>${escapeHtml(r.model || r.provider || "—")}</td>
                <td>${escapeHtml(String(r.request_count))}</td>
              </tr>`,
              )
              .join("")}
            </tbody></table>`
            : `<p class="muted">No usage recorded yet. Chat and runs increment a rough request counter.</p>`
        }
      </div>
    </div>
    <div class="panel" style="margin-top:1rem">
      <div class="panel-head"><h3>API shortcuts</h3></div>
      <div class="panel-body">
        <pre class="mono-block">GET  /health
GET  /agents
GET  /agents/{id}/status
POST /agents/{id}/status/refresh
GET  /sources
POST /agents/{id}/run
POST /agents/{id}/pause
POST /agents/{id}/resume
GET  /agents/{id}/logs
POST /agents/{id}/chats
GET  /agents/{id}/chats
GET  /chats
GET  /chats/{id}
PATCH /chats/{id}
DELETE /chats/{id}
POST /chats/{id}/messages
GET  /executions/{id}
OpenAPI: /docs</pre>
      </div>
    </div>`;
}

function renderChatView() {
  const empty = $("#chat-empty");
  const workspace = $("#chat-workspace");
  if (!empty || !workspace) return;
  if (!state.agents.length) {
    empty.hidden = false;
    workspace.hidden = true;
    return;
  }
  empty.hidden = true;
  workspace.hidden = false;
  renderChatPanel();
}

function updateActivityNavBadge() {
  const el = $("#nav-activity-count");
  if (!el) return;
  const n = Number(state.activityCount) || 0;
  if (n > 0) {
    el.hidden = false;
    el.textContent = String(n);
  } else {
    el.hidden = true;
    el.textContent = "0";
  }
}

async function loadActivity() {
  const data = await api("/activity");
  state.activityItems = data.items || [];
  state.activityCount = data.count ?? state.activityItems.length;
  updateActivityNavBadge();
  if (state.view === "activity") renderActivity();
}

async function cancelActivityItem(item) {
  try {
    if (item.kind === "run" && item.execution_id) {
      await api(`/executions/${item.execution_id}/cancel`, {
        method: "POST",
        body: "{}",
      });
      toast("Run cancel requested");
    } else if (item.kind === "chat" && item.chat_id) {
      await api(`/chats/${item.chat_id}/cancel`, {
        method: "POST",
        body: "{}",
      });
      toast("Chat cancel requested");
    }
  } catch (err) {
    toast(err.message, "error");
  }
  await loadActivity().catch(() => {});
}

function openActivityItem(item) {
  if (item.kind === "run" && item.execution_id) {
    state.selectedAgentId = item.agent_id || state.selectedAgentId;
    state.selectedExecutionId = item.execution_id;
    setView("executions");
    refreshSelectedLogs().then(() => selectExecution(item.execution_id));
    return;
  }
  if (item.kind === "chat" && item.chat_id) {
    const agent = state.agents.find((a) => a.id === item.agent_id);
    if (agent) {
      state.chatAgentId = agent.id;
      state.chatOpenedFrom = "agents";
      setView("chat");
      selectChat(item.chat_id);
    } else {
      toast("Agent for this chat is missing", "error");
    }
  }
}

function renderActivity() {
  const root = $("#view-activity");
  if (!root) return;
  const items = state.activityItems || [];
  if (!items.length) {
    root.innerHTML = `
      <div class="panel">
        <div class="empty">
          Nothing in flight. Agent runs and streaming chats appear here while active.
        </div>
      </div>`;
    return;
  }
  root.innerHTML = `
    <div class="panel">
      <div class="panel-head">
        <h3>Live activity</h3>
        <span class="muted">${items.length} active</span>
      </div>
      <div class="panel-body">
        <ul class="activity-list">
          ${items
            .map((item) => {
              const kindLabel = item.kind === "run" ? "run" : "chat";
              const isStuck = item.is_stuck || item.status === "stuck";
              const statusLabel = isStuck
                ? "stuck"
                : item.status || "running";
              const agent =
                state.agents.find((a) => a.id === item.agent_id) || null;
              const agentLabel =
                formatAgentLabel(agent, "") ||
                item.agent_name ||
                agentName(item.agent_id);
              return `
            <li class="activity-item ${isStuck ? "activity-stuck" : ""}" data-id="${escapeHtml(item.id)}">
              <div class="activity-item-main" data-act="open">
                <strong>${escapeHtml(item.title || kindLabel)}</strong>
                <div class="activity-meta">
                  <span class="badge ${escapeHtml(statusLabel)}">${escapeHtml(statusLabel)}</span>
                  ${
                    item.kind === "run" || item.duration_seconds > 0
                      ? `<span>age ${formatDurationSeconds(item.duration_seconds)}</span>`
                      : ""
                  }
                  <span class="chip">${escapeHtml(kindLabel)}</span>
                  <span>${escapeHtml(agentLabel)}</span>
                  <span>${escapeHtml(fmtRelative(item.started_at))}</span>
                </div>
              </div>
              <div class="row-actions">
                <button type="button" class="ghost-btn" data-act="open">Open</button>
                <button type="button" class="danger-btn" data-act="cancel">Cancel</button>
              </div>
            </li>`;
            })
            .join("")}
        </ul>
      </div>
    </div>`;

  $$(".activity-item", root).forEach((row, idx) => {
    const item = items[idx];
    row.querySelectorAll('[data-act="open"]').forEach((btn) => {
      btn.onclick = () => openActivityItem(item);
    });
    row.querySelector('[data-act="cancel"]').onclick = () =>
      cancelActivityItem(item);
  });
}

function render() {
  if (state.view === "agents") renderAgents();
  else if (state.view === "chat") renderChatView();
  else if (state.view === "activity") renderActivity();
  else if (state.view === "sources") renderSources();
  else if (state.view === "executions") renderExecutions();
  else renderSystem();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/** Remove full HTML documents from assistant text when a preview iframe is shown. */
function stripEmbeddedHtmlDocs(text) {
  if (!text) return "";
  return String(text)
    .replace(
      /```(?:html)?\s*(?:<!DOCTYPE html[\s\S]*?<\/html>|<html[\s\S]*?<\/html>)\s*```/gi,
      "",
    )
    .replace(/(?:<!DOCTYPE html[\s\S]*?<\/html>|<html[\s\S]*?<\/html>)/gi, "")
    .trim();
}

/**
 * Sanitize Markdown → HTML for chat bubbles / report captions.
 * Falls back to escaped plain text if marked/DOMPurify are unavailable.
 */
function renderChatMarkdown(text) {
  const raw = String(text ?? "");
  if (!raw) return "";
  const markedLib = globalThis.marked;
  const purify = globalThis.DOMPurify;
  if (!markedLib?.parse || !purify?.sanitize) {
    return escapeHtml(raw);
  }
  try {
    if (typeof markedLib.setOptions === "function") {
      markedLib.setOptions({ gfm: true, breaks: true });
    }
    const html = markedLib.parse(raw);
    return purify.sanitize(html, {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["style", "script", "iframe", "object", "embed", "form"],
      FORBID_ATTR: ["style", "onerror", "onload", "onclick"],
    });
  } catch {
    return escapeHtml(raw);
  }
}

function renderChatMessageBubble(m, idx) {
  const isRun = m.kind === "run_result" || m.kind === "handoff_report";
  // Report cards only for persisted messages with html (never stream placeholders).
  const hasHtml = Boolean(m.html);
  const textForDisplay = hasHtml
    ? stripEmbeddedHtmlDocs(m.content)
    : m.content || "";

  // HTML reports are artifacts, not chat bubbles.
  // While a new reply streams, show a light placeholder so frequent re-renders
  // do not thrash iframes (which can leave them blank).
  if (hasHtml) {
    const title = isRun ? "Executive summary" : "HTML report";
    const caption = textForDisplay
      ? `<div class="chat-report-caption chat-md">${renderChatMarkdown(textForDisplay)}</div>`
      : "";
    const agent = chatAgent();
    const handoffId = agent?.handoff_agent_id;
    const handoffBtn =
      handoffId && !state.chatSending
        ? `<button type="button" class="ghost-btn chat-handoff-report" data-msg-idx="${idx}" title="Send to handoff agent">Send report to…</button>`
        : "";
    const preview = state.chatSending
      ? `<div class="chat-html-preview chat-html-placeholder" style="min-height:120px;padding:1rem;color:var(--muted)">Report saved — finishing reply…</div>`
      : `<div class="chat-html-preview">
          <iframe class="chat-html-frame" data-html-idx="${idx}" title="HTML report preview" sandbox="allow-same-origin" style="height:360px;min-height:360px"></iframe>
        </div>`;
    return `
      <article class="chat-report-card" data-msg-idx="${idx}" aria-label="${escapeHtml(title)}">
        <header class="chat-report-head">
          <div class="chat-report-head-main">
            <span class="chat-report-badge">${escapeHtml(title)}</span>
            <span class="muted chat-report-time">${escapeHtml(fmtTime(m.timestamp))}</span>
          </div>
          <div class="row-actions">
            ${handoffBtn}
            <button type="button" class="ghost-btn chat-expand-report" data-msg-idx="${idx}" title="Open fullscreen">Expand</button>
          </div>
        </header>
        ${caption}
        ${preview}
      </article>`;
  }

  // User messages stay plain; assistant/run text gets sanitized Markdown.
  const useMarkdown = m.role !== "user" && Boolean(textForDisplay);
  const contentBlock = textForDisplay
    ? useMarkdown
      ? `<div class="chat-content chat-md">${renderChatMarkdown(textForDisplay)}</div>`
      : `<div class="chat-content">${escapeHtml(textForDisplay)}</div>`
    : "";
  const classes = ["chat-bubble", `role-${escapeHtml(m.role)}`]
    .filter(Boolean)
    .join(" ");
  return `
    <div class="${classes}" data-msg-idx="${idx}">
      <div class="chat-meta">
        <span class="chip">${escapeHtml(m.role)}</span>
        <span class="muted">${escapeHtml(fmtTime(m.timestamp))}</span>
      </div>
      ${contentBlock}
    </div>`;
}

function renderPendingChatBubbles() {
  if (!state.chatSending) return "";
  const parts = [];
  const hasStreamText =
    Boolean((state.chatStreamingText || "").trim()) &&
    !state.chatStreamGeneratingHtml;
  const hasTools = (state.chatStreamTools || []).length > 0;
  // Preparing / working until the first non-whitespace token arrives.
  // Do not show an empty "streaming…" bubble during tools-only / HTML phases.
  if (!hasStreamText) {
    let label = "Preparing answer…";
    if (state.chatStreamGeneratingHtml) label = "Generating HTML report…";
    else if (hasTools) label = "Working… using tools";
    parts.push(`
      <div class="chat-bubble role-assistant pending" aria-live="polite" aria-busy="true">
        <div class="chat-meta">
          <span class="chip">assistant</span>
        </div>
        <div class="chat-thinking">
          <span class="chat-thinking-label">${escapeHtml(label)}</span>
          <span class="typing-dots" aria-hidden="true"><i></i><i></i><i></i></span>
        </div>
      </div>`);
  }
  for (const tool of state.chatStreamTools || []) {
    const label =
      typeof tool === "string" ? tool : tool.label || tool.name || "tool";
    parts.push(`
      <div class="chat-bubble role-tool" aria-live="polite">
        <div class="chat-meta">
          <span class="chip">tool</span>
        </div>
        <div class="chat-content chat-tool-label">${escapeHtml(label)}</div>
      </div>`);
  }
  if (hasStreamText) {
    parts.push(`
      <div class="chat-bubble role-assistant streaming" aria-live="polite">
        <div class="chat-meta">
          <span class="chip">assistant</span>
          <span class="muted">streaming…</span>
        </div>
        <div class="chat-content">${escapeHtml(state.chatStreamingText)}</div>
      </div>`);
  }
  return parts.join("");
}

function wireChatHtmlPreviews(thread) {
  revokeHtmlBlobUrls();
  $$("iframe.chat-html-frame[data-html-idx]", thread).forEach((frame) => {
    const idx = Number(frame.dataset.htmlIdx);
    const msg = state.chatMessages[idx];
    if (!msg?.html) return;
    frame.style.height = "360px";
    frame.style.minHeight = "360px";
    // Prefer dedicated HTML endpoint (most reliable), blob fallback, then srcdoc.
    if (state.chatId != null && Number.isFinite(idx)) {
      frame.src = `/chats/${encodeURIComponent(state.chatId)}/messages/${idx}/html?t=${Date.now()}`;
    } else {
      try {
        const blob = new Blob([msg.html], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        _htmlBlobUrls.add(url);
        frame.src = url;
      } catch {
        frame.srcdoc = msg.html;
      }
    }
  });
  $$(".chat-expand-report", thread).forEach((btn) => {
    btn.onclick = () => {
      const msg = state.chatMessages[Number(btn.dataset.msgIdx)];
      if (msg?.html) openReport(msg.html);
    };
  });
  $$(".chat-handoff-report", thread).forEach((btn) => {
    btn.onclick = async () => {
      if (!state.chatId) return;
      try {
        const dest = await api(`/chats/${state.chatId}/handoff`, {
          method: "POST",
          body: JSON.stringify({
            message_index: Number(btn.dataset.msgIdx),
          }),
        });
        toast("Report handed off");
        const agent = state.agents.find((a) => a.id === dest.agent_id);
        if (agent) await openChat(agent, dest.id, "chat");
      } catch (err) {
        toast(err.message || "Handoff failed", "error");
      }
    };
  });
}

function formatJson(value) {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function wireDialogs() {
  $("#agent-form").addEventListener("submit", saveAgent);
  $("#source-form").addEventListener("submit", saveSource);
  $("#run-form").addEventListener("submit", submitRun);
  $("#chat-form").addEventListener("submit", sendChatMessage);
  $("#chat-new").onclick = () => createChat();
  $("#chat-rename").onclick = () => renameActiveChat();
  $("#chat-delete").onclick = () => deleteActiveChat();
  $("#chat-agent-select")?.addEventListener("change", (event) => {
    onChatAgentPickerChange(event.target.value || null);
  });
  $$('.chat-filter-chips [data-filter]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = btn.dataset.filter === "agent" ? "agent" : "all";
      if (state.chatSessionsFilter === next) return;
      state.chatSessionsFilter = next;
      renderChatPanel();
    });
  });
  $$('.chat-filter-chips [data-kind]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const next =
        btn.dataset.kind === "runs"
          ? "runs"
          : btn.dataset.kind === "chats"
            ? "chats"
            : "all";
      if (state.chatSessionsKind === next) return;
      state.chatSessionsKind = next;
      renderChatPanel();
    });
  });
  $("#chat-session-search")?.addEventListener("input", (event) => {
    state.chatSessionsQuery = event.target.value || "";
    renderChatPanel();
  });
  $("#chat-session-sort")?.addEventListener("change", (event) => {
    state.chatSessionsSort =
      event.target.value === "oldest" ? "oldest" : "newest";
    renderChatPanel();
  });
  $("#chat-attach")?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!state.chatId) {
      toast("Send a message or open a session before attaching", "error");
      return;
    }
    try {
      const body = new FormData();
      body.append("file", file);
      const res = await fetch(`/chats/${state.chatId}/attachments`, {
        method: "POST",
        body,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      await refreshChatMessagesFromServer();
      renderChatPanel();
      toast(`Attached ${file.name}`);
    } catch (err) {
      toast(err.message || "Upload failed", "error");
    }
  });
  $("#chat-input")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("#chat-form").requestSubmit();
    }
  });
  ["agent-dialog-close", "agent-dialog-cancel"].forEach((id) => {
    $(`#${id}`).onclick = () => {
      destroyPromptEditors();
      $("#agent-dialog").close();
    };
  });
  $("#agent-dialog")?.addEventListener("close", () => {
    resetDraftAvatar();
  });
  ["source-dialog-close", "source-dialog-cancel"].forEach((id) => {
    $(`#${id}`).onclick = () => closeSourceDialog();
  });
  $("#source-dialog-test")?.addEventListener("click", () => testDraftSource());
  $("#chat-cancel")?.addEventListener("click", () => cancelChatStream());
  ["run-dialog-close", "run-dialog-cancel"].forEach((id) => {
    $(`#${id}`).onclick = () => $("#run-dialog").close();
  });
  $("#report-dialog-close").onclick = () => $("#report-dialog").close();

  ["rename-dialog-close", "rename-dialog-cancel"].forEach((id) => {
    $(`#${id}`)?.addEventListener("click", () => {
      const dialog = $("#rename-dialog");
      if (dialog?.open) dialog.close("cancel");
    });
  });
  $("#rename-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const dialog = $("#rename-dialog");
    if (dialog?.open) dialog.close("confirm");
  });
  ["confirm-dialog-close", "confirm-dialog-cancel"].forEach((id) => {
    $(`#${id}`)?.addEventListener("click", () => {
      const dialog = $("#confirm-dialog");
      if (dialog?.open) dialog.close("cancel");
    });
  });
  $("#confirm-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const dialog = $("#confirm-dialog");
    if (dialog?.open) dialog.close("confirm");
  });

  $("#agent-avatar-file")?.addEventListener("change", (event) => {
    const file = event.target.files?.[0] || null;
    if (!file) return;
    if (draftAvatar.objectUrl) URL.revokeObjectURL(draftAvatar.objectUrl);
    draftAvatar.file = file;
    draftAvatar.objectUrl = URL.createObjectURL(file);
    draftAvatar.preset = null;
    draftAvatar.clearImage = false;
    renderAvatarEditor();
  });
  $("#agent-avatar-clear")?.addEventListener("click", () => {
    if (draftAvatar.objectUrl) URL.revokeObjectURL(draftAvatar.objectUrl);
    draftAvatar.file = null;
    draftAvatar.objectUrl = null;
    draftAvatar.preset = null;
    draftAvatar.clearImage = Boolean(draftAvatar.url);
    const fileInput = $("#agent-avatar-file");
    if (fileInput) fileInput.value = "";
    renderAvatarEditor();
  });
  $("#agent-form")
    ?.querySelector('input[name="name"]')
    ?.addEventListener("input", () => {
      if ($("#agent-dialog")?.open) renderAvatarEditor();
    });

  $("#agent-provider").addEventListener("change", () => {
    syncProviderUi();
    populateModelSelect($("#agent-provider").value, null);
  });
  $("#agent-api-key").addEventListener("blur", () => {
    const provider = $("#agent-provider").value;
    const selected = readModelName() || null;
    populateModelSelect(provider, selected);
  });
  $("#agent-base-url")?.addEventListener("blur", () => {
    const provider = $("#agent-provider").value;
    if (provider !== "ollama") return;
    const selected = readModelName() || null;
    populateModelSelect(provider, selected);
  });
  $("#agent-template-select")?.addEventListener("change", (event) => {
    applyAgentTemplate(event.target.value || "");
  });
  wireModelCombobox();
  $("#agent-custom-model")?.addEventListener("input", syncModelUi);

  $("#btn-manage-sources")?.addEventListener("click", () => {
    destroyPromptEditors();
    $("#agent-dialog").close();
    setView("sources");
  });
  $("#attach-sources-filter")?.addEventListener("input", (event) => {
    state.attachFilter = event.target.value || "";
    renderAttachSourcesList();
  });

  ensureMonthdayGrid();
  const scheduler = $("#cron-scheduler");
  scheduler.addEventListener("input", syncCronUiVisibility);
  scheduler.addEventListener("change", syncCronUiVisibility);
}

async function loadSources() {
  state.sources = await api("/sources");
  if (
    state.selectedSourceId &&
    !state.sources.some((s) => s.id === state.selectedSourceId)
  ) {
    state.selectedSourceId = null;
  }
  if (!state.selectedSourceId && state.sources.length) {
    state.selectedSourceId = state.sources[0].id;
  }
}

async function refreshAll() {
  await Promise.all([
    loadAgents(),
    loadSources(),
    loadAgentTemplates(),
    loadHealth(),
    loadAllSessions().catch(() => {
      state.allSessions = [];
    }),
    loadUsage().catch(() => {
      state.usage = null;
    }),
  ]);
  if (state.selectedAgentId) await refreshSelectedLogs();
  else render();
}

async function init() {
  const initialRoute = parseAdminRoute();
  applyRouteIds(initialRoute);
  if (ADMIN_VIEWS.has(initialRoute.view)) {
    state.view = initialRoute.view;
  }

  $$(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const view = btn.dataset.view;
      setView(view);
      if (view === "chat") {
        loadAllSessions()
          .then(() => render())
          .catch((e) => toast(e.message, "error"));
      }
      if (view === "system") {
        loadUsage()
          .then(() => render())
          .catch(() => render());
      }
      if (view === "activity") {
        loadActivity()
          .then(() => render())
          .catch((e) => toast(e.message, "error"));
      }
    });
  });
  window.addEventListener("popstate", () => {
    onPopState().catch((e) => toast(e.message, "error"));
  });
  $("#btn-refresh").onclick = () => refreshAll().catch((e) => toast(e.message, "error"));
  wireDialogs();
  renderTopActions();

  try {
    await refreshAll();
    await restoreFromRoute(initialRoute, { replaceUrl: true });
  } catch (e) {
    toast(e.message, "error");
    setView(initialRoute.view || "agents");
  }
  setInterval(() => loadHealth().catch(() => {}), 15000);
  loadActivity().catch(() => {});
  setInterval(() => loadActivity().catch(() => {}), 2500);
}

init();
