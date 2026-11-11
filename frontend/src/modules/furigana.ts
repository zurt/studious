// Furigana. Transcriptions and model output carry readings inline as
// 漢字(かな) — the convention every VLM prompt in this app asks for. This
// module turns those annotations into <ruby> and owns the global display
// mode:
//   hidden (default) — readings are veiled; tapping a word reveals it, so
//                      the learner tries the reading before looking
//   shown            — every reading is visible
//   off              — readings are removed, kanji only
// The mode lives on <html data-furigana="…"> and CSS does the rest, so
// changing it never re-renders anything.

export type FuriganaMode = "hidden" | "shown" | "off";

export const FURIGANA_MODES: { mode: FuriganaMode; label: string; title: string }[] = [
  { mode: "hidden", label: "Hide", title: "Readings hidden — tap a word to reveal it (F cycles)" },
  { mode: "shown", label: "Show", title: "Show every reading (F cycles)" },
  { mode: "off", label: "Off", title: "No readings, kanji only (F cycles)" },
];

const MODE_KEY = "studious.furigana.mode";
const DEFAULT_MODE: FuriganaMode = "hidden";

// A reading unit: a run of kanji immediately followed by a hiragana reading
// in half- or full-width parentheses. Katakana-only parentheses are left
// alone — in textbook text those are answer labels like 文(ア), not readings.
const KANJI = "\\u3400-\\u4DBF\\u4E00-\\u9FFF\\uF900-\\uFAFF々〆ヵヶ";
const UNIT_SOURCE = `([${KANJI}]+)[(（]([\\u3041-\\u3096ー]+)[)）]`;

export type FuriganaUnit = { start: number; end: number; base: string; reading: string };

export function furiganaUnits(text: string): FuriganaUnit[] {
  const out: FuriganaUnit[] = [];
  for (const m of text.matchAll(new RegExp(UNIT_SOURCE, "g"))) {
    const start = m.index ?? 0;
    out.push({ start, end: start + m[0].length, base: m[1], reading: m[2] });
  }
  return out;
}

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/**
 * Escaped HTML for `text` with every reading unit as <ruby>. The <rp>
 * parentheses keep the element's text content (and copy/paste) identical to
 * the 漢字(かな) source.
 */
export function furiganaHtml(text: string | null | undefined): string {
  if (!text) return "";
  let html = "";
  let i = 0;
  for (const u of furiganaUnits(text)) {
    html += esc(text.slice(i, u.start));
    html += `<ruby class="furi">${esc(u.base)}<rp>(</rp><rt>${esc(u.reading)}</rt><rp>)</rp></ruby>`;
    i = u.end;
  }
  return html + esc(text.slice(i));
}

/**
 * Widen [start, end) so it never cuts through a reading unit. Spans computed
 * on the raw text (vocab links, the filled-in blank) often cover a word's
 * kanji but not the (かな) after it; widening keeps each unit whole so it can
 * still render as ruby inside the span.
 */
export function snapToUnits(units: FuriganaUnit[], start: number, end: number): [number, number] {
  for (const u of units) {
    if (start > u.start && start < u.end) start = u.start;
    if (end > u.start && end < u.end) end = u.end;
  }
  return [start, end];
}

/**
 * Convert reading units inside already-rendered HTML (e.g. markdown) in
 * place. Code blocks and existing ruby are left alone; a unit split across
 * elements (e.g. **漢字**(かな)) stays as plain text.
 */
export function applyFurigana(root: HTMLElement): void {
  const test = new RegExp(UNIT_SOURCE);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || parent.closest("ruby, code, pre, script, style, textarea")) {
        return NodeFilter.FILTER_REJECT;
      }
      return test.test(node.nodeValue || "") ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    const tpl = document.createElement("template");
    tpl.innerHTML = furiganaHtml(node.nodeValue);
    node.replaceWith(tpl.content);
  }
}

// ---------- display mode ----------

export function getFuriganaMode(): FuriganaMode {
  try {
    const v = localStorage.getItem(MODE_KEY);
    if (v === "hidden" || v === "shown" || v === "off") return v;
  } catch {
    // storage unavailable — fall through to the default
  }
  return DEFAULT_MODE;
}

export function setFuriganaMode(mode: FuriganaMode): void {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    // the mode still applies for this page view
  }
  document.documentElement.dataset.furigana = mode;
  document.querySelectorAll<HTMLElement>(".furigana-toggle").forEach(syncToggle);
}

export function cycleFuriganaMode(): FuriganaMode {
  const order = FURIGANA_MODES.map((m) => m.mode);
  const next = order[(order.indexOf(getFuriganaMode()) + 1) % order.length];
  setFuriganaMode(next);
  return next;
}

function syncToggle(group: HTMLElement): void {
  const mode = getFuriganaMode();
  group.querySelectorAll<HTMLButtonElement>("[data-furigana-mode]").forEach((btn) => {
    const on = btn.dataset.furiganaMode === mode;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", String(on));
  });
}

/** Segmented Hide / Show / Off control (styled like the text-size toggle). */
export function createFuriganaToggle(): HTMLElement {
  const group = document.createElement("span");
  group.className = "text-size-toggle furigana-toggle";
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", "Furigana");
  group.title = "Furigana";
  for (const { mode, label, title } of FURIGANA_MODES) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "icon-btn text-size-btn furigana-mode-btn";
    btn.dataset.furiganaMode = mode;
    btn.textContent = label;
    btn.title = title;
    btn.setAttribute("aria-label", title);
    // Toggles sit in collapsible pane headers; keep the click from also
    // collapsing the pane.
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      setFuriganaMode(mode);
    });
    group.appendChild(btn);
  }
  syncToggle(group);
  return group;
}

let initialized = false;

/**
 * Apply the saved mode and install the tap-to-reveal handler. A tap on a
 * veiled word (or on any `.furi-reveal` element, such as an example's kana
 * line) toggles just that one. Handlers that stop propagation — vocab links,
 * whose popover already shows the reading — keep their own behavior.
 */
export function initFurigana(): void {
  document.documentElement.dataset.furigana = getFuriganaMode();
  if (initialized) return;
  initialized = true;
  document.addEventListener("click", (e) => {
    if (document.documentElement.dataset.furigana !== "hidden") return;
    const el = (e.target as HTMLElement | null)?.closest?.("ruby.furi, .furi-reveal");
    if (el) el.classList.toggle("is-revealed");
  });
}
