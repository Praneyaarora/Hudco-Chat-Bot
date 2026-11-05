/**
 * HUDCO Bot — Enterprise Conversational AI & Research Harness
 * File: ui/static/app.js
 *
 * Implements:
 * - Multi-user persistent session management & Argon2id auth UI.
 * - Collapsible sidebar with date-grouped conversation threads.
 * - Live token usage context meter & model-aware slider controls.
 * - Multi-turn conversational continuity with automatic rolling summaries.
 * - Seamless provider switching & dual dark/light themes.
 */

// Global Application State
const STATE = {
  currentUser: { authenticated: false, user: null },
  activeSessionId: null,
  activeSessionData: null,
  conversations: [],
  activeProvider: "gemini",
  contextBudget: 8192,
  currentUsedTokens: 0,
  lastTelemetry: null,
  modelSpecs: {},
  uiMode: "chat",
  theme: "dark",
  sidebarCollapsed: false,
  authTab: "login",
  searchQuery: "",
  isSubmitting: false,
};

// ============================================================================
// Initialization
// ============================================================================
document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  await checkAuthStatus();
  await loadServerConfig();
  await loadConversations();
  await fetchReports();
  await fetchStatus();
});

function initTheme() {
  const savedTheme = localStorage.getItem("hudco_theme") || "dark";
  STATE.theme = savedTheme;
  document.body.className = savedTheme === "light" ? "light-theme" : "dark-theme";
  document.body.setAttribute("data-theme", savedTheme);
}

function toggleTheme() {
  STATE.theme = STATE.theme === "dark" ? "light" : "dark";
  document.body.className = STATE.theme === "light" ? "light-theme" : "dark-theme";
  document.body.setAttribute("data-theme", STATE.theme);
  localStorage.setItem("hudco_theme", STATE.theme);
}

// ============================================================================
// Authentication & User Profile
// ============================================================================
async function checkAuthStatus() {
  try {
    const res = await fetch("/api/auth/me");
    const data = await res.json();
    STATE.currentUser = data;
    renderUserBadge();
  } catch (err) {
    console.warn("Could not check auth status:", err);
  }
}

function renderUserBadge() {
  const badge = document.getElementById("userProfileBadge");
  const avatar = document.getElementById("userAvatarIcon");
  const nameEl = document.getElementById("userDisplayName");
  const roleEl = document.getElementById("userDisplayRole");
  const btnAction = document.getElementById("btnUserAuthAction");

  if (!badge) return;

  if (STATE.currentUser.authenticated && STATE.currentUser.user) {
    const u = STATE.currentUser.user;
    const initial = (u.username || u.name || "U")[0].toUpperCase();
    avatar.textContent = initial;
    avatar.className = "user-avatar-initials";
    nameEl.textContent = u.username || u.name || u.email;
    roleEl.textContent = u.role ? u.role.toUpperCase() : "Analyst";
    btnAction.textContent = "Sign Out";
  } else {
    avatar.textContent = "G";
    avatar.className = "user-avatar-initials user-avatar-guest";
    nameEl.textContent = "Guest User";
    roleEl.textContent = "Local Session";
    btnAction.textContent = "Sign In";
  }
}

function handleAuthActionClick() {
  if (STATE.currentUser.authenticated) {
    handleSignOut();
  } else {
    openAuthModal("login");
  }
}

function openAuthModal(mode = "login") {
  STATE.authTab = mode;
  const modal = document.getElementById("authModalBackdrop");
  if (modal) modal.style.display = "flex";
  switchAuthTab(mode);
  clearAuthError();
}

function closeAuthModal() {
  const modal = document.getElementById("authModalBackdrop");
  if (modal) modal.style.display = "none";
  clearAuthError();
}

function switchAuthTab(mode) {
  STATE.authTab = mode;
  const tabIn = document.getElementById("tabSignIn");
  const tabReg = document.getElementById("tabRegister");
  const groupName = document.getElementById("groupRegisterName");
  const btnSubmit = document.getElementById("btnAuthSubmit");
  const title = document.getElementById("authModalTitle");

  if (mode === "register") {
    tabIn.classList.remove("active");
    tabReg.classList.add("active");
    groupName.style.display = "flex";
    btnSubmit.textContent = "Create Account";
    title.textContent = "Create HUDCO Account";
  } else {
    tabIn.classList.add("active");
    tabReg.classList.remove("active");
    groupName.style.display = "none";
    btnSubmit.textContent = "Sign In";
    title.textContent = "Sign In to HUDCO Bot";
  }
  clearAuthError();
}

function setAuthError(msg) {
  const errBox = document.getElementById("authErrorMsg");
  if (errBox) {
    errBox.textContent = msg;
    errBox.style.display = "block";
  }
}

function clearAuthError() {
  const errBox = document.getElementById("authErrorMsg");
  if (errBox) {
    errBox.textContent = "";
    errBox.style.display = "none";
  }
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  clearAuthError();

  const email = document.getElementById("authInputEmail").value.trim();
  const password = document.getElementById("authInputPassword").value;
  const name = document.getElementById("authInputName").value.trim();

  const endpoint = STATE.authTab === "register" ? "/api/auth/register" : "/api/auth/login";
  const payload = STATE.authTab === "register" ? { name, email, password } : { email, password };

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (!res.ok) {
      setAuthError(data.error || "Authentication failed.");
      return;
    }

    closeAuthModal();
    await checkAuthStatus();
    await loadConversations();
  } catch (err) {
    setAuthError(`Network error: ${err.message}`);
  }
}

async function handleSignOut() {
  if (!confirm("Are you sure you want to sign out?")) return;
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    STATE.currentUser = { authenticated: false, user: null };
    renderUserBadge();
    await loadConversations();
  } catch (err) {
    console.error("Sign out error:", err);
  }
}

// ============================================================================
// Server Configuration & Provider Setup
// ============================================================================
async function loadServerConfig() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    STATE.activeProvider = data.provider || "gemini";
    STATE.contextBudget = data.context_budget || 8192;
    STATE.modelSpecs = data.model_specs || {};

    const provSelect = document.getElementById("providerSelect");
    if (provSelect) provSelect.value = STATE.activeProvider;

    const labels = {
      gemini: "Google Gemini",
      local_qwen: "Local LLM",
      claude: "Claude 3.5 Sonnet",
      openai: "OpenAI GPT-4o",
    };

    const provLabel = document.getElementById("providerLabel");
    if (provLabel) {
      provLabel.textContent = labels[STATE.activeProvider] || "LLM Engine";
    }

    const provBadge = document.getElementById("activeProviderBadge");
    if (provBadge) {
      provBadge.textContent = labels[STATE.activeProvider] || "Google Gemini";
    }

    updateSliderSpecs();
  } catch (err) {
    console.warn("Could not load server config:", err);
  }
}

