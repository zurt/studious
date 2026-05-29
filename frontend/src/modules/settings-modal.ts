import {
  CostSummary,
  DocMeta,
  Preferences,
  ProvidersResponse,
  getCostSummary,
  getDocument,
  getPreferences,
  getProviders,
  listDocuments,
  updatePreferences,
} from "../api";
import { error as logError } from "../logger";
import { replaceQuery } from "../router";

type Section = "general" | "usage";

const SECTIONS: Section[] = ["general", "usage"];

function isSection(v: string | null): v is Section {
  return v !== null && (SECTIONS as string[]).includes(v);
}

let activeModal: { setSection: (s: Section) => void; close: () => void } | null = null;

export function settingsSectionFromUrl(): Section | null {
  const v = new URLSearchParams(location.search).get("settings");
  return isSection(v) ? v : null;
}

export function syncSettingsModalFromUrl(): void {
  const section = settingsSectionFromUrl();
  if (section === null) {
    activeModal?.close();
    return;
  }
  if (activeModal) activeModal.setSection(section);
  else openSettingsModal(section);
}

export function openSettingsModal(initial: Section = "general"): void {
  if (activeModal) {
    activeModal.setSection(initial);
    replaceQuery({ settings: initial });
    return;
  }
  replaceQuery({ settings: initial });
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `
    <div class="modal settings-modal">
      <div class="settings-header">
        <h2>Settings</h2>
        <button class="icon-btn" id="settings-close" title="Close">&#x2716;</button>
      </div>
      <div class="settings-body">
        <ul class="settings-nav" role="tablist">
          <li class="settings-nav-item active" data-section="general">General</li>
          <li class="settings-nav-item" data-section="usage">Usage</li>
        </ul>
        <div class="settings-content" id="settings-content">
          <div class="muted">Loading…</div>
        </div>
      </div>
    </div>
  `;
  (document.fullscreenElement ?? document.body).appendChild(bg);

  const content = bg.querySelector<HTMLElement>("#settings-content")!;
  const navItems = Array.from(bg.querySelectorAll<HTMLElement>(".settings-nav-item"));

  let current: Section = initial;

  function close() {
    document.removeEventListener("keydown", onKey);
    bg.remove();
    activeModal = null;
    replaceQuery({ settings: null });
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") close();
  }
  bg.querySelector("#settings-close")!.addEventListener("click", close);
  bg.addEventListener("click", (e) => { if (e.target === bg) close(); });
  document.addEventListener("keydown", onKey);

  function select(section: Section, updateUrl: boolean) {
    current = section;
    for (const el of navItems) {
      el.classList.toggle("active", el.dataset.section === section);
    }
    if (updateUrl) replaceQuery({ settings: section });
    if (section === "general") renderGeneral(content);
    else renderUsage(content);
  }
  for (const el of navItems) {
    el.addEventListener("click", () => select(el.dataset.section as Section, true));
  }

  activeModal = {
    setSection: (s) => { if (s !== current) select(s, false); },
    close,
  };

  select(current, false);
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]!));
}

