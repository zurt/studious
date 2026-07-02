import {
  getStudyQueue,
  postStudyReview,
  type StudyCard,
  type StudyGrade,
  type StudyQueue,
} from "../api";
import { isTypingTarget } from "../modules/shortcuts-help";
import { toastError } from "../modules/toast";
import { info, error as logError } from "../logger";
import { navigate } from "../router";

const QUEUE_LIMIT = 20;
const NEW_LIMIT = 10;

const GRADES: { grade: StudyGrade; key: string; label: string; hint: string }[] = [
  { grade: 1, key: "1", label: "Again", hint: "forgot — see it again shortly" },
  { grade: 2, key: "2", label: "Hard", hint: "barely recalled" },
  { grade: 3, key: "3", label: "Good", hint: "recalled with effort" },
  { grade: 4, key: "4", label: "Easy", hint: "instant recall" },
];

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Highlight the sighted surface form inside the sentence for context cards.
function sentenceFront(card: StudyCard): string {
  const text = card.sighting?.sentence_text || "";
  const surface = card.sighting?.surface || "";
  const safe = escapeHtml(text);
  if (!surface || !text.includes(surface)) return safe;
  return safe.replace(escapeHtml(surface), `<mark class="srs-surface">${escapeHtml(surface)}</mark>`);
}

function cardFront(card: StudyCard): string {
  if (card.card_type === "context") {
    return `<div class="srs-sentence" lang="ja">${sentenceFront(card)}</div>
            <div class="srs-front-hint">What does the marked word mean?</div>`;
  }
  if (card.card_type === "pattern") {
    return `<div class="srs-term" lang="ja">${escapeHtml(card.item.pattern || "")}</div>`;
  }
  return `<div class="srs-term" lang="ja">${escapeHtml(card.item.headword || "")}</div>`;
}

function cardBack(card: StudyCard): string {
  const it = card.item;
  if (card.kind === "grammar") {
    const example = card.sighting?.sentence_text
      ? `<div class="srs-example" lang="ja">${escapeHtml(card.sighting.sentence_text)}</div>`
      : "";
    return `
      <div class="srs-term" lang="ja">${escapeHtml(it.pattern || "")}</div>
      <div class="srs-meaning">${escapeHtml(it.explanation || "")}</div>
      ${example}
      ${it.notes ? `<div class="srs-notes">${escapeHtml(it.notes)}</div>` : ""}`;
  }
  const reading =
    it.reading && it.reading !== it.headword
      ? `<div class="srs-reading" lang="ja">${escapeHtml(it.reading)}</div>`
      : "";
  // A context card asks about the marked word, so its back leads with the word itself.
  const headword =
    card.card_type === "context"
      ? `<div class="srs-term srs-term-small" lang="ja">${escapeHtml(it.headword || "")}</div>`
      : "";
  const links = Object.entries(it.links || {})
    .map(
      ([name, url]) =>
        `<a class="study-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(name)} ↗</a>`,
    )
    .join("");
  return `
    ${headword}
    ${reading}
    <div class="srs-meaning">${escapeHtml(it.meaning || "")}</div>
    ${it.pos?.length ? `<div class="srs-pos">${escapeHtml(it.pos.join(" · "))}</div>` : ""}
    ${it.notes ? `<div class="srs-notes">${escapeHtml(it.notes)}</div>` : ""}
    ${links ? `<div class="row srs-links">${links}</div>` : ""}`;
}