function updateSliderSpecs() {
  const spec = STATE.modelSpecs[STATE.activeProvider] || {
    min_budget: 1024,
    max_budget: 32768,
    warning_threshold: 12288,
    warning_text: "High context usage increases memory and latency.",
  };

  const slider = document.getElementById("contextBudgetSlider");
  const badge = document.getElementById("sliderValBadge");
  const rangeHint = document.getElementById("budgetRangeHint");

  if (slider) {
    slider.min = spec.min_budget || 1024;
    slider.max = spec.max_budget || 32768;
    slider.value = STATE.contextBudget;
  }
  if (badge) badge.textContent = `${Number(STATE.contextBudget).toLocaleString()} tokens`;
  if (rangeHint) {
    rangeHint.textContent = `Min: ${Number(spec.min_budget).toLocaleString()} · Max: ${Number(spec.max_budget).toLocaleString()}`;
  }

  checkSliderWarning(STATE.contextBudget, spec);
}

function handleContextSliderInput(val) {
  const newBudget = parseInt(val, 10);
  const badge = document.getElementById("sliderValBadge");
  if (badge) badge.textContent = `${Number(newBudget).toLocaleString()} tokens`;
  const spec = STATE.modelSpecs[STATE.activeProvider];
  if (spec) checkSliderWarning(newBudget, spec);

  // Recalculate context meter immediately upon slider movement without resetting used tokens!
  const used = STATE.currentUsedTokens || 0;
  const pct = newBudget > 0 ? Number(((used / newBudget) * 100).toFixed(1)) : 0;

  const meterTokenCount = document.getElementById("meterTokenCount");
  const meterPercentage = document.getElementById("meterPercentage");
  const meterBarFill = document.getElementById("meterBarFill");
  const tooltipBudgetLabel = document.getElementById("tooltipBudgetLabel");

  if (meterTokenCount) meterTokenCount.textContent = `${used.toLocaleString()} / ${newBudget.toLocaleString()}`;
  if (meterPercentage) {
    meterPercentage.textContent = `${pct}%`;
    meterPercentage.className = pct >= 90 ? "meter-percent rose" : (pct >= 75 ? "meter-percent amber" : "meter-percent");
  }
  if (meterBarFill) {
    meterBarFill.style.width = `${Math.min(100, pct)}%`;
    meterBarFill.className = pct >= 90 ? "meter-bar-fill rose" : (pct >= 75 ? "meter-bar-fill amber" : "meter-bar-fill");
  }
  if (tooltipBudgetLabel) tooltipBudgetLabel.textContent = `${newBudget.toLocaleString()} max tokens`;
}

function checkSliderWarning(val, spec) {
  const banner = document.getElementById("sliderWarningBanner");
  const warnText = document.getElementById("sliderWarningText");
  if (!banner) return;

  if (Number(val) >= (spec.warning_threshold || 12288)) {
    banner.style.display = "flex";
    if (warnText) warnText.textContent = spec.warning_text;
  } else {
    banner.style.display = "none";
  }
}

async function handleContextSliderChange(val) {
  STATE.contextBudget = parseInt(val, 10);
  handleContextSliderInput(val);
  try {
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ context_budget: STATE.contextBudget }),
    });
  } catch (err) {
    console.error("Could not save context budget:", err);
  }
}

async function handleProviderChange(provider) {
  STATE.activeProvider = provider;
  try {
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    });
    await loadServerConfig();
  } catch (err) {
    console.error("Could not change provider:", err);
  }
}

async function saveApiKeys() {
  const tavily = document.getElementById("keyTavily").value.trim();
  const gemini = document.getElementById("keyGemini").value.trim();
  const claude = document.getElementById("keyClaude").value.trim();
  const openai = document.getElementById("keyOpenAI").value.trim();

  const api_keys = {};
  if (tavily) api_keys.tavily = tavily;
  if (gemini) api_keys.gemini = gemini;
  if (claude) api_keys.claude = claude;
  if (openai) api_keys.openai = openai;

  try {
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_keys }),
    });
    alert("API keys saved securely to server.");
  } catch (err) {
    alert(`Failed to save keys: ${err.message}`);
  }
}

// ============================================================================
// Collapsible Sidebar & Conversation Threads
// ============================================================================
function toggleSidebar() {
  const sidebar = document.getElementById("sidebarContainer");
  if (!sidebar) return;
  STATE.sidebarCollapsed = !STATE.sidebarCollapsed;
  if (STATE.sidebarCollapsed) {
    sidebar.classList.add("collapsed");
  } else {
    sidebar.classList.remove("collapsed");
  }
}

async function loadConversations() {
  try {
    const res = await fetch("/api/chats");
    const data = await res.json();
    STATE.conversations = data.conversations || [];
    renderConversationsList();

    // Auto-select latest conversation or prepare fresh session
    if (STATE.conversations.length > 0 && !STATE.activeSessionId) {
      await selectConversation(STATE.conversations[0].session_id);
    } else if (STATE.conversations.length === 0) {
      STATE.activeSessionId = null;
      STATE.activeSessionData = null;
      renderFreshChatWorkspace();
    }
  } catch (err) {
    console.error("Could not load conversations:", err);
  }
}

function renderConversationsList() {
  const container = document.getElementById("sidebarChatList");
  if (!container) return;

  const filterQuery = (STATE.searchQuery || "").toLowerCase();
  const filtered = STATE.conversations.filter(c =>
    (c.title || "").toLowerCase().includes(filterQuery)
  );

  if (filtered.length === 0) {
    container.innerHTML = `
      <div style="padding: 24px 12px; text-align: center; color: var(--text-muted); font-size: 0.78rem;">
        ${filterQuery ? "No matching conversations found." : "No saved conversations yet. Click New Chat to begin!"}
      </div>
    `;
    return;
  }

  // Group by Today, Yesterday, and Older
  const now = Date.now();
  const oneDay = 24 * 60 * 60 * 1000;
  const todayItems = [];
  const yesterdayItems = [];
  const olderItems = [];

  filtered.forEach(conv => {
    const age = now - (conv.updated_at * 1000);
    if (age < oneDay) {
      todayItems.push(conv);
    } else if (age < 2 * oneDay) {
      yesterdayItems.push(conv);
    } else {
      olderItems.push(conv);
    }
  });

  let html = "";
  if (todayItems.length > 0) {
    html += renderChatGroup("Today", todayItems);
  }
  if (yesterdayItems.length > 0) {
    html += renderChatGroup("Yesterday", yesterdayItems);
  }
  if (olderItems.length > 0) {
    html += renderChatGroup("Previous Conversations", olderItems);
  }

  container.innerHTML = html;
}

