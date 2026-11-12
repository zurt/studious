import {
  listStoreItems,
  createStoreItem,
  patchStoreItem,
  deleteStoreItem,
  mergeStoreItems,
  getStoreStats,
  runStoreBackfill,
  listDocuments,
  listChapters,
  getWanikaniStatus,
  syncWanikani,
  syncAnki,
  getVocabWanikani,
  previewAnkiPush,
  generateExamples,
  deleteVocabExample,
  sendAnkiPush,
  getTtsStatus,
  vocabAudioUrl,
  type Chapter,
  type DocMeta,
  type GrammarItem,
  type ShortlistReason,
  type ShortlistSummary,
  type StoreItem,
  type StoreKind,
  type StoreListParams,
  type StoreStatus,
  type VocabItem,
  type WkDrilldown,
  type WkSubjectView,
} from "../api";
import { chooseDialog, confirmDialog } from "../modules/confirm";
import { ankiPushDialog, pushResultMessage } from "../modules/anki-push-dialog";
import { ankiFuriganaHtml } from "../modules/furigana";
import { emit, STORE_STATUS_CHANGED, type StoreStatusChange } from "../modules/events";
import { toastError, toastInfo } from "../modules/toast";
import { info, error as logError } from "../logger";
import { navigate, replaceQuery } from "../router";
import { escapeHtml } from "../modules/html";

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
  chapterId: string;
  source: string;
  anki: string;
  sort: "recent" | "updated" | "alpha" | "priority" | "frequency";
  /** Vocab only: show the proposed chapter shortlist. */
  shortlist: boolean;
  /** Vocab only: reviewing the items hidden for this reason (implies shortlist). */
  excluded: ShortlistReason | "";
  summary: ShortlistSummary | null;
  items: StoreItem[];
  total: number;
  expanded: Set<string>;
  selected: Set<string>;
  editing: Set<string>;
};

export function mountVocabDashboard(_params: Record<string, string>, container: HTMLElement) {
  mountStudyDashboard("vocab", container);
}