export function mountStudySession(_params: Record<string, string>, container: HTMLElement) {
  container.innerHTML = `
    <div class="study-dash srs-session">
      <div class="row study-dash-header">
        <h2 style="margin:0">Study</h2>
        <span id="srs-progress" class="srs-progress"></span>
        <div class="grow"></div>
        <a href="/vocab" id="srs-vocab-link" class="study-link">Manage vocab →</a>
      </div>
      <div id="srs-body" class="srs-body"><p class="empty">Loading queue…</p></div>
    </div>
  `;
  const body = container.querySelector<HTMLElement>("#srs-body")!;
  const progressEl = container.querySelector<HTMLElement>("#srs-progress")!;
  container.querySelector<HTMLAnchorElement>("#srs-vocab-link")!.addEventListener("click", (e) => {
    e.preventDefault();
    navigate("/vocab");
  });

  let cards: StudyCard[] = [];
  let counts: StudyQueue["counts"] = { due: 0, new: 0, active_items: 0 };
  let index = 0;
  let revealed = false;
  let shownAt = 0;
  let reviewed = 0;
  let lapses = 0;
  let submitting = false;

  function updateProgress() {
    progressEl.textContent = cards.length
      ? `${Math.min(index + 1, cards.length)} / ${cards.length}`
      : "";
  }

  function renderEmpty() {
    updateProgress();
    body.innerHTML = counts.active_items
      ? `<p class="empty">All caught up — nothing due right now. 🎉</p>`
      : `<p class="empty">No cards to study yet. Mark words as <strong>Active</strong> on the
         <a href="/vocab" data-nav>vocab dashboard</a> (or grammar patterns on the grammar
         dashboard) and they'll show up here as flashcards.</p>`;
    body.querySelector<HTMLAnchorElement>("[data-nav]")?.addEventListener("click", (e) => {
      e.preventDefault();
      navigate("/vocab");
    });
  }

  function renderDone() {
    updateProgress();
    body.innerHTML = `
      <div class="srs-card srs-done">
        <div class="srs-meaning">Session done: ${reviewed} review(s)${lapses ? `, ${lapses} again` : ""}.</div>
        <div class="row" style="justify-content:center;gap:8px">
          <button id="srs-again-btn">Keep studying</button>
        </div>
      </div>`;
    body.querySelector<HTMLButtonElement>("#srs-again-btn")!.addEventListener("click", () => {
      void loadQueue();
    });
  }

  function renderCard() {
    if (index >= cards.length) {
      renderDone();
      return;
    }
    updateProgress();
    const card = cards[index];
    const badge =
      card.state.reps === 0
        ? `<span class="study-badge srs-badge-new">new</span>`
        : `<span class="study-badge srs-badge-due">due</span>`;
    const typeLabel =
      card.card_type === "context" ? "in context" : card.kind === "grammar" ? "grammar" : "word";
    body.innerHTML = `
      <div class="srs-card">
        <div class="row srs-card-meta">${badge}<span class="srs-card-type">${typeLabel}</span></div>
        <div class="srs-front">${cardFront(card)}</div>
        <div class="srs-back" ${revealed ? "" : "hidden"}>${cardBack(card)}</div>
        <div class="srs-controls">
          ${
            revealed
              ? GRADES.map(
                  (g) =>
                    `<button class="srs-grade srs-grade-${g.grade}" data-grade="${g.grade}" title="${g.hint} (${g.key})">${g.label}</button>`,
                ).join("")
              : `<button id="srs-reveal" title="Show answer (space)">Show answer</button>`
          }
        </div>
      </div>`;
    body.querySelector<HTMLButtonElement>("#srs-reveal")?.addEventListener("click", reveal);
    body.querySelectorAll<HTMLButtonElement>(".srs-grade").forEach((btn) => {
      btn.addEventListener("click", () => void grade(Number(btn.dataset.grade) as StudyGrade));
    });
  }

  function reveal() {
    if (revealed || index >= cards.length) return;
    revealed = true;
    renderCard();
  }

  async function grade(g: StudyGrade) {
    if (!revealed || submitting || index >= cards.length) return;
    submitting = true;
    const card = cards[index];
    try {
      await postStudyReview(card, g, Date.now() - shownAt);
      reviewed += 1;
      if (g === 1) {
        lapses += 1;
        // Failed cards come back at the end of this session.
        cards.push(card);
      }
      index += 1;
      revealed = false;
      shownAt = Date.now();
      renderCard();
    } catch (e: any) {
      logError("StudySession", "review_failed", { item_id: card.item_id, error: e.message });
      toastError("Failed to record review: " + e.message);
    } finally {
      submitting = false;
    }
  }

  async function loadQueue() {
    body.innerHTML = `<p class="empty">Loading queue…</p>`;
    try {
      const queue = await getStudyQueue(QUEUE_LIMIT, NEW_LIMIT);
      cards = queue.cards;
      counts = queue.counts;
      index = 0;
      revealed = false;
      reviewed = 0;
      lapses = 0;
      shownAt = Date.now();
      info("StudySession", "queue_loaded", { cards: cards.length, ...counts });
      if (cards.length === 0) renderEmpty();
      else renderCard();
    } catch (e: any) {
      logError("StudySession", "queue_failed", { error: e.message });
      body.innerHTML = `<p class="error">Failed to load the study queue: ${escapeHtml(e.message)}</p>`;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.metaKey || e.ctrlKey || e.altKey || isTypingTarget(e.target)) return;
    if (e.key === " " || e.key === "Enter") {
      if (!revealed && index < cards.length) {
        e.preventDefault();
        reveal();
      }
      return;
    }
    const match = GRADES.find((g) => g.key === e.key);
    if (match && revealed) {
      e.preventDefault();
      void grade(match.grade);
    }
  }
  document.addEventListener("keydown", onKeydown);

  void loadQueue();

  return () => {
    document.removeEventListener("keydown", onKeydown);
  };
}
