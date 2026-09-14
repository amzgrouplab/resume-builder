const STORAGE_KEY = "vellum.settings.v1";
const LAST_PROFILE_KEY = "vellum.lastProfile";
const STAGES = [
  "Reading the Word document",
  "Mapping roles and dates",
  "Checking technology launch years",
  "Rewriting each role against the job description",
  "Putting text back into the original layout",
];

const defaultSettings = {
  apiKey: "",
  model: "gpt-4o",
  strictTimeline: true,
  matchLength: true,
};

const state = {
  settings: loadSettings(),
  file: null,
  profileId: localStorage.getItem(LAST_PROFILE_KEY) || "",
  profiles: [],
  parsed: null,
  result: null,
  busy: false,
  view: "studio",
  newProfileFile: null,
};

function loadSettings() {
  try {
    return { ...defaultSettings, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
  } catch {
    return { ...defaultSettings };
  }
}

function saveSettings() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.settings));
}

function $(id) {
  return document.getElementById(id);
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function maskKey(key) {
  const trimmed = key.trim();
  if (!trimmed) return "";
  if (trimmed.length < 12) return "••••••••";
  return `${trimmed.slice(0, 7)}…${trimmed.slice(-4)}`;
}

function lcs(a, b) {
  const table = Array.from({ length: a.length + 1 }, () => Array(b.length + 1).fill(0));
  for (let i = 1; i <= a.length; i += 1) {
    for (let j = 1; j <= b.length; j += 1) {
      table[i][j] = a[i - 1] === b[j - 1] ? table[i - 1][j - 1] + 1 : Math.max(table[i - 1][j], table[i][j - 1]);
    }
  }
  return table;
}

function diffWords(original, next) {
  const left = original.split(/(\s+)/);
  const right = next.split(/(\s+)/);
  const table = lcs(left, right);
  const tokens = [];
  let i = left.length;
  let j = right.length;
  while (i > 0 && j > 0) {
    if (left[i - 1] === right[j - 1]) {
      tokens.push({ text: left[i - 1], kind: "same" });
      i -= 1;
      j -= 1;
    } else if (table[i - 1][j] >= table[i][j - 1]) {
      tokens.push({ text: left[i - 1], kind: "del" });
      i -= 1;
    } else {
      tokens.push({ text: right[j - 1], kind: "add" });
      j -= 1;
    }
  }
  while (i > 0) {
    tokens.push({ text: left[i - 1], kind: "del" });
    i -= 1;
  }
  while (j > 0) {
    tokens.push({ text: right[j - 1], kind: "add" });
    j -= 1;
  }
  return tokens.reverse();
}

async function readError(res) {
  try {
    const data = await res.json();
    if (typeof data.detail === "string") return data.detail;
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

function setView(view) {
  state.view = view;
  $("studio").classList.toggle("hidden", view !== "studio");
  $("profiles").classList.toggle("hidden", view !== "profiles");
  $("settings").classList.toggle("hidden", view !== "settings");
  $("nav-studio").classList.toggle("active", view === "studio");
  $("nav-profiles").classList.toggle("active", view === "profiles");
  $("nav-settings").classList.toggle("active", view === "settings");
}

function renderKeyChip() {
  const chip = $("key-chip");
  if (state.settings.apiKey) {
    chip.textContent = `OpenAI ${maskKey(state.settings.apiKey)}`;
    chip.classList.add("ready");
    $("key-warning").classList.add("hidden");
  } else {
    chip.textContent = "No API key yet";
    chip.classList.remove("ready");
    $("key-warning").classList.remove("hidden");
  }
}

function hasResume() {
  return Boolean(state.profileId || state.file);
}

function syncRunButton() {
  $("run").disabled = !(hasResume() && $("job").value.trim().length > 40 && state.settings.apiKey && !state.busy);
  $("save-profile").classList.toggle("hidden", !(state.file && !state.profileId));
  $("create-profile").disabled = !(state.newProfileFile && $("profile-name").value.trim());
}

function showError(message, id = "error") {
  const el = $(id);
  if (!message) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.textContent = message;
  el.classList.remove("hidden");
}

function renderParse(parsed) {
  const meta = $("file-meta");
  const roles = $("roles");
  if (!parsed) {
    meta.classList.add("hidden");
    roles.innerHTML = "";
    return;
  }
  meta.classList.remove("hidden");
  meta.innerHTML = `<span>${esc(parsed.bullets)} bullets across ${esc(
    parsed.roles.length
  )} roles</span><span>${esc(parsed.paragraphs)} paragraphs left untouched unless they are list items</span>`;
  roles.innerHTML = parsed.roles
    .map(
      (role) =>
        `<div class="role"><b>${esc(role.title)}</b><span>${esc(role.dates || "dates unread")} · ${esc(
          role.bullets
        )} bullets</span></div>`
    )
    .join("");
}

function renderProgress(stage, visible) {
  const box = $("progress");
  const list = $("stages");
  if (!visible) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  list.innerHTML = STAGES.map((label, index) => {
    const cls = index < stage ? "done" : index === stage ? "on" : "";
    return `<li class="${cls}">${esc(label)}</li>`;
  }).join("");
}

function renderResults(result) {
  const section = $("results");
  if (!result) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");
  const changed = result.updates.filter((row) => row.changed);
  const kept = result.updates.length - changed.length;
  $("stats").innerHTML = `
    <span><b>${esc(result.bullets_changed)}</b> rewritten</span>
    <span><b>${esc(kept)}</b> left as-is</span>
    <span><b>${(result.elapsed_ms / 1000).toFixed(1)}s</b></span>
    ${result.company ? `<span>aligned to <b>${esc(result.company)}</b></span>` : ""}
  `;
  $("notes").textContent = (result.notes || []).join(" ");
  const ordered = [...changed, ...result.updates.filter((row) => !row.changed)];
  $("diffs").innerHTML = ordered
    .map((row) => {
      const tokens = row.changed ? diffWords(row.original, row.rewritten) : [{ text: row.rewritten, kind: "same" }];
      const body = tokens
        .map((token) => `<span class="token ${token.kind}">${esc(token.text)}</span>`)
        .join("");
      return `<article class="diff-card">
        <header>
          <span>${esc(row.role || "Bullet")}${row.dates ? ` · ${esc(row.dates)}` : ""}</span>
          <span>${row.changed ? `${row.char_original}→${row.char_new} chars` : "Unchanged"}</span>
        </header>
        <p>${body}</p>
        ${row.reason ? `<div class="reason">${esc(row.reason)}</div>` : ""}
      </article>`;
    })
    .join("");
}

function renderProfileSelect() {
  const select = $("profile-select");
  const current = state.profileId;
  select.innerHTML = `<option value="">Upload a new file…</option>${state.profiles
    .map((profile) => `<option value="${esc(profile.id)}">${esc(profile.name)}</option>`)
    .join("")}`;
  select.value = state.profiles.some((profile) => profile.id === current) ? current : "";
}

function renderProfileList() {
  const list = $("profile-list");
  if (!state.profiles.length) {
    list.innerHTML = `<p class="fine-print">No profiles yet. Save a Word resume above.</p>`;
    return;
  }
  list.innerHTML = state.profiles
    .map(
      (profile) => `<div class="profile-row">
        <div>
          <b>${esc(profile.name)}</b>
          <span>${esc(profile.bullets)} bullets · ${esc(profile.roles?.length || 0)} roles</span>
        </div>
        <div class="profile-actions">
          <button type="button" class="ghost" data-use="${esc(profile.id)}">Use in Studio</button>
          <button type="button" class="ghost" data-del="${esc(profile.id)}">Delete</button>
        </div>
      </div>`
    )
    .join("");
}

async function loadProfiles() {
  const res = await fetch("/api/profiles");
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json();
  state.profiles = data.profiles || [];
  renderProfileSelect();
  renderProfileList();
}

function hydrateSettings() {
  $("apiKey").value = state.settings.apiKey;
  $("model").value = state.settings.model;
  $("strictTimeline").checked = state.settings.strictTimeline;
  $("matchLength").checked = state.settings.matchLength;
}

function downloadDocx(filename, base64) {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const blob = new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function parseResumePayload(body, label) {
  $("drop-title").textContent = label;
  $("drop-hint").textContent = "Reading bullets and employment dates…";
  const res = await fetch("/api/parse", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  const parsed = await res.json();
  state.parsed = parsed;
  $("drop-hint").textContent = "Word file ready. Layout will be preserved.";
  renderParse(parsed);
}

async function takeFile(file) {
  if (!file) return;
  state.file = file;
  state.profileId = "";
  localStorage.removeItem(LAST_PROFILE_KEY);
  $("profile-select").value = "";
  state.result = null;
  renderResults(null);
  showError("");
  try {
    const body = new FormData();
    body.append("resume", file);
    await parseResumePayload(body, file.name);
  } catch (err) {
    showError(err.message || "Could not read that Word file.");
  }
  syncRunButton();
}

async function selectProfile(profileId) {
  if (!profileId) {
    state.profileId = "";
    localStorage.removeItem(LAST_PROFILE_KEY);
    syncRunButton();
    return;
  }
  state.profileId = profileId;
  state.file = null;
  localStorage.setItem(LAST_PROFILE_KEY, profileId);
  const profile = state.profiles.find((item) => item.id === profileId);
  state.result = null;
  renderResults(null);
  showError("");
  try {
    const body = new FormData();
    body.append("profile_id", profileId);
    await parseResumePayload(body, profile ? profile.name : "Saved profile");
  } catch (err) {
    showError(err.message || "Could not open that profile.");
  }
  syncRunButton();
}

async function tailor() {
  if (!hasResume() || state.busy) return;
  state.busy = true;
  state.result = null;
  showError("");
  renderResults(null);
  $("run").textContent = "Tailoring…";
  syncRunButton();
  const started = Date.now();
  let stage = 0;
  renderProgress(0, true);
  const tick = window.setInterval(() => {
    const ms = Date.now() - started;
    $("timer").textContent = `${(ms / 1000).toFixed(1)}s`;
    stage = Math.min(STAGES.length - 1, Math.floor(ms / 8000));
    renderProgress(stage, true);
  }, 200);

  try {
    const body = new FormData();
    if (state.profileId) body.append("profile_id", state.profileId);
    else body.append("resume", state.file);
    body.append("job_description", $("job").value);
    body.append("model", state.settings.model);
    body.append("strict_timeline", String(state.settings.strictTimeline));
    body.append("match_length", String(state.settings.matchLength));
    const res = await fetch("/api/tailor", {
      method: "POST",
      headers: { "X-OpenAI-Key": state.settings.apiKey },
      body,
    });
    if (!res.ok) throw new Error(await readError(res));
    const result = await res.json();
    state.result = result;
    $("timer").textContent = `${(result.elapsed_ms / 1000).toFixed(1)}s`;
    renderProgress(STAGES.length - 1, false);
    renderResults(result);
  } catch (err) {
    showError(err.message || "Tailoring failed.");
    renderProgress(0, false);
  } finally {
    window.clearInterval(tick);
    state.busy = false;
    $("run").textContent = "Update resume";
    syncRunButton();
  }
}

async function saveCurrentAsProfile() {
  if (!state.file) return;
  const name = window.prompt("Name this profile", state.file.name.replace(/\.docx$/i, ""));
  if (!name) return;
  const body = new FormData();
  body.append("name", name);
  body.append("resume", state.file);
  const res = await fetch("/api/profiles", { method: "POST", body });
  if (!res.ok) {
    showError(await readError(res));
    return;
  }
  const created = await res.json();
  await loadProfiles();
  await selectProfile(created.id);
  $("profile-select").value = created.id;
}

async function createProfileFromPage() {
  if (!state.newProfileFile) return;
  const body = new FormData();
  body.append("name", $("profile-name").value.trim());
  body.append("resume", state.newProfileFile);
  const res = await fetch("/api/profiles", { method: "POST", body });
  if (!res.ok) {
    showError(await readError(res), "profile-error");
    return;
  }
  const created = await res.json();
  state.newProfileFile = null;
  $("profile-name").value = "";
  $("profile-drop-title").textContent = "Drop a Word resume to save";
  showError("", "profile-error");
  await loadProfiles();
  await selectProfile(created.id);
  setView("studio");
}

function bindDrop(el, onFile) {
  el.addEventListener("dragover", (event) => {
    event.preventDefault();
    el.classList.add("hot");
  });
  el.addEventListener("dragleave", () => el.classList.remove("hot"));
  el.addEventListener("drop", (event) => {
    event.preventDefault();
    el.classList.remove("hot");
    onFile(event.dataTransfer.files[0]);
  });
}

function bind() {
  $("nav-studio").addEventListener("click", () => setView("studio"));
  $("nav-profiles").addEventListener("click", () => setView("profiles"));
  $("nav-settings").addEventListener("click", () => setView("settings"));
  $("open-settings").addEventListener("click", () => setView("settings"));
  $("choose-file").addEventListener("click", () => $("file-input").click());
  $("file-input").addEventListener("change", (event) => takeFile(event.target.files[0]));
  $("choose-profile-file").addEventListener("click", () => $("profile-file-input").click());
  $("profile-file-input").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (!file) return;
    state.newProfileFile = file;
    $("profile-drop-title").textContent = file.name;
    if (!$("profile-name").value.trim()) {
      $("profile-name").value = file.name.replace(/\.docx$/i, "");
    }
    syncRunButton();
  });
  bindDrop($("drop"), takeFile);
  bindDrop($("profile-drop"), (file) => {
    if (!file) return;
    state.newProfileFile = file;
    $("profile-drop-title").textContent = file.name;
    if (!$("profile-name").value.trim()) {
      $("profile-name").value = file.name.replace(/\.docx$/i, "");
    }
    syncRunButton();
  });

  $("profile-select").addEventListener("change", (event) => selectProfile(event.target.value));
  $("profile-name").addEventListener("input", syncRunButton);
  $("save-profile").addEventListener("click", saveCurrentAsProfile);
  $("create-profile").addEventListener("click", createProfileFromPage);
  $("profile-list").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.use) {
      await selectProfile(button.dataset.use);
      $("profile-select").value = button.dataset.use;
      setView("studio");
    }
    if (button.dataset.del) {
      const res = await fetch(`/api/profiles/${button.dataset.del}`, { method: "DELETE" });
      if (!res.ok) {
        showError(await readError(res), "profile-error");
        return;
      }
      if (state.profileId === button.dataset.del) {
        state.profileId = "";
        localStorage.removeItem(LAST_PROFILE_KEY);
      }
      await loadProfiles();
      syncRunButton();
    }
  });

  $("job").addEventListener("input", syncRunButton);
  $("run").addEventListener("click", tailor);
  $("download").addEventListener("click", () => {
    if (state.result) downloadDocx(state.result.filename, state.result.docx_base64);
  });

  ["apiKey", "model", "strictTimeline", "matchLength"].forEach((id) => {
    $(id).addEventListener("input", persistSettings);
    $(id).addEventListener("change", persistSettings);
  });

  $("test-key").addEventListener("click", async () => {
    const box = $("test-state");
    box.className = "status-ok";
    box.textContent = "Checking…";
    try {
      const res = await fetch("/api/settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: state.settings.apiKey, model: state.settings.model }),
      });
      if (!res.ok) throw new Error(await readError(res));
      box.textContent = "Key accepted for this model.";
    } catch (err) {
      box.className = "error";
      box.textContent = err.message || "Could not verify the key.";
    }
  });
}

function persistSettings() {
  state.settings = {
    apiKey: $("apiKey").value.trim(),
    model: $("model").value,
    strictTimeline: $("strictTimeline").checked,
    matchLength: $("matchLength").checked,
  };
  saveSettings();
  renderKeyChip();
  syncRunButton();
}

hydrateSettings();
renderKeyChip();
bind();
syncRunButton();
loadProfiles()
  .then(() => {
    if (state.profileId) return selectProfile(state.profileId);
    return null;
  })
  .catch((err) => showError(err.message || "Could not load profiles."));
