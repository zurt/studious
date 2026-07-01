import {
  listStoreItems,
  createStoreItem,
  patchStoreItem,
  deleteStoreItem,
  getStoreStats,
  runStoreBackfill,
  listDocuments,
  getWanikaniStatus,
  syncWanikani,
  getVocabWanikani,
  type DocMeta,
  type GrammarItem,
  type StoreItem,
  type StoreKind,
  type StoreListParams,
  type StoreStatus,
  type VocabItem,
  type WkDrilldown,
  type WkSubjectView,
} from "../api";
import { confirmDialog } from "../modules/confirm";
import { toastError, toastInfo } from "../modules/toast";
import { info, error as logError } from "../logger";
import { navigate, replaceQuery } from "../router";

const PAGE_SIZE = 100;
const STATUSES: StoreStatus[] = ["unreviewed", "active", "known", "ignored"];
const STATUS_LABELS: Record<StoreStatus, string> = {
  unreviewed: "Inbox",
  active: "Active",
  known: "Known",
  ignored: "Ignored",
};

type State = {
  kind: StoreKind;
  status: StoreStatus | "";
  q: string;
  docId: string;
  source: string;
  sort: "recent" | "updated" | "alpha" | "priority";
  items: StoreItem[];
  total: number;
  expanded: Set<string>;
};

export function mountVocabDashboard(_params: Record<string, string>, container: HTMLElement) {
  mountStudyDashboard("vocab", container);
}