function renderChatGroup(title, items) {
  const itemsHtml = items.map(c => `
    <div class="chat-item ${c.session_id === STATE.activeSessionId ? "active" : ""}" onclick="selectConversation('${c.session_id}')">
      <span class="chat-item-title" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</span>
      <div class="chat-item-actions" onclick="event.stopPropagation()">
        <button type="button" class="chat-action-btn" title="Rename conversation" onclick="promptRenameChat('${c.session_id}', '${escapeHtml(c.title)}')">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
        </button>
        <button type="button" class="chat-action-btn" title="Export conversation JSON" onclick="exportChat('${c.session_id}')">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
        </button>
        <button type="button" class="chat-action-btn" title="Delete conversation" onclick="deleteChat('${c.session_id}')">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
        </button>
      </div>
    </div>
  `).join("");

  return `
    <div>
      <div class="chat-group-title">${title}</div>
      <div class="chat-group-items">${itemsHtml}</div>
    </div>
  `;
}

function handleSearchChats(query) {
  STATE.searchQuery = query;
  renderConversationsList();
}

async function createNewChatSession() {
  try {
    const res = await fetch("/api/chats", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "New Conversation" }),
    });
    const data = await res.json();
    if (data.session) {
      STATE.activeSessionId = data.session.session_id;
      STATE.activeSessionData = data.session;
      await loadConversations();
      renderFreshChatWorkspace();
    }
  } catch (err) {
    console.error("Could not create new session:", err);
  }
}

async function selectConversation(sessionId) {
  try {
    STATE.activeSessionId = sessionId;
    renderConversationsList();

    const res = await fetch(`/api/chats/${sessionId}`);
    if (!res.ok) {
      renderFreshChatWorkspace();
      return;
    }
    const data = await res.json();
    STATE.activeSessionData = data.session;
    renderMessagesFromSession(data.session);

    if (data.context_telemetry) {
      updateContextMeter(data.context_telemetry);
    } else {
      let estTokens = 0;
      (data.session.messages || []).forEach(m => {
        estTokens += Math.max(1, Math.round((m.content || "").length / 3.7));
      });
      updateContextMeter({
        used_tokens: estTokens,
        max_budget: STATE.contextBudget,
        percentage: Number(((estTokens / STATE.contextBudget) * 100).toFixed(1)),
        system_tokens: 250,
        summary_tokens: data.session.rolling_summary ? Math.round(data.session.rolling_summary.length / 3.7) : 0,
        history_tokens: estTokens,
        evidence_tokens: 0,
        query_tokens: 0,
        has_rolling_summary: Boolean(data.session.rolling_summary),
        active_turns_count: (data.session.messages || []).length,
      });
    }
  } catch (err) {
    console.error("Error selecting conversation:", err);
  }
}