export function mountGrammarDashboard(_params: Record<string, string>, container: HTMLElement) {
  mountStudyDashboard("grammar", container);
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

// jpost errors look like `/url: 503 {"detail":"..."}`; show just the detail.
export function ankiErrorDetail(message: string): string {
  const m = message.match(/\{.*\}\s*$/s);
  if (m) {
    try {
      const d = JSON.parse(m[0]).detail;
      if (typeof d === "string") return d;
    } catch {
      // fall through to the raw message
    }
  }
  return message;
}

/** Title for the "Send to Anki…" button: why it is disabled, or what it does. */
export function sendToAnkiTitle(docId: string, chapterId: string, candidates: number): string {
  if (!docId || !chapterId) return "Pick a textbook and a specific chapter to send its shortlist to Anki";
  if (candidates === 0) return "No candidates to send";
  return "Add this chapter's shortlist words to the Studious deck in Anki";
}

export function ankiBadge(item: StoreItem): string {
  const a = (item as VocabItem).anki;
  if (!a) return "";
  const note =
    a.match === "headword"
      ? "matched on spelling only, reading differs"
      : a.match === "stem"
        ? `matched the same word with or without する/な · ${a.deck}`
        : a.match === "entry"
        ? `matched by dictionary entry (different spelling) · ${a.deck}`
        : `${a.deck}`;
  const mark = a.match === "exact" ? "" : "~";
  return `<span class="study-badge study-badge-anki study-badge-anki-${a.state}" title="${escapeHtml(note)}">Anki · ${a.state}${mark}</span>`;
}

export function wkBurnedBadge(item: StoreItem): string {
  if (!(item as VocabItem).wk_burned) return "";
  return `<span class="study-badge study-badge-wk" title="Burned in WaniKani">WK burned</span>`;
}

/** Words per chapter the owner studies; rows beyond it are marked as over budget. */
export const SHORTLIST_BUDGET = 125;

export const SHORTLIST_REASONS: ShortlistReason[] = [
  "in_anki",
  "basic",
  "grammar_like",
  "not_dictionary",
  "status_known",
  "status_ignored",
];

export const SHORTLIST_REASON_LABELS: Record<ShortlistReason, string> = {
  in_anki: "in Anki",
  basic: "basic",
  grammar_like: "grammar-like",
  not_dictionary: "not in dictionary",
  status_known: "known",
  status_ignored: "ignored",
};

/** Summary line: "142 candidates · hidden: 310 in Anki · 96 basic …". Zero counts are
 * omitted; each hidden count is a button that switches to the excluded=<reason> list. */
export function shortlistSummaryHtml(total: number, summary: ShortlistSummary): string {
  const hidden = SHORTLIST_REASONS.filter((r) => (summary.excluded[r] ?? 0) > 0)
    .map(
      (r) =>
        `<button class="study-stat-chip" data-excluded="${r}" title="Show the ${SHORTLIST_REASON_LABELS[r]} words hidden from the shortlist">${summary.excluded[r]} ${SHORTLIST_REASON_LABELS[r]}</button>`,
    )
    .join(" · ");
  const head = `${total} ${total === 1 ? "candidate" : "candidates"}`;
  return hidden ? `${head} · hidden: ${hidden}` : head;
}

/** Line shown while reviewing one hidden group, with the way back. */
export function excludedLineHtml(total: number, reason: ShortlistReason): string {
  return `Hidden, ${SHORTLIST_REASON_LABELS[reason]}: ${total} · <button class="study-stat-chip" data-back-to-shortlist>Back to shortlist</button>`;
}

/** Items with the budget divider spliced in after the first `budget` rows. No divider
 * when everything fits or the shortlist is off; rebuilt from scratch on each render, so
 * loading more pages can never duplicate or misplace it. */
export function rowsWithBudgetDivider<T>(
  items: T[],
  enabled: boolean,
  budget = SHORTLIST_BUDGET,
): (T | "divider")[] {
  if (!enabled || items.length <= budget) return [...items];
  return [...items.slice(0, budget), "divider", ...items.slice(budget)];
}

type ListParamState = Pick<
  State,
  "kind" | "status" | "q" | "docId" | "chapterId" | "source" | "anki" | "sort" | "shortlist" | "excluded"
>;

/** Request parameters for the current filters. The shortlist has its own order, so it
 * sends no sort; reviewing a hidden group sends excluded= and keeps the normal sort. */
export function storeListParams(state: ListParamState, offset = 0): StoreListParams {
  const vocab = state.kind === "vocab";
  const shortlistOn = vocab && state.shortlist && !state.excluded;
  return {
    status: (state.status || undefined) as StoreStatus | undefined,
    q: state.q || undefined,
    doc_id: state.docId || undefined,
    chapter_id: state.chapterId || undefined,
    source: state.source || undefined,
    anki: state.anki || undefined,
    shortlist: shortlistOn ? true : undefined,
    excluded: vocab && state.excluded ? state.excluded : undefined,
    sort: shortlistOn ? undefined : state.sort,
    limit: PAGE_SIZE,
    offset,
  };
}

/** "1 item" / "N items" for the list header. */
export function countLabel(total: number): string {
  return `${total} ${total === 1 ? "item" : "items"}`;
}

/** Compact frequency rank: 1 -> "#1", 1234 -> "#1.2k", 25000 -> "#25k". */
export function formatFreqRank(rank: number): string {
  if (rank < 1000) return `#${rank}`;
  const k = rank / 1000;
  return `#${k < 10 ? k.toFixed(1).replace(/\.0$/, "") : Math.round(k)}k`;
}

export function freqBadge(item: StoreItem): string {
  const rank = item.classifications?.freq_rank;
  if (typeof rank !== "number" || rank < 1) return "";
  return `<span class="study-badge study-badge-freq" title="Frequency rank ${rank} (JPDB corpus)">${formatFreqRank(rank)}</span>`;
}

/** <option> list for the chapter filter: chapters in their defined order. */
export function chapterOptions(chapters: Chapter[]): string {
  const sorted = [...chapters].sort((a, b) => a.order - b.order);
  return (
    `<option value="">All chapters</option>` +
    sorted.map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.title)}</option>`).join("")
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
    chapterId: query.get("chapter") || "",
    source: "",
    anki: "",
    sort: "recent",
    shortlist: false,
    excluded: "",
    summary: null,
    items: [],
    total: 0,
    expanded: new Set(),
    selected: new Set(),
    editing: new Set(),
  };
  if (state.status && !STATUSES.includes(state.status as StoreStatus)) state.status = "";
  if (kind === "vocab") {
    const excludedParam = query.get("excluded") as ShortlistReason | null;
    if (excludedParam && SHORTLIST_REASONS.includes(excludedParam)) state.excluded = excludedParam;
    state.shortlist = query.get("shortlist") === "1" || !!state.excluded;
  }

  const title = kind === "vocab" ? "Vocabulary" : "Grammar";
  container.innerHTML = `
    <div class="study-dash">
      <div class="row study-dash-header">
        <h2 style="margin:0">${title}</h2>
        <div id="study-stats" class="study-stats"></div>
        <div class="grow"></div>
        <button id="study-add-btn" title="Add an entry by hand">+ Add</button>
        <button id="study-backfill-btn" title="Re-harvest all breakdowns and vocab lists on disk">Backfill</button>
        <button id="study-anki-btn" title="Import card state from Anki (read-only; Anki must be open with AnkiConnect)">Sync Anki</button>
        <button id="study-wk-btn" hidden title="Sync WaniKani levels, mnemonics, and your notes">Sync WK</button>
      </div>
      <form id="study-add-form" class="study-add-form" hidden></form>
      <div class="row study-filters">
        <input id="study-search" type="search" placeholder="Search ${kind === "vocab" ? "word, reading, meaning" : "pattern, explanation"}…" value="${escapeHtml(state.q)}" />
        <select id="study-doc-filter"><option value="">All textbooks</option></select>
        <select id="study-chapter-filter" title="Pick a textbook first" disabled><option value="">All chapters</option></select>
        <select id="study-source-filter">
          <option value="">All sources</option>
          <option value="vocab_list">Vocab lists</option>
          <option value="breakdown">Breakdowns</option>
          <option value="manual">Manual</option>
        </select>
        ${
          kind === "vocab"
            ? `<select id="study-anki-filter" title="Filter by Anki card state">
          <option value="">Any Anki state</option>
          <option value="any">In Anki</option>
          <option value="none">Not in Anki</option>
          <option value="mature">Anki: mature</option>
          <option value="young">Anki: young</option>
          <option value="learning">Anki: learning</option>
          <option value="new">Anki: new</option>
          <option value="suspended">Anki: suspended</option>
        </select>`
            : ""
        }
        ${
          kind === "vocab"
            ? `<button id="study-shortlist-toggle" class="study-stat-chip" aria-pressed="false" title="Propose a study shortlist: hide words already in Anki, basic, grammar-like or known">Shortlist</button>`
            : ""
        }
        <select id="study-sort">
          <option value="recent">Newest</option>
          <option value="updated">Recently updated</option>
          <option value="alpha">${kind === "vocab" ? "By reading" : "By pattern"}</option>
          ${kind === "vocab" ? `<option value="priority">By study priority</option><option value="frequency">By frequency</option><option value="shortlist" hidden>Shortlist order</option>` : ""}
        </select>
        <span id="study-count" class="study-bulk-label" aria-live="polite"></span>
      </div>
      <div id="study-shortlist-line" class="study-bulk-label study-shortlist-line" hidden></div>
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
  const chapterFilter = container.querySelector<HTMLSelectElement>("#study-chapter-filter")!;
  const countEl = container.querySelector<HTMLElement>("#study-count")!;
  const sourceFilter = container.querySelector<HTMLSelectElement>("#study-source-filter")!;
  const sortSelect = container.querySelector<HTMLSelectElement>("#study-sort")!;
  const addBtn = container.querySelector<HTMLButtonElement>("#study-add-btn")!;
  const addForm = container.querySelector<HTMLFormElement>("#study-add-form")!;
  const backfillBtn = container.querySelector<HTMLButtonElement>("#study-backfill-btn")!;
  const ankiBtn = container.querySelector<HTMLButtonElement>("#study-anki-btn")!;
  const ankiFilter = container.querySelector<HTMLSelectElement>("#study-anki-filter");
  const wkBtn = container.querySelector<HTMLButtonElement>("#study-wk-btn")!;
  const shortlistToggle = container.querySelector<HTMLButtonElement>("#study-shortlist-toggle");
  const shortlistLine = container.querySelector<HTMLElement>("#study-shortlist-line")!;

  let docs: DocMeta[] = [];
  const docNames = new Map<string, string>();
  let wkHasData = false;

  function params(offset = 0): StoreListParams {
    return storeListParams(state, offset);
  }

  /** The shortlist's own review actions (Know it / Skip) apply to the shortlist itself. */
  const inShortlist = () => state.kind === "vocab" && state.shortlist && !state.excluded;

  function renderShortlistLine() {
    const on = state.kind === "vocab" && state.shortlist;
    shortlistToggle?.classList.toggle("active", on);
    shortlistToggle?.setAttribute("aria-pressed", String(on));
    // The shortlist has its own order: say so in the control instead of
    // leaving a dead select that still reads "Newest".
    sortSelect.disabled = inShortlist();
    sortSelect.value = inShortlist() ? "shortlist" : state.sort;
    sortSelect.title = inShortlist() ? "The shortlist is ordered by frequency, with the chapter's vocab-list words first. Turn Shortlist off to sort." : "";
    shortlistLine.hidden = !on;
    if (!on) return;
    if (state.excluded) {
      shortlistLine.innerHTML = excludedLineHtml(state.total, state.excluded);
    } else if (state.summary) {
      shortlistLine.innerHTML = shortlistSummaryHtml(state.total, state.summary);
    } else {
      shortlistLine.textContent = "";
    }
    if (!state.excluded) {
      const send = document.createElement("button");
      send.className = "study-stat-chip";
      send.id = "study-anki-push-btn";
      send.textContent = "Send to Anki…";
      send.disabled = !state.docId || !state.chapterId || state.total === 0;
      send.title = sendToAnkiTitle(state.docId, state.chapterId, state.total);
      send.addEventListener("click", () => void sendToAnki(send));
      shortlistLine.append(" · ", send);
    }
    shortlistLine.querySelectorAll<HTMLButtonElement>("[data-excluded]").forEach((btn) => {
      btn.addEventListener("click", () => setShortlist(true, btn.dataset.excluded as ShortlistReason));
    });
    shortlistLine.querySelector("[data-back-to-shortlist]")?.addEventListener("click", () =>
      setShortlist(true, ""),
    );
  }

  async function sendToAnki(btn: HTMLButtonElement) {
    const docId = state.docId;
    const chapterId = state.chapterId;
    btn.disabled = true;
    try {
      const first = await previewAnkiPush(docId, chapterId, SHORTLIST_BUDGET);
      const choice = await ankiPushDialog(
        first,
        state.total,
        SHORTLIST_BUDGET,
        (n) => previewAnkiPush(docId, chapterId, n),
        async (ids) => {
          try {
            return await generateExamples(ids, false, { docId, chapterId });
          } catch (e: any) {
            logError("StudyDash", "examples_failed", { error: e.message });
            throw new Error(ankiErrorDetail(e.message));
          }
        },
      );
      if (choice === null) return;
      const result = await sendAnkiPush(docId, chapterId, choice.limit, choice.audio);
      info("StudyDash", "anki_push_done", { created: result.created, failed: result.failed.length });
      (result.failed.length || !result.sync_ok ? toastError : toastInfo)(pushResultMessage(result));
      await reload();
    } catch (e: any) {
      logError("StudyDash", "anki_push_failed", { error: e.message });
      toastError("Send to Anki failed: " + ankiErrorDetail(e.message));
    } finally {
      btn.disabled = false;
    }
  }

  function setShortlist(on: boolean, excluded: ShortlistReason | "") {
    state.shortlist = on;
    state.excluded = on ? excluded : "";
    state.summary = null;
    replaceQuery({ shortlist: on ? "1" : null, excluded: state.excluded || null });
    void reload();
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
      state.summary = res.shortlist ?? null;
      state.selected.clear();
      state.editing.clear();
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
    countEl.textContent = countLabel(state.total);
    moreBtn.hidden = state.items.length >= state.total;
    renderShortlistLine();
    renderBulkBar();
    if (state.items.length === 0) {
      const filtered =
        state.status || state.q || state.docId || state.chapterId || state.source || state.shortlist;
      listEl.innerHTML = filtered
        ? `<p class="empty">No ${state.kind} items match the current filters.</p>`
        : `<p class="empty">Nothing here yet. Items are harvested automatically when you
           transcribe vocab lists or generate sentence breakdowns — or click
           <strong>Backfill</strong> to harvest everything already on disk.</p>`;
      return;
    }
    listEl.innerHTML = "";
    for (const entry of rowsWithBudgetDivider(state.items, inShortlist())) {
      if (entry === "divider") {
        const divider = document.createElement("div");
        divider.className = "study-budget-divider";
        divider.textContent = `Budget: ${SHORTLIST_BUDGET} words. Everything below is beyond this chapter's budget.`;
        listEl.appendChild(divider);
      } else {
        listEl.appendChild(renderRow(entry));
      }
    }
  }

  /** One-tap review from the shortlist (Know it / Skip) or from a hidden group (Restore):
   * the row leaves the list and the summary counts follow locally, no refetch. */
  async function reviewItem(item: StoreItem, status: StoreStatus, btn: HTMLButtonElement) {
    btn.disabled = true;
    try {
      await patchStoreItem(state.kind, item.id, { status });
      emit<StoreStatusChange>(STORE_STATUS_CHANGED, { kind: state.kind, id: item.id, status });
      state.items = state.items.filter((i) => i.id !== item.id);
      state.total -= 1;
      const summary = state.summary;
      if (summary && inShortlist()) {
        const key: ShortlistReason = status === "known" ? "status_known" : "status_ignored";
        summary.excluded[key] = (summary.excluded[key] ?? 0) + 1;
        if ((item as VocabItem).wk_burned) summary.wk_burned = Math.max(0, summary.wk_burned - 1);
      }
      render();
      void refreshStats();
    } catch (e: any) {
      btn.disabled = false;
      logError("StudyDash", "review_failed", { item_id: item.id, error: e.message });
      toastError("Update failed: " + e.message);
    }
  }

  function renderBulkBar() {
    const selCount = state.selected.size;
    const showInbox = state.status === "unreviewed" && state.items.length > 0;
    bulkBar.hidden = !selCount && !showInbox;
    if (bulkBar.hidden) return;
    if (selCount) {
      bulkBar.innerHTML = `
        <span class="study-bulk-label">${selCount} selected</span>
        ${STATUSES.map((s) => `<button data-bulk-sel="${s}">${STATUS_LABELS[s]}</button>`).join("")}
        <button data-bulk-merge ${selCount < 2 ? "disabled" : ""} title="Merge duplicates into one entry">Merge…</button>
        <div class="grow"></div>
        <button data-bulk-clear>Clear</button>
      `;
      bulkBar.querySelectorAll<HTMLButtonElement>("[data-bulk-sel]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const targets = state.items.filter((i) => state.selected.has(i.id));
          void bulkSet(btn.dataset.bulkSel as StoreStatus, btn, targets, false);
        });
      });
      bulkBar.querySelector<HTMLButtonElement>("[data-bulk-merge]")!
        .addEventListener("click", () => void mergeSelected());
      bulkBar.querySelector<HTMLButtonElement>("[data-bulk-clear]")!
        .addEventListener("click", () => {
          state.selected.clear();
          render();
        });
      return;
    }
    bulkBar.innerHTML = `
      <span class="study-bulk-label">${state.items.length} shown</span>
      <button data-bulk="active">Accept all shown</button>
      <button data-bulk="ignored">Ignore all shown</button>
    `;
    bulkBar.querySelectorAll<HTMLButtonElement>("[data-bulk]").forEach((btn) => {
      btn.addEventListener("click", () =>
        void bulkSet(btn.dataset.bulk as StoreStatus, btn, [...state.items], true));
    });
  }

  async function bulkSet(
    status: StoreStatus,
    btn: HTMLButtonElement,
    targets: StoreItem[],
    confirm: boolean,
  ) {
    if (confirm) {
      const ok = await confirmDialog(
        status === "ignored" ? "Ignore all shown?" : "Accept all shown?",
        `Set ${targets.length} shown item(s) to "${STATUS_LABELS[status]}"?`,
        STATUS_LABELS[status],
      );
      if (!ok) return;
    }
    btn.disabled = true;
    let failures = 0;
    for (const item of targets) {
      try {
        await patchStoreItem(state.kind, item.id, { status });
        emit<StoreStatusChange>(STORE_STATUS_CHANGED, { kind: state.kind, id: item.id, status });
      } catch {
        failures += 1;
      }
    }
    info("StudyDash", "bulk_status", { kind: state.kind, status, count: targets.length, failures });
    if (failures) toastError(`${failures} item(s) failed to update`);
    await reload();
  }

  async function mergeSelected() {
    const targets = state.items.filter((i) => state.selected.has(i.id));
    if (targets.length < 2) return;
    const canonicalId = await chooseDialog(
      "Merge duplicates",
      "The other entries fold into the one you keep: sightings and spellings are " +
        "combined, and its word, meaning, and status win.",
      targets.map((item) => ({
        value: item.id,
        label: isVocab(item)
          ? `${item.headword}${item.reading && item.reading !== item.headword ? `（${item.reading}）` : ""} — ${item.meaning}`
          : `${item.pattern} — ${(item as GrammarItem).explanation}`,
        hint: `${item.sightings.length} sighting(s) · ${STATUS_LABELS[item.status]}`,
      })),
      "Merge",
    );
    if (!canonicalId) return;
    let merged = 0;
    try {
      for (const item of targets) {
        if (item.id === canonicalId) continue;
        await mergeStoreItems(state.kind, canonicalId, item.id);
        merged += 1;
      }
      info("StudyDash", "merge_done", { kind: state.kind, canonical: canonicalId, merged });
      toastInfo(`Merged ${merged} duplicate(s)`);
    } catch (e: any) {
      logError("StudyDash", "merge_failed", { kind: state.kind, error: e.message });
      toastError(`Merge failed after ${merged} item(s): ` + e.message);
    }
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
        <input type="checkbox" class="study-select" aria-label="Select entry" ${inShortlist() ? "hidden" : ""} ${state.selected.has(item.id) ? "checked" : ""} />
        <span class="study-term" lang="ja">${escapeHtml(term)}</span>
        ${sub && sub !== term ? `<span class="study-reading" lang="ja">${escapeHtml(sub)}</span>` : ""}
        <span class="study-gloss">${escapeHtml(gloss)}</span>
        <div class="grow"></div>
        ${classChips}
        ${wkBurnedBadge(item)}
        ${freqBadge(item)}
        ${ankiBadge(item)}
        ${sources.map((s) => `<span class="study-badge study-badge-${s}">${s.replace("_", " ")}</span>`).join("")}
        <button class="study-sightings-btn" title="Details, sightings, kanji breakdown">${sightingCount ? `${sightingCount}×` : "…"}</button>
        ${
          inShortlist()
            ? `<span class="study-review-actions"><button class="study-review-btn" data-review="known" title="Mark as known; it leaves the shortlist">Know it</button><button class="study-review-btn" data-review="ignored" title="Ignore; it leaves the shortlist">Skip</button></span>`
            : state.kind === "vocab" && (state.excluded === "status_known" || state.excluded === "status_ignored")
              ? `<span class="study-review-actions"><button class="study-review-btn" data-review="unreviewed" title="Put it back in the inbox">Restore</button></span>`
              : ""
        }
        <div class="study-status-toggle" ${inShortlist() ? "hidden" : ""}>
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
    row.querySelector<HTMLInputElement>(".study-select")!.addEventListener("change", (e) => {
      const checked = (e.target as HTMLInputElement).checked;
      if (checked) state.selected.add(item.id);
      else state.selected.delete(item.id);
      renderBulkBar();
    });
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

    row.querySelectorAll<HTMLButtonElement>(".study-review-btn").forEach((btn) => {
      btn.addEventListener("click", () =>
        void reviewItem(item, btn.dataset.review as StoreStatus, btn));
    });

    row.querySelectorAll<HTMLButtonElement>(".study-status-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const status = btn.dataset.status as StoreStatus;
        if (status === item.status) return;
        try {
          const updated = await patchStoreItem(state.kind, item.id, { status });
          Object.assign(item, updated);
          emit<StoreStatusChange>(STORE_STATUS_CHANGED, { kind: state.kind, id: item.id, status });
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
    if (state.editing.has(item.id)) {
      renderEditForm(item, detail);
      return;
    }
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
    const variants = (isVocab(item) && item.surface_variants?.length)
      ? `<span class="study-variants">also: ${item.surface_variants.map((v) => `<span lang="ja">${escapeHtml(v)}</span>`).join("、")}</span>`
      : "";
    detail.innerHTML = `
      <div class="row study-detail-head">
        ${links ? `<div class="row study-links">${links}</div>` : ""}
        ${variants}
        <div class="grow"></div>
        <button class="study-edit-btn" title="Edit fields and notes">Edit</button>
      </div>
      ${isVocab(item) && item.meaning_context && item.meaning_context !== item.meaning ? `<div class="study-context">In the textbook: <span lang="en">${escapeHtml(item.meaning_context)}</span></div>` : ""}
      ${item.notes ? `<div class="study-notes">${escapeHtml(item.notes)}</div>` : ""}
      ${isVocab(item) ? `<div class="study-example"></div><div class="study-audio" hidden></div>` : ""}
      ${sightings || `<p class="empty">No sightings.</p>`}
      <div class="study-wk" hidden></div>
    `;
    const exampleEl = detail.querySelector<HTMLElement>(".study-example");
    if (exampleEl && isVocab(item)) renderExample(item, exampleEl);
    const audioEl = detail.querySelector<HTMLElement>(".study-audio");
    if (audioEl && isVocab(item)) void renderAudio(item, audioEl);
    detail.querySelector<HTMLButtonElement>(".study-edit-btn")!.addEventListener("click", () => {
      state.editing.add(item.id);
      renderEditForm(item, detail);
    });
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

  let ttsStatus: Promise<{ available: boolean; voice: string }> | null = null;

  /** "Play word" / "Play sentence" buttons, only when the Mac voice is available. */
  async function renderAudio(item: VocabItem, el: HTMLElement) {
    ttsStatus ??= getTtsStatus().catch(() => ({ available: false, voice: "" }));
    const status = await ttsStatus;
    if (!status.available || !el.isConnected) return;
    el.hidden = false;
    el.innerHTML = `
      <button class="study-audio-btn" data-part="word" title="Speak the word with the Mac voice (${escapeHtml(status.voice)})">Play word</button>
      <button class="study-audio-btn" data-part="sentence" title="Speak the example sentence with the Mac voice">Play sentence</button>`;
    el.querySelectorAll<HTMLButtonElement>(".study-audio-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const part = btn.dataset.part as "word" | "sentence";
        btn.disabled = true;
        try {
          const r = await fetch(vocabAudioUrl(item.id, part));
          if (!r.ok) throw new Error(ankiErrorDetail(`${r.status} ${await r.text()}`));
          const url = URL.createObjectURL(await r.blob());
          const audio = new Audio(url);
          audio.addEventListener("ended", () => URL.revokeObjectURL(url));
          await audio.play();
        } catch (e: any) {
          logError("StudyDash", "audio_failed", { item_id: item.id, error: e.message });
          toastError(`Play ${part} failed: ` + e.message);
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  /** The stored example sentence (bold word, ruby readings) with Generate / Regenerate / Remove. */
  function renderExample(item: VocabItem, el: HTMLElement) {
    const ex = item.example;
    el.innerHTML = `
      ${
        ex
          ? `<div class="study-example-label">${ex.source === "textbook" ? "Textbook sentence" : "Generated sentence"}</div>
             <div class="study-example-text" lang="ja">${ankiFuriganaHtml(ex.furigana, ex.surface) || escapeHtml(ex.sentence)}</div>
             <div class="study-example-gloss">${escapeHtml(ex.gloss)}</div>`
          : ""
      }
      <div class="row study-example-actions">
        <button class="study-example-gen" title="${ex ? "Write a new example sentence with the model" : "Write an example sentence with the model (uses API tokens)"}">${ex ? "Regenerate" : "Generate example"}</button>
        ${ex ? `<button class="study-example-remove" title="Remove the stored example sentence">Remove</button>` : ""}
      </div>
    `;
    const gen = el.querySelector<HTMLButtonElement>(".study-example-gen")!;
    const remove = el.querySelector<HTMLButtonElement>(".study-example-remove");
    gen.addEventListener("click", async () => {
      gen.disabled = true;
      if (remove) remove.disabled = true;
      gen.textContent = "Generating\u2026";
      try {
        const res = await generateExamples([item.id], !!ex, { docId: state.docId, chapterId: state.chapterId });
        const r = res.items[0];
        if (r?.example) {
          item.example = r.example;
        } else {
          toastError("No example generated: " + (r?.reason ?? "unknown reason"));
        }
      } catch (e: any) {
        logError("StudyDash", "example_failed", { item_id: item.id, error: e.message });
        toastError("Generate example failed: " + ankiErrorDetail(e.message));
      }
      renderExample(item, el);
    });
    remove?.addEventListener("click", async () => {
      gen.disabled = true;
      remove.disabled = true;
      try {
        await deleteVocabExample(item.id);
        item.example = null;
      } catch (e: any) {
        logError("StudyDash", "example_remove_failed", { item_id: item.id, error: e.message });
        toastError("Remove failed: " + e.message);
      }
      renderExample(item, el);
    });
  }

  function renderEditForm(item: StoreItem, detail: HTMLElement) {
    const fields = isVocab(item)
      ? [
          { name: "headword", label: "Word", value: item.headword, ja: true },
          { name: "reading", label: "Reading", value: item.reading, ja: true },
          { name: "meaning", label: "Meaning", value: item.meaning, ja: false },
        ]
      : [
          { name: "pattern", label: "Pattern", value: item.pattern, ja: true },
          { name: "explanation", label: "Explanation", value: (item as GrammarItem).explanation, ja: false },
        ];
    const form = document.createElement("form");
    form.className = "study-edit-form";
    form.innerHTML = `
      ${fields
        .map(
          (f) => `
        <label class="study-edit-field">
          <span>${f.label}</span>
          <input name="${f.name}" value="${escapeHtml(f.value)}" ${f.ja ? 'lang="ja"' : ""} ${f.name === "headword" || f.name === "pattern" ? "required" : ""} />
        </label>`,
        )
        .join("")}
      <label class="study-edit-field">
        <span>Notes</span>
        <textarea name="notes" rows="2" placeholder="Your own notes…"></textarea>
      </label>
      <div class="row">
        <div class="grow"></div>
        <button type="button" class="study-edit-cancel">Cancel</button>
        <button type="submit">Save</button>
      </div>
    `;
    form.querySelector<HTMLTextAreaElement>("textarea[name=notes]")!.value = item.notes || "";
    detail.innerHTML = "";
    detail.appendChild(form);

    form.querySelector<HTMLButtonElement>(".study-edit-cancel")!.addEventListener("click", () => {
      state.editing.delete(item.id);
      renderDetail(item, detail);
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(form).entries()) as Record<string, string>;
      const changes: Record<string, string> = {};
      for (const [key, value] of Object.entries(data)) {
        if ((item as any)[key] !== value) changes[key] = value;
      }
      if (!Object.keys(changes).length) {
        state.editing.delete(item.id);
        renderDetail(item, detail);
        return;
      }
      try {
        const updated = await patchStoreItem(state.kind, item.id, changes);
        Object.assign(item, updated);
        state.editing.delete(item.id);
        toastInfo("Saved");
        const row = detail.closest(".study-row");
        if (row) row.replaceWith(renderRow(item));
        void refreshStats();
      } catch (err: any) {
        logError("StudyDash", "edit_failed", { item_id: item.id, error: err.message });
        toastError("Save failed: " + err.message);
      }
    });
    form.querySelector<HTMLInputElement>("input")!.focus();
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

  ankiBtn.addEventListener("click", async () => {
    ankiBtn.disabled = true;
    ankiBtn.textContent = "Syncing Anki…";
    try {
      const result = await syncAnki();
      info("StudyDash", "anki_sync_done", { cards: result.total_cards, matched: result.matched });
      toastInfo(`Anki synced: ${result.total_cards} cards, ${result.matched} of your store items matched`);
      await reload();
    } catch (e: any) {
      logError("StudyDash", "anki_sync_failed", { error: e.message });
      toastError("Anki sync failed: " + ankiErrorDetail(e.message));
    } finally {
      ankiBtn.disabled = false;
      ankiBtn.textContent = "Sync Anki";
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

  // Chapter select: disabled until a textbook is chosen; a textbook change
  // resets it. A ?chapter= deep link (coverage view) has no textbook, so it
  // shows as a single "Linked chapter" option until the user changes it.
  let chapterReq = 0;
  async function loadChapters(docId: string) {
    const req = ++chapterReq;
    state.chapterId = "";
    chapterFilter.disabled = true;
    chapterFilter.innerHTML = `<option value="">All chapters</option>`;
    chapterFilter.title = "Pick a textbook first";
    if (!docId) return;
    try {
      const chapters = await listChapters(docId);
      if (req !== chapterReq) return;
      chapterFilter.innerHTML = chapterOptions(chapters);
      chapterFilter.disabled = false;
      chapterFilter.title = "Filter by chapter";
    } catch (e: any) {
      logError("StudyDash", "chapters_failed", { error: e.message });
    }
  }
  if (state.chapterId) {
    chapterFilter.innerHTML = `<option value="">All chapters</option><option value="${escapeHtml(state.chapterId)}" selected>Linked chapter</option>`;
    chapterFilter.value = state.chapterId;
    chapterFilter.disabled = false;
    chapterFilter.title = "Showing only items sighted in one chapter";
  }
  docFilter.addEventListener("change", () => {
    state.docId = docFilter.value;
    if (state.chapterId) replaceQuery({ chapter: null });
    void loadChapters(state.docId);
    void reload();
  });
  chapterFilter.addEventListener("change", () => {
    state.chapterId = chapterFilter.value;
    replaceQuery({ chapter: state.chapterId || null });
    void reload();
  });
  ankiFilter?.addEventListener("change", () => {
    state.anki = ankiFilter.value;
    void reload();
  });

  shortlistToggle?.addEventListener("click", () => setShortlist(!state.shortlist, ""));

  sourceFilter.addEventListener("change", () => {
    state.source = sourceFilter.value;
    void reload();
  });
  sortSelect.addEventListener("change", () => {
    // "shortlist" is a label for the disabled state, not a real sort; some
    // browsers still list a hidden <option>.
    if (sortSelect.value === "shortlist") {
      sortSelect.value = state.sort;
      return;
    }
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