export function mountGrammarDashboard(_params: Record<string, string>, container: HTMLElement) {
  mountStudyDashboard("grammar", container);
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isVocab(item: StoreItem): item is VocabItem {
  return "headword" in item;
}

// WaniKani mnemonics carry markup like <radical>…</radical>; escape
// everything, then turn just those known tags into styled spans.
function wkMarkup(text: string): string {
  return escapeHtml(text).replace(
    /&lt;(\/?)(radical|kanji|vocabulary|reading|ja)&gt;/g,
    (_m, close, tag) => (close ? "</span>" : `<span class="wk-tag wk-tag-${tag}">`),
  );
}

function wkSrsChip(subject: WkSubjectView): string {
  if (!subject.srs) return "";
  const year = subject.srs.burned_at ? ` ${subject.srs.burned_at.slice(0, 4)}` : "";
  return `<span class="study-badge wk-srs wk-srs-${escapeHtml(subject.srs.stage_name)}">${escapeHtml(subject.srs.stage_name)}${year}</span>`;
}

function wkSubjectBlock(subject: WkSubjectView, heading: string): string {
  const notes = subject.user_notes;
  return `
    <div class="wk-subject wk-subject-${subject.object}">
      <div class="row wk-subject-head">
        <span class="wk-chars" lang="ja">${escapeHtml(subject.characters || subject.slug)}</span>
        <span class="wk-meta">${heading} · level ${subject.level} · ${escapeHtml(subject.meanings.join(", "))}${subject.readings.length ? ` · ${escapeHtml(subject.readings.join("・"))}` : ""}</span>
        <div class="grow"></div>
        ${wkSrsChip(subject)}
        <a class="study-link" href="${escapeHtml(subject.document_url)}" target="_blank" rel="noopener noreferrer">WK ↗</a>
      </div>
      ${subject.meaning_mnemonic ? `<div class="wk-mnemonic">${wkMarkup(subject.meaning_mnemonic)}</div>` : ""}
      ${subject.reading_mnemonic ? `<div class="wk-mnemonic">${wkMarkup(subject.reading_mnemonic)}</div>` : ""}
      ${
        notes && (notes.meaning_note || notes.reading_note || notes.synonyms.length)
          ? `<div class="wk-user-notes">Your notes: ${escapeHtml(
              [notes.meaning_note, notes.reading_note, notes.synonyms.join(", ")]
                .filter(Boolean)
                .join(" — "),
            )}</div>`
          : ""
      }
    </div>`;
}

function renderWkDrilldown(d: WkDrilldown): string {
  return `
    <div class="wk-drilldown">
      ${wkSubjectBlock(d, "vocabulary")}
      ${d.kanji
        .map(
          (k) => `
            ${wkSubjectBlock(k, "kanji")}
            <div class="wk-radicals">${k.radicals.map((r) => wkSubjectBlock(r, "radical")).join("")}</div>`,
        )
        .join("")}
    </div>`;
}

function mountStudyDashboard(kind: StoreKind, container: HTMLElement) {
  const query = new URLSearchParams(location.search);
  const state: State = {
    kind,
    status: (query.get("status") as StoreStatus) || "",
    q: query.get("q") || "",
    docId: "",
    source: "",
    sort: "recent",
    items: [],
    total: 0,
    expanded: new Set(),
  };
  if (state.status && !STATUSES.includes(state.status as StoreStatus)) state.status = "";

  const title = kind === "vocab" ? "Vocabulary" : "Grammar";
  container.innerHTML = `
    <div class="study-dash">
      <div class="row study-dash-header">
        <h2 style="margin:0">${title}</h2>
        <div id="study-stats" class="study-stats"></div>
        <div class="grow"></div>
        <button id="study-add-btn" title="Add an entry by hand">+ Add</button>
        <button id="study-backfill-btn" title="Re-harvest all breakdowns and vocab lists on disk">Backfill</button>
        <button id="study-wk-btn" hidden title="Sync WaniKani levels, mnemonics, and your notes">Sync WK</button>
      </div>
      <form id="study-add-form" class="study-add-form" hidden></form>
      <div class="row study-filters">
        <input id="study-search" type="search" placeholder="Search ${kind === "vocab" ? "word, reading, meaning" : "pattern, explanation"}…" value="${escapeHtml(state.q)}" />
        <select id="study-doc-filter"><option value="">All textbooks</option></select>
        <select id="study-source-filter">
          <option value="">All sources</option>
          <option value="vocab_list">Vocab lists</option>
          <option value="breakdown">Breakdowns</option>
          <option value="manual">Manual</option>
        </select>
        <select id="study-sort">
          <option value="recent">Newest</option>
          <option value="updated">Recently updated</option>
          <option value="alpha">${kind === "vocab" ? "By reading" : "By pattern"}</option>
          ${kind === "vocab" ? `<option value="priority">By study priority</option>` : ""}
        </select>
      </div>
      <div id="study-bulk-bar" class="row study-bulk-bar" hidden></div>
      <div id="study-list" class="study-list"></div>
      <div class="row" style="justify-content:center;margin:12px 0">
        <button id="study-more-btn" hidden>Load more</button>
      </div>
    </div>
  `;

  const listEl = container.querySelector<HTMLElement>("#study-list")!;
  const statsEl = container.querySelector<HTMLElement>("#study-stats")!;
  const bulkBar = container.querySelector<HTMLElement>("#study-bulk-bar")!;
  const moreBtn = container.querySelector<HTMLButtonElement>("#study-more-btn")!;
  const searchInput = container.querySelector<HTMLInputElement>("#study-search")!;
  const docFilter = container.querySelector<HTMLSelectElement>("#study-doc-filter")!;
  const sourceFilter = container.querySelector<HTMLSelectElement>("#study-source-filter")!;
  const sortSelect = container.querySelector<HTMLSelectElement>("#study-sort")!;
  const addBtn = container.querySelector<HTMLButtonElement>("#study-add-btn")!;
  const addForm = container.querySelector<HTMLFormElement>("#study-add-form")!;
  const backfillBtn = container.querySelector<HTMLButtonElement>("#study-backfill-btn")!;
  const wkBtn = container.querySelector<HTMLButtonElement>("#study-wk-btn")!;

  let docs: DocMeta[] = [];
  const docNames = new Map<string, string>();
  let wkHasData = false;

  function params(offset = 0): StoreListParams {
    return {
      status: (state.status || undefined) as StoreStatus | undefined,
      q: state.q || undefined,
      doc_id: state.docId || undefined,
      source: state.source || undefined,
      sort: state.sort,
      limit: PAGE_SIZE,
      offset,
    };
  }

  async function refreshStats() {
    try {
      const stats = await getStoreStats();
      const s = stats[state.kind];
      statsEl.innerHTML = ["", ...STATUSES]
        .map((status) => {
          const count = status ? (s[status] ?? 0) : (s.total ?? 0);
          const label = status ? STATUS_LABELS[status as StoreStatus] : "All";
          const active = state.status === status ? " active" : "";
          return `<button class="study-stat-chip${active}" data-status="${status}">${label} <span class="study-stat-count">${count}</span></button>`;
        })
        .join("");
      statsEl.querySelectorAll<HTMLButtonElement>(".study-stat-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
          state.status = (chip.dataset.status || "") as State["status"];
          replaceQuery({ status: state.status || null });
          void reload();
        });
      });
    } catch (e: any) {
      logError("StudyDash", "stats_failed", { error: e.message });
    }
  }

  async function reload() {
    listEl.innerHTML = `<p class="empty">Loading…</p>`;
    try {
      const res = await listStoreItems(state.kind, params(0));
      state.items = res.items;
      state.total = res.total;
      render();
      void refreshStats();
    } catch (e: any) {
      logError("StudyDash", "list_failed", { error: e.message, stack: e.stack });
      listEl.innerHTML = `<p class="error">Failed to load: ${escapeHtml(e.message)}</p>`;
    }
  }

  async function loadMore() {
    try {
      const res = await listStoreItems(state.kind, params(state.items.length));
      state.items = [...state.items, ...res.items];
      state.total = res.total;
      render();
    } catch (e: any) {
      toastError("Failed to load more: " + e.message);
    }
  }

  function render() {
    moreBtn.hidden = state.items.length >= state.total;
    renderBulkBar();
    if (state.items.length === 0) {
      const filtered = state.status || state.q || state.docId || state.source;
      listEl.innerHTML = filtered
        ? `<p class="empty">No ${state.kind} items match the current filters.</p>`
        : `<p class="empty">Nothing here yet. Items are harvested automatically when you
           transcribe vocab lists or generate sentence breakdowns — or click
           <strong>Backfill</strong> to harvest everything already on disk.</p>`;
      return;
    }
    listEl.innerHTML = "";
    for (const item of state.items) listEl.appendChild(renderRow(item));
  }

  function renderBulkBar() {
    const showBulk = state.status === "unreviewed" && state.items.length > 0;
    bulkBar.hidden = !showBulk;
    if (!showBulk) return;
    bulkBar.innerHTML = `
      <span class="study-bulk-label">${state.items.length} shown</span>
      <button data-bulk="active">Accept all shown</button>
      <button data-bulk="ignored">Ignore all shown</button>
    `;
    bulkBar.querySelectorAll<HTMLButtonElement>("[data-bulk]").forEach((btn) => {
      btn.addEventListener("click", () => void bulkSet(btn.dataset.bulk as StoreStatus, btn));
    });
  }

  async function bulkSet(status: StoreStatus, btn: HTMLButtonElement) {
    const targets = [...state.items];
    const ok = await confirmDialog(
      status === "ignored" ? "Ignore all shown?" : "Accept all shown?",
      `Set ${targets.length} shown item(s) to "${STATUS_LABELS[status]}"?`,
      STATUS_LABELS[status],
    );
    if (!ok) return;
    btn.disabled = true;
    let failures = 0;
    for (const item of targets) {
      try {
        await patchStoreItem(state.kind, item.id, { status });
      } catch {
        failures += 1;
      }
    }
    info("StudyDash", "bulk_status", { kind: state.kind, status, count: targets.length, failures });
    if (failures) toastError(`${failures} item(s) failed to update`);
    await reload();
  }

  function renderRow(item: StoreItem): HTMLElement {
    const row = document.createElement("div");
    row.className = "study-row";
    row.dataset.id = item.id;

    const term = isVocab(item) ? item.headword : item.pattern;
    const sub = isVocab(item) ? item.reading : "";
    const gloss = isVocab(item) ? item.meaning : (item as GrammarItem).explanation;
    const sources = [...new Set(item.sightings.map((s) => s.source))];
    const sightingCount = item.sightings.length;
    const c = item.classifications || {};
    const classChips = [
      c.jlpt ? `<span class="study-badge study-badge-jlpt">${escapeHtml(String(c.jlpt))}</span>` : "",
      c.jmdict_common ? `<span class="study-badge study-badge-common">common</span>` : "",
      typeof c.wanikani_level === "number"
        ? `<span class="study-badge study-badge-wk">WK ${c.wanikani_level}</span>`
        : "",
    ].join("");

    row.innerHTML = `
      <div class="study-row-main">
        <span class="study-term" lang="ja">${escapeHtml(term)}</span>
        ${sub && sub !== term ? `<span class="study-reading" lang="ja">${escapeHtml(sub)}</span>` : ""}
        <span class="study-gloss">${escapeHtml(gloss)}</span>
        <div class="grow"></div>
        ${classChips}
        ${sources.map((s) => `<span class="study-badge study-badge-${s}">${s.replace("_", " ")}</span>`).join("")}
        <button class="study-sightings-btn" title="Details, sightings, kanji breakdown">${sightingCount ? `${sightingCount}×` : "…"}</button>
        <div class="study-status-toggle">
          ${STATUSES.map(
            (s) =>
              `<button class="study-status-btn${item.status === s ? " active" : ""}" data-status="${s}" title="${STATUS_LABELS[s]}">${STATUS_LABELS[s]}</button>`,
          ).join("")}
        </div>
        <button class="study-delete-btn icon-btn" title="Delete entry" aria-label="Delete entry">✕</button>
      </div>
      <div class="study-row-detail" hidden></div>
    `;

    const detail = row.querySelector<HTMLElement>(".study-row-detail")!;
    const sightingsBtn = row.querySelector<HTMLButtonElement>(".study-sightings-btn")!;
    sightingsBtn.addEventListener("click", () => {
      const open = !detail.hidden;
      detail.hidden = open;
      if (open) {
        state.expanded.delete(item.id);
        return;
      }
      state.expanded.add(item.id);
      renderDetail(item, detail);
    });
    if (state.expanded.has(item.id)) {
      detail.hidden = false;
      renderDetail(item, detail);
    }

    row.querySelectorAll<HTMLButtonElement>(".study-status-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const status = btn.dataset.status as StoreStatus;
        if (status === item.status) return;
        try {
          const updated = await patchStoreItem(state.kind, item.id, { status });
          Object.assign(item, updated);
          row.replaceWith(renderRow(item));
          void refreshStats();
        } catch (e: any) {
          logError("StudyDash", "status_failed", { item_id: item.id, error: e.message });
          toastError("Update failed: " + e.message);
        }
      });
    });

    row.querySelector<HTMLButtonElement>(".study-delete-btn")!.addEventListener("click", async () => {
      const ok = await confirmDialog(
        "Delete entry?",
        `Delete "${term}" from the ${state.kind} store? Harvesting will not re-create it.`,
      );
      if (!ok) return;
      try {
        await deleteStoreItem(state.kind, item.id);
        state.items = state.items.filter((i) => i.id !== item.id);
        state.total -= 1;
        render();
        void refreshStats();
      } catch (e: any) {
        toastError("Delete failed: " + e.message);
      }
    });

    return row;
  }

  function renderDetail(item: StoreItem, detail: HTMLElement) {
    const links = Object.entries(item.links || {})
      .map(
        ([name, url]) =>
          `<a class="study-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(name)} ↗</a>`,
      )
      .join("");
    const sightings = item.sightings
      .map((s) => {
        const docName = docNames.get(s.doc_id) || s.doc_id;
        const context = s.sentence_text || s.surface;
        return `
          <div class="study-sighting">
            <span class="study-badge study-badge-${s.source}">${s.source.replace("_", " ")}</span>
            <span class="study-sighting-text" lang="ja">${escapeHtml(context)}</span>
            <a href="/doc/${s.doc_id}/chapter/${s.chapter_id}" data-nav-chapter>${escapeHtml(docName)} →</a>
          </div>`;
      })
      .join("");
    detail.innerHTML = `
      ${links ? `<div class="row study-links">${links}</div>` : ""}
      ${sightings || `<p class="empty">No sightings.</p>`}
      <div class="study-wk" hidden></div>
    `;
    detail.querySelectorAll<HTMLAnchorElement>("[data-nav-chapter]").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        navigate(a.getAttribute("href")!);
      });
    });
    if (state.kind === "vocab" && wkHasData) {
      void loadWkDrilldown(item.id, detail.querySelector<HTMLElement>(".study-wk")!);
    }
  }

  async function loadWkDrilldown(itemId: string, el: HTMLElement) {
    try {
      const d = await getVocabWanikani(itemId);
      el.hidden = false;
      el.innerHTML = renderWkDrilldown(d);
    } catch {
      // 404 (word not on WK) or 409 (cache empty) — just omit the section.
      el.remove();
    }
  }

  function renderAddForm() {
    const fields =
      state.kind === "vocab"
        ? `
          <input name="headword" placeholder="Word (漢字)" required lang="ja" />
          <input name="reading" placeholder="Reading (かな)" lang="ja" />
          <input name="meaning" placeholder="Meaning" />`
        : `
          <input name="pattern" placeholder="Pattern (〜に関わらず)" required lang="ja" />
          <input name="explanation" placeholder="Explanation" />`;
    addForm.innerHTML = `
      <div class="row">
        ${fields}
        <button type="submit">Add</button>
        <button type="button" id="study-add-cancel">Cancel</button>
      </div>
    `;
    addForm.querySelector("#study-add-cancel")!.addEventListener("click", () => {
      addForm.hidden = true;
    });
  }

  addBtn.addEventListener("click", () => {
    addForm.hidden = !addForm.hidden;
    if (!addForm.hidden) {
      renderAddForm();
      addForm.querySelector<HTMLInputElement>("input")!.focus();
    }
  });

  addForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(addForm).entries()) as Record<string, string>;
    try {
      await createStoreItem(state.kind, data);
      addForm.hidden = true;
      toastInfo("Added");
      await reload();
    } catch (err: any) {
      const conflict = String(err.message).includes("409");
      toastError(conflict ? "Already in the store." : "Add failed: " + err.message);
    }
  });

  wkBtn.addEventListener("click", async () => {
    wkBtn.disabled = true;
    wkBtn.textContent = "Syncing WK…";
    try {
      const result: any = await syncWanikani();
      info("StudyDash", "wk_sync_done", result);
      const fetched = result.fetched || {};
      toastInfo(
        `WaniKani synced: ${fetched.subjects ?? 0} subjects, ${fetched.study_materials ?? 0} notes, ` +
          `${fetched.assignments ?? 0} assignments updated`,
      );
      wkHasData = true;
      await reload();
    } catch (e: any) {
      logError("StudyDash", "wk_sync_failed", { error: e.message });
      toastError("WaniKani sync failed: " + e.message);
    } finally {
      wkBtn.disabled = false;
      wkBtn.textContent = "Sync WK";
    }
  });

  backfillBtn.addEventListener("click", async () => {
    backfillBtn.disabled = true;
    backfillBtn.textContent = "Backfilling…";
    try {
      const totals = await runStoreBackfill();
      info("StudyDash", "backfill_done", totals);
      toastInfo(
        `Backfill done: ${totals.vocab_list_regions} vocab list(s), ${totals.breakdowns} breakdown(s), ` +
          `${totals.vocab_created + totals.grammar_created} new item(s)`,
      );
      await reload();
    } catch (e: any) {
      logError("StudyDash", "backfill_failed", { error: e.message, stack: e.stack });
      toastError("Backfill failed: " + e.message);
    } finally {
      backfillBtn.disabled = false;
      backfillBtn.textContent = "Backfill";
    }
  });

  let searchTimer: number | undefined;
  searchInput.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      state.q = searchInput.value.trim();
      replaceQuery({ q: state.q || null });
      void reload();
    }, 250);
  });

  docFilter.addEventListener("change", () => {
    state.docId = docFilter.value;
    void reload();
  });
  sourceFilter.addEventListener("change", () => {
    state.source = sourceFilter.value;
    void reload();
  });
  sortSelect.addEventListener("change", () => {
    state.sort = sortSelect.value as State["sort"];
    void reload();
  });
  moreBtn.addEventListener("click", () => void loadMore());

  void (async () => {
    try {
      docs = await listDocuments();
      for (const d of docs) docNames.set(d.id, d.name);
      docFilter.innerHTML =
        `<option value="">All textbooks</option>` +
        docs.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join("");
    } catch {
      // Doc filter stays empty; the list itself still works.
    }
  })();

  void (async () => {
    try {
      const wk = await getWanikaniStatus();
      wkBtn.hidden = !wk.configured;
      wkHasData = (wk.counts?.subjects ?? 0) > 0;
    } catch {
      // No WK affordances; everything else still works.
    }
  })();

  void reload();

  return () => {
    window.clearTimeout(searchTimer);
  };
}