async function promptRenameChat(sessionId, currentTitle) {
  const newTitle = prompt("Enter new title for this conversation:", currentTitle);
  if (!newTitle || newTitle.trim() === "" || newTitle.trim() === currentTitle) return;

  try {
    await fetch(`/api/chats/${sessionId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: newTitle.trim() }),
    });
    await loadConversations();
  } catch (err) {
    alert(`Rename failed: ${err.message}`);
  }
}

async function deleteChat(sessionId) {
  if (!confirm("Are you sure you want to delete this conversation? This action cannot be undone.")) return;

  try {
    await fetch(`/api/chats/${sessionId}`, { method: "DELETE" });
    if (STATE.activeSessionId === sessionId) {
      STATE.activeSessionId = null;
      STATE.activeSessionData = null;
    }
    await loadConversations();
  } catch (err) {
    alert(`Delete failed: ${err.message}`);
  }
}

async function exportChat(sessionId) {
  try {
    const res = await fetch(`/api/chats/${sessionId}/export`);
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `hudco_chat_${sessionId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert(`Export failed: ${err.message}`);
  }
}

function triggerImportChat() {
  const input = document.getElementById("importFileInput");
  if (input) input.click();
}

async function handleFileImport(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;

  try {
    const text = await file.text();
    const data = JSON.parse(text);

    const res = await fetch("/api/chats/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const result = await res.json();

    if (!res.ok) {
      alert(`Import failed: ${result.error || "Invalid file format."}`);
      return;
    }

    e.target.value = "";
    await loadConversations();
    if (result.session) {
      await selectConversation(result.session.session_id);
    }
  } catch (err) {
    alert(`Could not parse JSON file: ${err.message}`);
  }
}

// ============================================================================
// Real-Time Context Usage Meter
// ============================================================================
function updateContextMeter(telemetry) {
  if (!telemetry) return;

  STATE.lastTelemetry = Object.assign({}, telemetry);
  if (telemetry.used_tokens !== undefined) {
    STATE.currentUsedTokens = Number(telemetry.used_tokens || 0);
  }

  const meterTokenCount = document.getElementById("meterTokenCount");
  const meterPercentage = document.getElementById("meterPercentage");
  const meterBarFill = document.getElementById("meterBarFill");
  const tooltipBudgetLabel = document.getElementById("tooltipBudgetLabel");

  const ttSysTokens = document.getElementById("ttSysTokens");
  const ttSummaryTokens = document.getElementById("ttSummaryTokens");
  const ttHistoryTokens = document.getElementById("ttHistoryTokens");
  const ttEvidenceTokens = document.getElementById("ttEvidenceTokens");
  const ttQueryTokens = document.getElementById("ttQueryTokens");
  const ttWarningNote = document.getElementById("ttWarningNote");

  const used = STATE.currentUsedTokens;
  const maxB = Number(telemetry.max_budget || STATE.contextBudget || 8192);
  const pct = Number(telemetry.percentage !== undefined ? telemetry.percentage : ((used / maxB) * 100).toFixed(1));

  if (meterTokenCount) meterTokenCount.textContent = `${used.toLocaleString()} / ${maxB.toLocaleString()}`;
  if (meterPercentage) {
    meterPercentage.textContent = `${pct}%`;
    meterPercentage.className = pct >= 90 ? "meter-percent rose" : (pct >= 75 ? "meter-percent amber" : "meter-percent");
  }
  if (meterBarFill) {
    meterBarFill.style.width = `${Math.min(100, pct)}%`;
    meterBarFill.className = pct >= 90 ? "meter-bar-fill rose" : (pct >= 75 ? "meter-bar-fill amber" : "meter-bar-fill");
  }

  if (tooltipBudgetLabel) tooltipBudgetLabel.textContent = `${maxB.toLocaleString()} max tokens`;
  if (ttSysTokens) ttSysTokens.textContent = `${telemetry.system_tokens || 0} tokens`;
  if (ttSummaryTokens) {
    ttSummaryTokens.textContent = `${telemetry.summary_tokens || 0} tokens (${telemetry.has_rolling_summary ? "Active Summary" : "None"})`;
  }
  if (ttHistoryTokens) {
    ttHistoryTokens.textContent = `${telemetry.history_tokens || 0} tokens (${telemetry.active_turns_count || 0} turns)`;
  }
  if (ttEvidenceTokens) ttEvidenceTokens.textContent = `${telemetry.evidence_tokens || 0} tokens`;
  if (ttQueryTokens) ttQueryTokens.textContent = `${telemetry.query_tokens || 0} tokens`;

  if (ttWarningNote) {
    if (telemetry.warning_message) {
      ttWarningNote.innerHTML = `<strong style="color: #fbbf24;">⚠️ ${escapeHtml(telemetry.warning_message)}</strong>`;
    } else {
      ttWarningNote.textContent = "Token sliding window preserves recent turns and condenses older turns into factual rolling summaries.";
    }
  }
}

// ============================================================================
// Chat Rendering & Interaction
// ============================================================================
function renderFreshChatWorkspace() {
  STATE.currentUsedTokens = 0;
  const container = document.getElementById("chatMessagesScroll");
  if (!container) return;

  container.innerHTML = `
    <div class="message-row bot">
      <div class="msg-avatar">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
          <polyline points="9 22 9 12 15 12 15 22"></polyline>
        </svg>
      </div>
      <div class="msg-content-wrap">
        <div class="msg-meta">
          <span class="msg-sender">HUDCO Bot</span>
          <span>Just now</span>
        </div>
        <div class="msg-bubble">
          <p>Hello! I am <strong>HUDCO Bot</strong>, your AI assistant for Housing and Urban Development Corporation Limited.</p>
          <p>You can ask me questions about:</p>
          <ul>
            <li><strong>Annual Reports & Financial Results</strong> (Loan sanctions, Net Worth, Profit After Tax FY 2014-24)</li>
            <li><strong>Corporate Information & Head Office</strong> (Registered address, contact numbers)</li>
            <li><strong>Recruitment & Careers</strong> (How to apply on official portal)</li>
            <li><strong>Urban Infrastructure Schemes</strong> (UiWIN platform, smart city financing)</li>
          </ul>
          <div class="suggested-chips-wrap">
            <span class="suggested-title">Suggested:</span>
            <button type="button" class="prompt-chip" onclick="sendSuggestedQuery('Where is HUDCO head office located?')">🏢 Where is HUDCO Head Office?</button>
            <button type="button" class="prompt-chip" onclick="sendSuggestedQuery('How to apply for jobs and careers at HUDCO?')">💼 How to apply for jobs at HUDCO?</button>
            <button type="button" class="prompt-chip" onclick="sendSuggestedQuery('What is the UiWIN platform launched by HUDCO?')">🌐 What is the UiWIN platform?</button>
            <button type="button" class="prompt-chip" onclick="sendSuggestedQuery('What was HUDCO\\'s net profit and net worth in FY 2023-24?')">📈 FY 2023-24 Net Profit & Net Worth</button>
          </div>
        </div>
      </div>
    </div>
  `;

  updateContextMeter({
    used_tokens: 0,
    max_budget: STATE.contextBudget,
    percentage: 0,
    system_tokens: 0,
    summary_tokens: 0,
    history_tokens: 0,
    evidence_tokens: 0,
    query_tokens: 0,
  });
}

function renderMessagesFromSession(session) {
  const container = document.getElementById("chatMessagesScroll");
  if (!container) return;

  if (!session.messages || session.messages.length === 0) {
    renderFreshChatWorkspace();
    return;
  }

  let html = "";
  session.messages.forEach(msg => {
    const isBot = msg.role === "assistant";
    const hasEvidence = isBot && Array.isArray(msg.evidence_payload) && msg.evidence_payload.length > 0;
    const isWeb = hasEvidence && Boolean(msg.evidence_payload[0] && msg.evidence_payload[0].is_web);

    let actionsRowHtml = "";
    if (isBot) {
      const escapedJson = hasEvidence ? JSON.stringify(msg.evidence_payload).replace(/"/g, '&quot;') : "[]";
      actionsRowHtml = `
        <div class="msg-actions-row">
          <button type="button" class="action-pill-btn copy-mini-btn" onclick="copyChatMessage(this, \`${escapeJsString(msg.content)}\`)" title="Copy answer">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
            <span>Copy</span>
          </button>
          ${hasEvidence ? `
            <button type="button" class="action-pill-btn sources-pill-btn ${isWeb ? "web" : "chunks"}" onclick="openHistoricalSourcesModal(${escapedJson}, ${isWeb})" title="Inspect verified sources">
              ${isWeb ? `🌐 ${msg.evidence_payload.length} Web Sources` : `📚 ${msg.evidence_payload.length} Verified Chunks`}
            </button>
            <button type="button" class="action-pill-btn inspect-pill-btn" onclick="openHistoricalSourcesModal(${escapedJson}, ${isWeb}); openInDeveloperMode();" title="Inspect in Developer Mode">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
              <span>Inspect ⚙️</span>
            </button>
          ` : ""}
        </div>
      `;
    }

    html += `
      <div class="message-row ${isBot ? "bot" : "user"}">
        <div class="msg-avatar">
          ${isBot ? `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
              <polyline points="9 22 9 12 15 12 15 22"></polyline>
            </svg>
          ` : `
            <span>U</span>
          `}
        </div>
        <div class="msg-content-wrap">
          <div class="msg-meta">
            <span class="msg-sender">${isBot ? "HUDCO Bot" : "You"}</span>
            <span>${formatTime(msg.timestamp)}</span>
          </div>
          <div class="msg-bubble">
            ${formatMessageContent(msg.content)}
          </div>
          ${actionsRowHtml}
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
  container.scrollTop = container.scrollHeight;
}

function sendSuggestedQuery(text) {
  const input = document.getElementById("chatInputText");
  if (input) {
    input.value = text;
    handleChatSubmit(new Event("submit"));
  }
}

function autoResizeTextarea(el) {
  el.style.height = "auto";
  el.style.height = `${Math.min(140, Math.max(24, el.scrollHeight))}px`;
}

function handleTextareaKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleChatSubmit(e);
  }
}

async function handleChatSubmit(e) {
  if (e) e.preventDefault();
  if (STATE.isSubmitting) return;

  const input = document.getElementById("chatInputText");
  const sendBtn = document.getElementById("chatSendBtn");
  const query = (input.value || "").trim();
  if (!query) return;

  STATE.isSubmitting = true;
  input.value = "";
  input.style.height = "auto";
  if (sendBtn) sendBtn.disabled = true;

  // Append user bubble to DOM immediately
  appendMessageToDOM("user", query, Date.now() / 1000);

  // Append thinking placeholder for Bot
  const botMsgPlaceholderId = `bot_turn_${Date.now()}`;
  appendThinkingPlaceholder(botMsgPlaceholderId);

  try {
    const payload = {
      query,
      session_id: STATE.activeSessionId,
      provider: STATE.activeProvider,
      context_budget: STATE.contextBudget,
    };

    const res = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (!res.ok) {
      replacePlaceholderWithContent(
        botMsgPlaceholderId,
        `Error: ${data.error || "Server processing failed."}`
      );
      return;
    }

    if (data.session_id && data.session_id !== STATE.activeSessionId) {
      STATE.activeSessionId = data.session_id;
      await loadConversations();
    }

    const answerObj = data.answer || {};
    const finalCleanAnswer = answerObj.clean_answer || answerObj.answer || "No response received.";
    const isWeb = Boolean(data.used_web_search);
    lastQueryData = data;
    lastEvidenceResults = data.results || [];
    updateDevViewWithData(data);
    replacePlaceholderWithContent(botMsgPlaceholderId, finalCleanAnswer, data.results, isWeb);

    // Update Live Context Meter Telemetry
    if (data.context_telemetry) {
      updateContextMeter(data.context_telemetry);
    }
  } catch (err) {
    replacePlaceholderWithContent(
      botMsgPlaceholderId,
      `Connection error: Unable to contact HUDCO server (${err.message}).`
    );
  } finally {
    STATE.isSubmitting = false;
    if (sendBtn) sendBtn.disabled = false;
    input.focus();
  }
}

function appendMessageToDOM(role, content, timestamp) {
  const container = document.getElementById("chatMessagesScroll");
  if (!container) return;

  const isBot = role === "assistant" || role === "bot";
  const row = document.createElement("div");
  row.className = `message-row ${isBot ? "bot" : "user"}`;
  row.innerHTML = `
    <div class="msg-avatar">
      ${isBot ? `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
          <polyline points="9 22 9 12 15 12 15 22"></polyline>
        </svg>
      ` : `
        <span>U</span>
      `}
    </div>
    <div class="msg-content-wrap">
      <div class="msg-meta">
        <span class="msg-sender">${isBot ? "HUDCO Bot" : "You"}</span>
        <span>${formatTime(timestamp)}</span>
      </div>
      <div class="msg-bubble">
        ${formatMessageContent(content)}
      </div>
    </div>
  `;

  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
}

function appendThinkingPlaceholder(id) {
  const container = document.getElementById("chatMessagesScroll");
  if (!container) return;

  const row = document.createElement("div");
  row.className = "message-row bot";
  row.id = id;
  row.innerHTML = `
    <div class="msg-avatar">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
        <polyline points="9 22 9 12 15 12 15 22"></polyline>
      </svg>
    </div>
    <div class="msg-content-wrap">
      <div class="msg-meta">
        <span class="msg-sender">HUDCO Bot</span>
        <span>Thinking...</span>
      </div>
      <div class="msg-bubble" style="opacity: 0.8; font-style: italic;">
        Consulting HUDCO reports and verified records...
      </div>
    </div>
  `;

  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
}

function replacePlaceholderWithContent(id, content, results = null, isWeb = false) {
  const row = document.getElementById(id);
  if (!row) return;

  const bubble = row.querySelector(".msg-bubble");
  const contentWrap = row.querySelector(".msg-content-wrap");
  const timeMeta = row.querySelector(".msg-meta span:last-child");
  if (bubble) {
    bubble.style.fontStyle = "normal";
    bubble.style.opacity = "1";
    bubble.innerHTML = formatMessageContent(content);
  }
  if (timeMeta) {
    timeMeta.textContent = "Just now";
  }

  // Remove any previous actions row in this bubble wrap
  if (contentWrap) {
    const prevActions = contentWrap.querySelector(".msg-actions-row");
    if (prevActions) prevActions.remove();

    const actionsRow = document.createElement("div");
    actionsRow.className = "msg-actions-row";

    // 1. Copy button
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "action-pill-btn copy-mini-btn";
    copyBtn.title = "Copy answer to clipboard";
    copyBtn.innerHTML = `
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
      <span>Copy</span>
    `;
    copyBtn.onclick = function() { copyChatMessage(this, content); };
    actionsRow.appendChild(copyBtn);

    // 2. Sources button (if results present)
    if (results && results.length > 0) {
      const count = results.length;
      const sourcesBtn = document.createElement("button");
      sourcesBtn.type = "button";
      sourcesBtn.className = `action-pill-btn sources-pill-btn ${isWeb ? "web" : "chunks"}`;
      sourcesBtn.title = isWeb ? "Inspect verified official web sources" : "Inspect verified annual report chunks";
      sourcesBtn.innerHTML = isWeb ? `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
        <span>🌐 ${count} Web Sources</span>
      ` : `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
        <span>📚 ${count} Verified Chunks</span>
      `;
      sourcesBtn.onclick = function() { openSourcesModal(); };
      actionsRow.appendChild(sourcesBtn);

      // 3. Inspect in Developer Mode button
      const inspectBtn = document.createElement("button");
      inspectBtn.type = "button";
      inspectBtn.className = "action-pill-btn inspect-pill-btn";
      inspectBtn.title = "Inspect full telemetry, candidate chunks, and parameters in Developer Mode";
      inspectBtn.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
        <span>Inspect ⚙️</span>
      `;
      inspectBtn.onclick = function() { openInDeveloperMode(); };
      actionsRow.appendChild(inspectBtn);
    }

    contentWrap.appendChild(actionsRow);
  }

  const container = document.getElementById("chatMessagesScroll");
  if (container) container.scrollTop = container.scrollHeight;
}

// ============================================================================
// Mode Switcher (Chat Mode vs Developer Mode)
// ============================================================================
function switchUIMode(mode) {
  STATE.uiMode = mode;
  const btnChat = document.getElementById("btnModeChat");
  const btnDev = document.getElementById("btnModeDev");
  const chatView = document.getElementById("chatModeView");
  const devView = document.getElementById("devModeView");

  if (mode === "dev") {
    btnChat.classList.remove("active");
    btnDev.classList.add("active");
    chatView.style.display = "none";
    devView.style.display = "flex";

    // Synchronize latest chat query and evidence into Developer section!
    if (lastQueryData) {
      updateDevViewWithData(lastQueryData);
      const devInput = document.getElementById("devQueryInput");
      if (devInput && lastQueryData.query) {
        devInput.value = lastQueryData.query;
      }
    }
  } else {
    btnChat.classList.add("active");
    btnDev.classList.remove("active");
    chatView.style.display = "flex";
    devView.style.display = "none";
  }
}

// ============================================================================
// Formatting Helpers
// ============================================================================
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatMessageContent(text) {
  if (!text) return "";
  let cleaned = text;

  // 1. Strip raw internal evidence markers with arbitrary descriptive text inside brackets:
  // e.g. [Citation: Evidence Item – Headquarters: New Delhi, Delhi, India]
  // e.g. [Citation: Evidence Item – Key people: Sanjay Kulshrestha (Chairman & MD)]
  cleaned = cleaned.replace(/\[\s*(?:Citation:\s*|Evidence\s*(?:Item\s*)?|Source:\s*|Ref:\s*)[^\]\n]*\]/gi, "");

  // 2. Strip bracketed numeric citations: [1], [2], [1, 2, 3]
  cleaned = cleaned.replace(/\[\s*\[?\s*\d+(?:\s*[,–-]\s*\d+)*\s*\]?\s*\]/g, "");

  // 3. Strip standalone evidence item header lines if leaked:
  cleaned = cleaned.replace(/---+\s*(?:START|END)?\s*EVIDENCE\s*ITEM\s*\[?\d*\]?[^-\n]*---+/gi, "");
  cleaned = cleaned.replace(/^(?:Chunk ID|Fiscal Year|Location|Section|Document):\s*.*$/gim, "");

  // 4. Strip prompt echo & intro phrases and dangling Evidence Item references:
  cleaned = cleaned.replace(/^\*?\*?(?:Evidence|Answer|Response):\*?\*?\s*/gi, "");
  cleaned = cleaned.replace(/^Based on (?:the )?(?:provided )?(?:evidence|annual reports?|documents?|sources?)[,\s]*/gi, "");
  cleaned = cleaned.replace(/^[,\s]*(?:and\s+)?(?:in\s+|as\s+per\s+|according\s+to\s+)?Evidence\s*(?:Item\s*)?(?:\[?\d*\]?)?.*$/gim, "");
  cleaned = cleaned.replace(/(?:,\s*)?(?:and\s+)?(?:in\s+|as\s+per\s+|according\s+to\s+)?Evidence\s*(?:Item\s*)?(?:\[?\d*\]?)?[:\s,]*/gi, "");

  // 5. Strip trailing citation/sources blocks:
  cleaned = cleaned.replace(/\n*\s*(?:Citations?|Sources?|References?):\s*(?:\[?[^\]\n]+\]?|\d+|https?:\/\/\S+)(?:[,\s]+(?:\[?[^\]\n]+\]?|\d+|https?:\/\/\S+))*\s*$/gi, "");

  // 6. Strip internal note / explanation leaks:
  cleaned = cleaned.replace(/\n+\s*(?:\*\*)?(?:Note|Explanation|Internal Note|Meta-Note|Context)(?:\*\*)?\s*:[\s\S]*$/gi, "");

  // 7. Clean up dangling commas and messy punctuation:
  cleaned = cleaned.replace(/([.!?])\s*[,;]+/g, "$1");
  cleaned = cleaned.replace(/(?:\s*,\s*)+(?=[.!?])/g, "");
  cleaned = cleaned.replace(/(?:\s*,\s*)+$/gm, ".");
  cleaned = cleaned.replace(/\s+([.,;:!?])/g, "$1");
  cleaned = cleaned.replace(/\.{2,}(?!\.)/g, ".");
  cleaned = cleaned.replace(/[ \t]{2,}/g, " ");

  // Format paragraphs and bold text
  const paragraphs = cleaned.split("\n\n").filter(p => p.trim().length > 0);
  return paragraphs.map(p => {
    let formatted = escapeHtml(p.trim());
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    return `<p>${formatted}</p>`;
  }).join("");
}

function formatTime(timestamp) {
  if (!timestamp) return "Just now";
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}



// ============================================================================
// DEVELOPER WORKSPACE & DIAGNOSTIC RETRIEVAL CONTROLS
// ============================================================================
let lastQueryData = null;
let lastEvidenceResults = [];
let globalReports = [];

async function fetchReports() {
  try {
    const res = await fetch("/api/reports");
    if (!res.ok) throw new Error("Failed to load reports");
    const data = await res.json();
    globalReports = data.reports || [];

    // 1. Populate Report Scope Filter Dropdown
    const isEligible = (r) => Boolean(r.is_eligible ?? (r.is_selectable ?? (r.status === "INDEXED")));
    const getYear = (r) => {
      if (r.fiscal_year) return r.fiscal_year;
      const m = (r.document_id || "").match(/ar(\d{2})/);
      if (m) {
        const yy = parseInt(m[1], 10);
        return `FY 20${yy-1}-${yy}`;
      }
      return "Annual Report";
    };

    const select = document.getElementById("reportFilterSelect");
    if (select) {
      const eligibleCount = globalReports.filter(isEligible).length;
      select.innerHTML = `<option value="ALL">All ${eligibleCount > 0 ? eligibleCount : ''} Verified Reports (Cross-Year Ingestion)</option>`;
      globalReports.forEach((r) => {
        const opt = document.createElement("option");
        opt.value = r.document_id;
        const yr = getYear(r);
        if (!isEligible(r)) {
          opt.disabled = true;
          opt.textContent = `${r.document_id}.pdf (${yr}) — [Quarantined: Missing OCR]`;
        } else {
          opt.textContent = `${r.document_id}.pdf (${yr}) · ${r.total_pages || 0} pages`;
        }
        select.appendChild(opt);
      });
    }

    // 2. Populate Audited Reports Inventory Table
    const tbody = document.getElementById("reportsTableBody");
    if (tbody && globalReports.length > 0) {
      tbody.innerHTML = globalReports.map(r => {
        const eligible = isEligible(r);
        const yr = getYear(r);
        return `
          <tr style="border-bottom: 1px solid var(--border-light);">
            <td style="padding: 10px 12px; font-weight: 600; color: var(--text-main);">${escapeHtml(yr)}</td>
            <td style="padding: 10px 12px; font-family: var(--font-mono); font-size: 0.8rem; color: var(--accent-cyan);">${escapeHtml(r.document_id)}</td>
            <td style="padding: 10px 12px; color: var(--text-secondary);">${escapeHtml(r.filename || r.document_id + '.pdf')}</td>
            <td style="padding: 10px 12px; color: var(--text-muted);">${r.total_pages || (eligible ? 'Verified' : '0')}</td>
            <td style="padding: 10px 12px;">
              <span style="display: inline-block; font-size: 0.72rem; font-weight: 600; padding: 3px 8px; border-radius: 4px; ${eligible ? 'background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid rgba(16,185,129,0.3);' : 'background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid rgba(239,68,68,0.3);'}">
                ${eligible ? '✓ Verified (Indexed)' : '⚠ Quarantined (Missing OCR)'}
              </span>
            </td>
          </tr>
        `;
      }).join('');
    }
  } catch (err) {
    console.warn("Reports inventory fetch error:", err);
  }
}

async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    // GPU Metrics
    const gpu = data.gpu || {};
    const modelDeviceText = document.getElementById("modelDeviceText");
    if (modelDeviceText) {
      if (gpu.available) {
        const vramUsed = (gpu.vram_used_mb / 1024).toFixed(1);
        modelDeviceText.textContent = `RTX 5060 · ${vramUsed} GB`;
      } else {
        modelDeviceText.textContent = "CPU / Cloud";
      }
    }
  } catch (err) {
    console.warn("Status telemetry error:", err);
  }
}