function fmtBytes(n: number): string {
  if (!n) return "0";
  const k = 1024;
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(k)));
  return `${(n / Math.pow(k, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function fmtUsd(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function fmtNum(n: number): string {
  return n.toLocaleString();
}

async function renderGeneral(host: HTMLElement) {
  host.innerHTML = `<div class="muted">Loading…</div>`;
  try {
    const [providers, prefs, docList] = await Promise.all([
      getProviders(),
      getPreferences(),
      listDocuments(),
    ]);
    const docs = await Promise.all(
      docList.map((d) => getDocument(d.id).catch(() => d))
    );
    host.innerHTML = generalHtml(providers, prefs, docs);
    wireGeneral(host);
  } catch (e: any) {
    logError("SettingsModal", "general_load_failed", { error: e?.message ?? String(e), stack: e?.stack });
    host.innerHTML = `<div class="error">Failed to load: ${escapeHtml(String(e))}</div>`;
  }
}

function generalHtml(
  providers: ProvidersResponse,
  prefs: Preferences,
  docs: DocMeta[]
): string {
  const d = providers.defaults;
  const modelOptions = prefs.available_vlm_models
    .map((m) => {
      const selected = m === prefs.vlm_model ? " selected" : "";
      const suffix = m === prefs.default_vlm_model ? " (default)" : "";
      return `<option value="${escapeHtml(m)}"${selected}>${escapeHtml(m)}${suffix}</option>`;
    })
    .join("");
  const vlmList = providers.vlm.map((p) => {
    const flag = p.unavailable ? ` <span class="muted">(unavailable: ${escapeHtml(p.unavailable)})</span>` : "";
    return `<li><code>${escapeHtml(p.name)}</code>${flag}</li>`;
  }).join("");
  const ocrList = providers.ocr.map((p) => {
    const flag = p.unavailable ? ` <span class="muted">(unavailable: ${escapeHtml(p.unavailable)})</span>` : "";
    return `<li><code>${escapeHtml(p.name)}</code>${flag}</li>`;
  }).join("");

  const docRows = docs.length
    ? docs.map((doc) => {
        const ch = doc.chapters?.length ?? 0;
        const rTrans = doc.regions_transcribed ?? 0;
        const rTotal = doc.regions_total ?? 0;
        const regionsCell = rTotal === 0 ? "0" : `${rTrans} / ${rTotal}`;
        const created = doc.created_at ? new Date(doc.created_at).toLocaleDateString() : "—";
        return `
          <tr>
            <td>${escapeHtml(doc.name)}</td>
            <td><code>${escapeHtml(doc.source_type)}</code></td>
            <td>${doc.page_count}</td>
            <td>${ch}</td>
            <td>${regionsCell}</td>
            <td class="muted">${escapeHtml(created)}</td>
          </tr>
        `;
      }).join("")
    : `<tr><td colspan="6" class="muted">No documents in library.</td></tr>`;

  return `
    <section class="settings-section">
      <h3>Configuration</h3>
      <dl class="settings-dl">
        <dt>Default VLM provider</dt><dd><code>${escapeHtml(d.vlm)}</code></dd>
        <dt>Default VLM model</dt><dd>
          <select id="settings-vlm-model" class="settings-select">${modelOptions}</select>
          <span id="settings-vlm-model-status" class="muted small" style="margin-left:0.5rem;"></span>
        </dd>
        <dt>Default OCR provider</dt><dd><code>${escapeHtml(d.ocr)}</code></dd>
        <dt>VLM providers</dt><dd><ul class="settings-inline-list">${vlmList || '<li class="muted">none</li>'}</ul></dd>
        <dt>OCR providers</dt><dd><ul class="settings-inline-list">${ocrList || '<li class="muted">none</li>'}</ul></dd>
      </dl>
    </section>
    <section class="settings-section">
      <h3>Library (${docs.length} document${docs.length === 1 ? "" : "s"})</h3>
      <table class="settings-table">
        <thead>
          <tr>
            <th>Name</th><th>Type</th><th>Pages</th><th>Chapters</th><th>Regions transcribed</th><th>Created</th>
          </tr>
        </thead>
        <tbody>${docRows}</tbody>
      </table>
      <p class="muted small">Note: full-page transcription is not currently in use — region-level transcription is the active workflow.</p>
    </section>
  `;
}

function wireGeneral(host: HTMLElement): void {
  const select = host.querySelector<HTMLSelectElement>("#settings-vlm-model");
  const status = host.querySelector<HTMLElement>("#settings-vlm-model-status");
  if (!select) return;
  select.addEventListener("change", async () => {
    const model = select.value;
    select.disabled = true;
    if (status) status.textContent = "Saving…";
    try {
      await updatePreferences({ vlm_model: model });
      if (status) status.textContent = "Saved.";
    } catch (e: any) {
      logError("SettingsModal", "preferences_save_failed", { error: e?.message ?? String(e) });
      if (status) status.textContent = `Failed: ${e?.message ?? String(e)}`;
    } finally {
      select.disabled = false;
    }
  });
}

async function renderUsage(host: HTMLElement) {
  host.innerHTML = `<div class="muted">Loading…</div>`;
  try {
    const [summary, docs] = await Promise.all([getCostSummary(), listDocuments()]);
    host.innerHTML = usageHtml(summary, docs);
  } catch (e: any) {
    logError("SettingsModal", "usage_load_failed", { error: e?.message ?? String(e), stack: e?.stack });
    host.innerHTML = `<div class="error">Failed to load: ${escapeHtml(String(e))}</div>`;
  }
}

function usageHtml(s: CostSummary, docs: DocMeta[]): string {
  const docNames = new Map<string, string>();
  for (const d of docs) docNames.set(d.id, d.name);

  const rangeLabel = s.first_timestamp && s.last_timestamp
    ? `${new Date(s.first_timestamp).toLocaleDateString()} → ${new Date(s.last_timestamp).toLocaleDateString()}`
    : "no requests yet";

  const modelRows = Object.entries(s.by_model)
    .sort((a, b) => b[1].estimated_cost_usd - a[1].estimated_cost_usd)
    .map(([model, b]) => `
      <tr>
        <td><code>${escapeHtml(model)}</code></td>
        <td>${fmtNum(b.requests)}</td>
        <td>${fmtNum(b.input_tokens)}</td>
        <td>${fmtNum(b.output_tokens)}</td>
        <td>${fmtUsd(b.estimated_cost_usd)}</td>
      </tr>
    `).join("");

  const docRows = Object.entries(s.by_doc)
    .sort((a, b) => b[1].estimated_cost_usd - a[1].estimated_cost_usd)
    .map(([docId, b]) => {
      const label = docId === "(none)" ? "(unattributed)" : (docNames.get(docId) ?? docId);
      return `
        <tr>
          <td title="${escapeHtml(docId)}">${escapeHtml(label)}</td>
          <td>${fmtNum(b.requests)}</td>
          <td>${fmtNum(b.input_tokens)}</td>
          <td>${fmtNum(b.output_tokens)}</td>
          <td>${fmtUsd(b.estimated_cost_usd)}</td>
        </tr>
      `;
    }).join("");

  const unknown = s.unknown_models.length
    ? `<p class="muted small">Models without pricing data (cost reported as $0): ${s.unknown_models.map((m) => `<code>${escapeHtml(m)}</code>`).join(", ")}</p>`
    : "";

  void fmtBytes;

  if (s.total_requests === 0) {
    return `
      <section class="settings-section">
        <div class="usage-empty">
          <div class="usage-empty-title">No usage recorded yet</div>
          <p class="muted">Spend appears here once a VLM transcription runs. Each Anthropic API call is logged to <code>backend/data/llm_audit.jsonl</code> with token counts; this view aggregates that log and applies the per-model pricing table.</p>
          <p class="muted small">Note: transcriptions completed before the audit log was added are not counted.</p>
        </div>
      </section>
    `;
  }

  return `
    <section class="settings-section">
      <div class="usage-totals">
        <div class="usage-stat">
          <div class="usage-stat-label">Estimated spend</div>
          <div class="usage-stat-value">${fmtUsd(s.total_estimated_cost_usd)}</div>
        </div>
        <div class="usage-stat">
          <div class="usage-stat-label">Requests</div>
          <div class="usage-stat-value">${fmtNum(s.total_requests)}</div>
          <div class="usage-stat-sub muted">${s.success_count} ok · ${s.error_count} error</div>
        </div>
        <div class="usage-stat">
          <div class="usage-stat-label">Input tokens</div>
          <div class="usage-stat-value">${fmtNum(s.total_input_tokens)}</div>
        </div>
        <div class="usage-stat">
          <div class="usage-stat-label">Output tokens</div>
          <div class="usage-stat-value">${fmtNum(s.total_output_tokens)}</div>
        </div>
      </div>
      <p class="muted small">Range: ${escapeHtml(rangeLabel)}. Estimates use the pricing table in the backend; they ignore prompt-cache discounts.</p>
    </section>

    ${s.total_requests === 0 ? "" : `
    <section class="settings-section">
      <h3>By model</h3>
      <table class="settings-table">
        <thead><tr><th>Model</th><th>Requests</th><th>Input</th><th>Output</th><th>Cost</th></tr></thead>
        <tbody>${modelRows}</tbody>
      </table>
    </section>

    <section class="settings-section">
      <h3>By document</h3>
      <table class="settings-table">
        <thead><tr><th>Document</th><th>Requests</th><th>Input</th><th>Output</th><th>Cost</th></tr></thead>
        <tbody>${docRows}</tbody>
      </table>
      ${unknown}
    </section>
    `}
  `;
}