async function executeDevQuery() {
  const query = document.getElementById("devQueryInput")?.value?.trim();
  if (!query) return;

  const btn = document.getElementById("devSubmitBtn");
  if (btn) btn.disabled = true;

  try {
    const methodEl = document.querySelector('input[name="retrievalMethod"]:checked');
    const payload = {
      query: query,
      method: methodEl ? methodEl.value : "hybrid_rrf",
      top_k: parseInt(document.getElementById("topKSlider")?.value || "5", 10),
      document_filter: document.getElementById("reportFilterSelect")?.value || "ALL",
      generate_answer: true,
      max_new_tokens: parseInt(document.getElementById("maxTokensSlider")?.value || "192", 10),
      temperature: 0.0,
      provider: STATE.activeProvider,
      enable_web_search: document.getElementById("webSearchToggle")?.checked !== false,
      context_budget: STATE.contextBudget,
    };

    const res = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Server HTTP ${res.status}`);
    }

    const data = await res.json();
    lastQueryData = data;
    lastEvidenceResults = data.results || [];
    updateDevViewWithData(data);

  } catch (err) {
    alert(`Diagnostic query failed: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function updateDevViewWithData(data) {
  if (!data) return;

  // Latency & Telemetry
  const retLatEl = document.getElementById("statRetrievalLatency");
  if (retLatEl) retLatEl.textContent = `${data.retrieval_latency_ms || 0} ms`;

  const genMs = data.answer ? data.answer.generation_time_ms : 0;
  const genLatEl = document.getElementById("statGenerationLatency");
  if (genLatEl) genLatEl.textContent = `${genMs || 0} ms`;

  const totLatEl = document.getElementById("statTotalLatency");
  if (totLatEl) totLatEl.textContent = `${data.total_query_latency_ms || 0} ms`;

  const candEl = document.getElementById("statCandidatesScored");
  if (candEl) candEl.textContent = (data.total_candidates_scored || 0).toLocaleString();

  const statusPill = document.getElementById("statStatusPill");
  if (statusPill) {
    const status = (data.status || "READY").toUpperCase();
    statusPill.textContent = status;
    if (status.includes("EVIDENCE") || status === "CONVERSATIONAL") {
      statusPill.className = "diag-status-pill green";
    } else if (status.includes("ABSTAINED")) {
      statusPill.className = "diag-status-pill amber";
    } else {
      statusPill.className = "diag-status-pill rose";
    }
  }

  // Answer Card
  const devCard = document.getElementById("devAnswerCard");
  const devContent = document.getElementById("devAnswerContent");
  if (devCard && devContent) {
    if (data.answer) {
      devCard.style.display = "block";
      devContent.innerHTML = formatMessageContent(data.answer.clean_answer || data.answer.answer || "");
      const modelBadge = document.getElementById("answerModelBadge");
      if (modelBadge) modelBadge.textContent = data.answer.model_name || data.answer.provider || "Qwen3-4B";
      const devBadge = document.getElementById("answerDeviceBadge");
      if (devBadge) devBadge.textContent = data.answer.device || "GPU";
    } else {
      devCard.style.display = "none";
    }
  }

  // Evidence Cards List
  const emptyState = document.getElementById("emptyStatePlaceholder");
  const evidenceList = document.getElementById("evidenceList");
  const resultBadge = document.getElementById("resultCountBadge");

  const results = data.results || [];
  if (resultBadge) {
    resultBadge.textContent = `${results.length} ${data.used_web_search ? 'Web Items' : 'Chunks'}`;
  }

  if (results.length === 0) {
    if (emptyState) emptyState.style.display = "flex";
    if (evidenceList) evidenceList.style.display = "none";
  } else {
    if (emptyState) emptyState.style.display = "none";
    if (evidenceList) {
      evidenceList.style.display = "flex";
      evidenceList.innerHTML = "";

      results.forEach((item, idx) => {
        const card = document.createElement("div");
        card.className = "evidence-card";
        const title = item.title || item.section_title || `Candidate [${idx+1}]`;
        const docLabel = item.is_web ? (item.domain || "Web") : `${item.document_id}.pdf · Page ${item.physical_page || ''}`;

        card.innerHTML = `
          <div class="evidence-card-header" onclick="this.parentElement.classList.toggle('highlighted')">
            <div class="evidence-header-left">
              <span class="evidence-num-tag">[${idx+1}]</span>
              <span class="evidence-title-text">${escapeHtml(title)}</span>
            </div>
            <div class="evidence-header-right">
              <span class="evidence-badge ${item.is_web ? 'web' : ''}">${escapeHtml(docLabel)}</span>
            </div>
          </div>
          <div class="evidence-card-body">
            <div class="evidence-text-content">${escapeHtml(item.content || "")}</div>
            ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="web-link-btn" style="display:inline-block; margin-top:8px; color:var(--primary-indigo); font-size:0.78rem;">🔗 Visit Source: ${escapeHtml(item.url)}</a>` : ""}
          </div>
        `;
        evidenceList.appendChild(card);
      });
    }
  }
}

function copyDevAnswerText() {
  if (!lastQueryData || !lastQueryData.answer) return;
  const text = lastQueryData.answer.clean_answer || lastQueryData.answer.answer || "";
  navigator.clipboard.writeText(text).then(() => {
    alert("Answer copied to clipboard!");
  });
}

function openSourcesModal() {
  const modal = document.getElementById("sourcesModalBackdrop");
  if (!modal) return;
  const content = document.getElementById("sourcesModalBody");
  const subtitle = document.getElementById("sourcesModalSubtitle");

  const results = lastEvidenceResults || [];
  const isWeb = Boolean(lastQueryData && lastQueryData.used_web_search);

  if (subtitle) {
    if (isWeb) {
      subtitle.textContent = "Verified Official Web Sources (Guarded Tavily Retrieval)";
    } else {
      subtitle.textContent = "Canonical Annual Report Chunks (Audited Financial Reports)";
    }
  }

  if (content) {
    content.innerHTML = "";
    if (results.length === 0) {
      content.innerHTML = "<p style='color:var(--text-muted); padding: 16px;'>No specific evidence items retrieved for this answer.</p>";
    } else {
      results.forEach((item, idx) => {
        const card = document.createElement("div");
        card.className = "evidence-card";
        card.style.marginBottom = "10px";
        const title = item.title || item.section_title || `Evidence Item [${idx+1}]`;
        const url = item.url || "";
        const pageInfo = item.physical_page ? `Page ${item.physical_page}` : (item.domain || "Web");

        const linkHtml = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" style="display:inline-block; margin-top:8px; color:var(--accent-cyan); font-size:0.8rem;">🔗 Open Official Source: ${escapeHtml(url)}</a>` : "";

        card.innerHTML = `
          <div class="evidence-card-header" style="cursor: default;">
            <div class="evidence-header-left">
              <span class="evidence-num-tag">[${idx+1}]</span>
              <span class="evidence-title-text">${escapeHtml(title)}</span>
            </div>
            <div class="evidence-header-right">
              <span class="evidence-badge ${item.is_web ? 'web' : ''}">${escapeHtml(pageInfo)}</span>
            </div>
          </div>
          <div class="evidence-card-body" style="padding: 12px;">
            <div class="evidence-text-content" style="white-space: pre-wrap; font-size: 0.85rem; line-height: 1.5;">${escapeHtml(item.content || "")}</div>
            ${linkHtml}
          </div>
        `;
        content.appendChild(card);
      });
    }
  }

  modal.style.display = "flex";
}

function closeSourcesModal(event) {
  if (event && event.target !== document.getElementById("sourcesModalBackdrop")) return;
  const modal = document.getElementById("sourcesModalBackdrop");
  if (modal) modal.style.display = "none";
}

function openInDeveloperMode() {
  closeSourcesModal();
  switchUIMode("dev");
}

function toggleAllAccordions(open) {
  document.querySelectorAll("#evidenceList .evidence-card").forEach(c => {
    if (open) c.classList.add("highlighted");
    else c.classList.remove("highlighted");
  });
}



function copyChatMessage(btn, text) {
  let clean = text || "";
  clean = clean.replace(/\[\s*(?:Citation:\s*|Evidence\s*(?:Item\s*)?|Source:\s*|Ref:\s*)[^\]\n]*\]/gi, "");
  clean = clean.replace(/\[\s*\[?\s*\d+(?:\s*[,–-]\s*\d+)*\s*\]?\s*\]/g, "");
  clean = clean.replace(/\n*\s*(?:\*\*)?(?:Note|Explanation|Internal Note|Meta-Note)(?:\*\*)?\s*:[\s\S]*$/i, "");
  clean = clean.replace(/([.!?])\s*[,;]+/g, "$1");
  clean = clean.replace(/(?:\s*,\s*)+(?=[.!?])/g, "");
  clean = clean.replace(/(?:\s*,\s*)+$/gm, ".");
  clean = clean.replace(/\s+([.,;:!?])/g, "$1").trim();
  navigator.clipboard.writeText(clean).then(() => {
    btn.classList.add("copied");
    const span = btn.querySelector("span");
    const orig = span ? span.textContent : "Copy";
    if (span) span.textContent = "Copied!";
    setTimeout(() => {
      btn.classList.remove("copied");
      if (span) span.textContent = orig;
    }, 2000);
  }).catch(err => {
    console.warn("Copy error:", err);
  });
}



function escapeJsString(str) {
  if (!str) return "";
  return String(str)
    .replace(/\\/g, "\\\\")
    .replace(/`/g, "\\`")
    .replace(/\$/g, "\\$");
}

function openHistoricalSourcesModal(evidence, isWeb) {
  lastEvidenceResults = evidence || [];
  lastQueryData = {
    results: lastEvidenceResults,
    used_web_search: Boolean(isWeb),
    query: "Historical Chat Message",
    answer: { clean_answer: "Archived message" }
  };
  openSourcesModal();
}
