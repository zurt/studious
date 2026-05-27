import {
  getBreakdown, requestBreakdown, openJobStream,
  getExerciseCompletion, requestExerciseCompletion,
  type Breakdown, type BreakdownLink, type BreakdownSentence, type Region,
  type ExerciseCompletion, type ExerciseCompletionEntry,
} from "../api";
import { generateCorrelationId, info, error as logError } from "../logger";
import { confirmDialog } from "./confirm";
import { applyPaneCollapsed, chevronHtml, isPaneCollapsed, setChevronCollapsed, setPaneCollapsed } from "./collapsible";
import { makeCopyButton, ICON_REDO } from "./region-list";

type Ctx = { docId: string; chapterId: string; region: Region };

export function mountBreakdownPane(container: HTMLElement, ctx: Ctx): () => void {
  let breakdown: Breakdown | null = null;
  let loading = true;
  let busy = false;
  let errMsg: string | null = null;
  let closeStream: (() => void) | null = null;
  let destroyed = false;
  const isExercise = ctx.region.tag === "exercises";
  let completion: ExerciseCompletion | null = null;
  const completionBusy = new Set<number>();
  const completionErrors = new Map<number, string>();
  const completionNotExercise = new Map<number, string>();
  const completionStreams = new Map<number, () => void>();
  const popover = document.createElement("div");
  popover.className = "bd-link-popover";
  popover.setAttribute("role", "dialog");
  popover.hidden = true;
  let activeLinkBtn: HTMLButtonElement | null = null;

  function closePopover(returnFocus = false) {
    if (popover.hidden) return;
    popover.hidden = true;
    popover.innerHTML = "";
    if (popover.parentElement) popover.parentElement.removeChild(popover);
    const wasActive = activeLinkBtn;
    activeLinkBtn = null;
    if (returnFocus && wasActive && document.contains(wasActive)) wasActive.focus();
  }

  function openPopover(btn: HTMLButtonElement) {
    if (!breakdown) return;
    const sIdx = Number(btn.dataset.sIdx);
    const kind = btn.dataset.kind as "vocab" | "grammar" | undefined;
    const idx = Number(btn.dataset.idx);
    const start = Number(btn.dataset.start);
    const s = breakdown.sentences[sIdx];
    if (!s || !kind) return;
    const link = (s.links || []).find(
      (l) => l.kind === kind && l.index === idx && l.start === start,
    );
    const refs: { kind: "vocab" | "grammar"; index: number }[] = [
      { kind, index: idx },
      ...((link?.extras as { kind: "vocab" | "grammar"; index: number }[] | undefined) || []),
    ];
    refs.sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "vocab" ? -1 : 1));
    const sections: string[] = [];
    const labels: string[] = [];
    for (const r of refs) {
      if (r.kind === "vocab") {
        const v = s.vocab?.[r.index];
        if (!v) continue;
        labels.push(`vocab: ${v.word}`);
        sections.push(`
          <div class="bd-popover-section" data-kind="vocab">
            <div class="bd-popover-word" lang="ja">${escapeHtml(v.word)}</div>
            ${v.reading ? `<div class="bd-popover-reading" lang="ja">${escapeHtml(v.reading)}</div>` : ""}
            <div class="bd-popover-meaning">${escapeHtml(v.meaning)}</div>
          </div>`);
      } else {
        const g = s.grammar?.[r.index];
        if (!g) continue;
        labels.push(`grammar: ${g.pattern}`);
        sections.push(`
          <div class="bd-popover-section" data-kind="grammar">
            <div class="bd-popover-pattern" lang="ja">${escapeHtml(g.pattern)}</div>
            <div class="bd-popover-meaning">${escapeHtml(g.explanation)}</div>
          </div>`);
      }
    }
    if (!sections.length) return;
    popover.innerHTML = sections.join('<div class="bd-popover-divider" role="separator"></div>');
    popover.setAttribute("aria-label", labels.join(" · "));
    const card = btn.closest(".breakdown-card") as HTMLElement | null;
    const parent = card || container;
    parent.appendChild(popover);
    popover.hidden = false;
    const parentRect = parent.getBoundingClientRect();
    const btnRect = btn.getBoundingClientRect();
    popover.style.top = `${btnRect.bottom - parentRect.top + 4}px`;
    const left = btnRect.left - parentRect.left;
    const maxLeft = Math.max(0, parent.clientWidth - popover.offsetWidth - 4);
    popover.style.left = `${Math.min(Math.max(0, left), maxLeft)}px`;
    activeLinkBtn = btn;
  }

  function onDocClick(e: MouseEvent) {
    if (popover.hidden) return;
    const target = e.target as Node;
    if (popover.contains(target)) return;
    if (activeLinkBtn && activeLinkBtn.contains(target)) return;
    const linkBtn = (target as HTMLElement).closest?.(".bd-link") as HTMLButtonElement | null;
    if (linkBtn && container.contains(linkBtn)) return;
    closePopover();
  }
  function onDocKeydown(e: KeyboardEvent) {
    if (e.key === "Escape" && !popover.hidden) {
      e.stopPropagation();
      closePopover(true);
    }
  }
  document.addEventListener("click", onDocClick, true);
  document.addEventListener("keydown", onDocKeydown);

  function sentenceToMarkdown(s: BreakdownSentence): string {
    const parts: string[] = [s.text];
    if (s.vocab && s.vocab.length) {
      const rows = s.vocab.map((v) => {
        const reading = v.reading ? `（${v.reading}）` : "";
        return `- ${v.word}${reading} — ${v.meaning}`;
      });
      parts.push("**Vocab**\n" + rows.join("\n"));
    }
    if (s.grammar && s.grammar.length) {
      const rows = s.grammar.map((g) => `- ${g.pattern} — ${g.explanation}`);
      parts.push("**Grammar**\n" + rows.join("\n"));
    }
    if (s.gloss) parts.push(s.gloss);
    return parts.join("\n\n");
  }

  function allSentencesToMarkdown(b: Breakdown): string {
    return b.sentences.map(sentenceToMarkdown).join("\n\n──────────\n\n");
  }

  function escapeHtml(s: string): string {
    return s
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function sentenceTextHtml(s: BreakdownSentence, sIdx: number): string {
    const text = s.text;
    const raw = (s.links || [])
      .filter((l) => (l.kind === "vocab" || l.kind === "grammar")
        && Number.isInteger(l.start) && Number.isInteger(l.end)
        && l.start >= 0 && l.end <= text.length && l.start < l.end)
      .slice()
      .sort((a, b) => a.start - b.start);
    const links: BreakdownLink[] = [];
    let cursor = 0;
    for (const l of raw) {
      if (l.start < cursor) continue;
      links.push(l);
      cursor = l.end;
    }
    if (!links.length) return escapeHtml(text);
    const out: string[] = [];
    let i = 0;
    for (const l of links) {
      if (l.start > i) out.push(escapeHtml(text.slice(i, l.start)));
      const span = text.slice(l.start, l.end);
      out.push(
        `<button type="button" class="bd-link" data-s-idx="${sIdx}" data-kind="${l.kind}" data-idx="${l.index}" data-start="${l.start}">${escapeHtml(span)}</button>`,
      );
      i = l.end;
    }
    if (i < text.length) out.push(escapeHtml(text.slice(i)));
    return out.join("");
  }

  function completionEntry(idx: number): ExerciseCompletionEntry | undefined {
    return completion?.completions?.[String(idx)];
  }

  function completionBlockHtml(idx: number): string {
    const entry = completionEntry(idx);
    const busyIt = completionBusy.has(idx);
    const errIt = completionErrors.get(idx);
    if (busyIt) {
      return `<div class="exercise-completion is-busy"><span class="spinner"></span> Completing exercise…</div>`;
    }
    if (entry) {
      const examples = (entry.examples || []).map((ex, ei) => `
        <li class="exercise-completion-example${ei === 0 ? " is-primary" : ""}">
          <div class="exercise-completion-example-jp" lang="ja">${escapeHtml(ex.japanese)}</div>
          <div class="exercise-completion-example-reading" lang="ja">${escapeHtml(ex.reading)}</div>
          <div class="exercise-completion-example-en">${escapeHtml(ex.english)}</div>
          <div class="exercise-completion-example-note">${escapeHtml(ex.explanation)}</div>
        </li>`).join("");
      return `
        <div class="exercise-completion">
          <div class="exercise-completion-header">
            <span class="exercise-completion-label">Completion</span>
            <button type="button" class="icon-btn" data-completion-regen="${idx}" title="Regenerate completion" aria-label="Regenerate completion">${ICON_REDO}</button>
          </div>
          <div class="exercise-completion-answer" lang="ja"><strong>Answer:</strong> ${escapeHtml(entry.answer)}</div>
          ${entry.answer_english ? `<div class="exercise-completion-answer-en">${escapeHtml(entry.answer_english)}</div>` : ""}
          ${entry.explanation ? `<div class="exercise-completion-explanation">${escapeHtml(entry.explanation)}</div>` : ""}
          ${examples ? `<ol class="exercise-completion-examples">${examples}</ol>` : ""}
        </div>`;
    }
    const notExercise = completionNotExercise.get(idx);
    const noticeHtml = notExercise
      ? `<div class="exercise-completion-notice">No exercise detected: ${escapeHtml(notExercise)}</div>`
      : "";
    const errHtml = errIt ? `<div class="exercise-completion-error">${escapeHtml(errIt)}</div>` : "";
    const btnLabel = notExercise || errIt ? "Try again" : "Complete exercise";
    return `
      <div class="exercise-completion is-empty">
        ${noticeHtml}
        ${errHtml}
        <button type="button" class="exercise-completion-btn" data-completion-gen="${idx}">${btnLabel}</button>
      </div>`;
  }

  function headerHtml(actionsHtml: string = "", metaText: string = ""): string {
    const collapsed = isPaneCollapsed("breakdown");
    const infoBtn = metaText ? `<button type="button" class="pane-info-btn" data-meta-toggle="breakdown" title="Model details" aria-label="Model details" aria-pressed="false"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg></button><span class="region-detail-meta is-hidden" data-meta-target="breakdown">${escapeHtml(metaText)}</span>` : "";
    return `
      <div class="breakdown-pane-header pane-collapsible-header" role="button" tabindex="0" aria-expanded="${!collapsed}">
        <span class="pane-header-label">${chevronHtml(collapsed)}<span>Sentence breakdown</span>${infoBtn}</span>
        ${actionsHtml ? `<span class="breakdown-pane-actions">${actionsHtml}</span>` : ""}
      </div>`;
  }

  function render() {
    if (destroyed) return;
    closePopover();
    if (loading) {
      container.innerHTML = `
        ${headerHtml()}
        <div class="region-detail-busy"><span class="spinner"></span> Loading…</div>`;
      applyPaneCollapsed(container, "breakdown");
      return;
    }
    if (errMsg) {
      container.innerHTML = `
        ${headerHtml(`<button type="button" id="bd-retry">Retry</button>`)}
        <div class="breakdown-error">${escapeHtml(errMsg)}</div>`;
      container.querySelector<HTMLButtonElement>("#bd-retry")!
        .addEventListener("click", (e) => { e.stopPropagation(); errMsg = null; void loadExisting(); });
      applyPaneCollapsed(container, "breakdown");
      return;
    }
    if (busy) {
      container.innerHTML = `
        ${headerHtml()}
        <div class="region-detail-busy"><span class="spinner"></span> Generating breakdown…</div>`;
      applyPaneCollapsed(container, "breakdown");
      return;
    }
    if (!breakdown) {
      container.innerHTML = `
        ${headerHtml(`<button type="button" id="bd-generate">Generate breakdown</button>`)}
        <div class="breakdown-empty">No breakdown yet.</div>`;
      container.querySelector<HTMLButtonElement>("#bd-generate")!
        .addEventListener("click", (e) => { e.stopPropagation(); void generate(false); });
      applyPaneCollapsed(container, "breakdown");
      return;
    }

    const meta: string[] = [];
    if (breakdown.model) meta.push(breakdown.model);
    if (breakdown.updated_at) meta.push(new Date(breakdown.updated_at).toLocaleString());
    const metaText = meta.join(" · ");

    const cards = breakdown.sentences.map((s, i) => {
      const vocab = (s.vocab || []).map((v) => `
        <tr>
          <td class="bd-vocab-word">${escapeHtml(v.word)}</td>
          <td class="bd-vocab-reading">${escapeHtml(v.reading || "")}</td>
          <td class="bd-vocab-meaning">${escapeHtml(v.meaning)}</td>
        </tr>`).join("");
      const grammar = (s.grammar || []).map((g) => `
        <li><span class="bd-grammar-pattern">${escapeHtml(g.pattern)}</span> — <span class="bd-grammar-explanation">${escapeHtml(g.explanation)}</span></li>`).join("");
      const hasAnswers = !!(vocab || grammar);
      const answersToggle = hasAnswers ? `
        <button type="button" class="icon-btn breakdown-answers-toggle" data-answers-toggle="${i}" title="Show vocab and grammar" aria-label="Show vocab and grammar" aria-pressed="false">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>
        </button>` : "";
      const answersBlock = hasAnswers ? `
        <div class="breakdown-answers">
          ${answersToggle}
          ${vocab ? `<table class="breakdown-vocab"><tbody>${vocab}</tbody></table>` : ""}
          ${grammar ? `<ul class="breakdown-grammar">${grammar}</ul>` : ""}
        </div>` : "";
      const completionBlock = isExercise ? completionBlockHtml(i) : "";
      return `
        <div class="breakdown-card${hasAnswers ? " answers-hidden" : ""}" data-idx="${i}">
          <div class="breakdown-card-header">
            <div class="breakdown-text" lang="ja">${sentenceTextHtml(s, i)}</div>
            <span class="breakdown-card-actions" data-copy-slot="${i}"></span>
          </div>
          ${answersBlock}
          <div class="breakdown-gloss-row">
            <div class="breakdown-gloss is-blurred">${escapeHtml(s.gloss)}</div>
            <button type="button" class="icon-btn breakdown-gloss-toggle" data-gloss-toggle="${i}" title="Show gloss" aria-label="Show gloss" aria-pressed="false">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>
            </button>
          </div>
          ${completionBlock}
        </div>`;
    }).join("");

    container.innerHTML = `
      ${headerHtml(`<button type="button" id="bd-regenerate" class="icon-btn" title="Regenerate" aria-label="Regenerate">${ICON_REDO}</button><span class="breakdown-copy-all-slot"></span>`, metaText)}
      <div class="breakdown-list">${cards}</div>`;

    const copyAllSlot = container.querySelector<HTMLElement>(".breakdown-copy-all-slot");
    if (copyAllSlot) {
      const copyAllBtn = makeCopyButton(() => allSentencesToMarkdown(breakdown!));
      copyAllBtn.title = "Copy all (Alt/Option for markdown)";
      copyAllBtn.setAttribute("aria-label", "Copy all");
      copyAllSlot.appendChild(copyAllBtn);
    }

    container.querySelectorAll<HTMLElement>("[data-copy-slot]").forEach((slot) => {
      const idx = Number(slot.getAttribute("data-copy-slot"));
      const sentence = breakdown!.sentences[idx];
      if (!sentence) return;
      slot.appendChild(makeCopyButton(() => sentenceToMarkdown(sentence)));
    });

    container.querySelectorAll<HTMLElement>(".breakdown-gloss-row").forEach((row) => {
      const btn = row.querySelector<HTMLButtonElement>("[data-gloss-toggle]");
      const gloss = row.querySelector<HTMLElement>(".breakdown-gloss");
      if (!btn || !gloss) return;
      const sync = () => {
        const blurred = gloss.classList.contains("is-blurred");
        btn.setAttribute("aria-pressed", String(!blurred));
        btn.title = blurred ? "Show gloss" : "Hide gloss";
        btn.setAttribute("aria-label", btn.title);
      };
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        gloss.classList.toggle("is-blurred");
        sync();
      });
      gloss.addEventListener("click", (e) => {
        if (!gloss.classList.contains("is-blurred")) return;
        e.stopPropagation();
        gloss.classList.remove("is-blurred");
        sync();
      });
    });

    container.querySelectorAll<HTMLElement>(".breakdown-card").forEach((card) => {
      const btn = card.querySelector<HTMLButtonElement>("[data-answers-toggle]");
      if (!btn) return;
      const sync = () => {
        const hidden = card.classList.contains("answers-hidden");
        btn.setAttribute("aria-pressed", String(!hidden));
        btn.title = hidden ? "Show vocab and grammar" : "Hide vocab and grammar";
        btn.setAttribute("aria-label", btn.title);
      };
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        card.classList.toggle("answers-hidden");
        sync();
      });
      card.addEventListener("click", (e) => {
        if (!card.classList.contains("answers-hidden")) return;
        const target = e.target as HTMLElement;
        if (!target.closest(".bd-vocab-reading, .bd-vocab-meaning, .bd-grammar-explanation")) return;
        e.stopPropagation();
        card.classList.remove("answers-hidden");
        sync();
      });
    });

    container.querySelector<HTMLButtonElement>("#bd-regenerate")!
      .addEventListener("click", async (e) => {
        e.stopPropagation();
        const ok = await confirmDialog(
          "Regenerate breakdown?",
          "The existing breakdown will be replaced.",
          "Regenerate",
        );
        if (ok) void generate(true);
      });
    applyPaneCollapsed(container, "breakdown");
  }

  function toggleCollapsed() {
    const next = !isPaneCollapsed("breakdown");
    setPaneCollapsed("breakdown", next);
    applyPaneCollapsed(container, "breakdown");
    const header = container.querySelector<HTMLElement>(".pane-collapsible-header");
    if (header) {
      header.setAttribute("aria-expanded", String(!next));
      const chev = header.querySelector<HTMLElement>(".pane-chevron");
      if (chev) setChevronCollapsed(chev, next);
    }
  }

  function onClick(e: MouseEvent) {
    const target = e.target as HTMLElement;
    const genBtn = target.closest("[data-completion-gen]") as HTMLButtonElement | null;
    if (genBtn) {
      e.stopPropagation();
      const idx = Number(genBtn.getAttribute("data-completion-gen"));
      void generateCompletion(idx, false);
      return;
    }
    const regenBtn = target.closest("[data-completion-regen]") as HTMLButtonElement | null;
    if (regenBtn) {
      e.stopPropagation();
      const idx = Number(regenBtn.getAttribute("data-completion-regen"));
      void (async () => {
        const ok = await confirmDialog(
          "Regenerate completion?",
          "The existing completion will be replaced.",
          "Regenerate",
        );
        if (ok) void generateCompletion(idx, true);
      })();
      return;
    }
    const linkBtn = target.closest(".bd-link") as HTMLButtonElement | null;
    if (linkBtn) {
      e.stopPropagation();
      if (activeLinkBtn === linkBtn && !popover.hidden) {
        closePopover(true);
      } else {
        openPopover(linkBtn);
      }
      return;
    }
    const infoBtn = target.closest('.pane-info-btn[data-meta-toggle="breakdown"]') as HTMLButtonElement | null;
    if (infoBtn) {
      e.stopPropagation();
      const metaEl = container.querySelector<HTMLElement>('.region-detail-meta[data-meta-target="breakdown"]');
      if (metaEl) {
        const hidden = metaEl.classList.toggle("is-hidden");
        infoBtn.setAttribute("aria-pressed", String(!hidden));
      }
      return;
    }
    if (!target.closest(".pane-collapsible-header")) return;
    if (target.closest(".breakdown-pane-actions")) return;
    toggleCollapsed();
  }
  function onKeydown(e: KeyboardEvent) {
    const target = e.target as HTMLElement;
    if (!target.classList.contains("pane-collapsible-header")) return;
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    toggleCollapsed();
  }
  container.addEventListener("click", onClick);
  container.addEventListener("keydown", onKeydown);

  async function generateCompletion(idx: number, overwrite: boolean) {
    if (completionBusy.has(idx)) return;
    completionBusy.add(idx);
    completionErrors.delete(idx);
    completionNotExercise.delete(idx);
    render();
    const cid = generateCorrelationId();
    try {
      const { job_id } = await requestExerciseCompletion(
        ctx.docId, ctx.chapterId, ctx.region.id,
        { sentence_index: idx, overwrite }, cid,
      );
      info("BreakdownPane", "exercise_completion_started", {
        region_id: ctx.region.id, sentence_index: idx, job_id, correlation_id: cid,
      });

      let settled = false;
      const settle = async (kind: "done" | "failed" | "no_exercise", msg?: string) => {
        if (settled || destroyed) return;
        settled = true;
        const stream = completionStreams.get(idx);
        if (stream) { stream(); completionStreams.delete(idx); }
        completionBusy.delete(idx);
        if (kind === "done") {
          try {
            completion = await getExerciseCompletion(ctx.docId, ctx.chapterId, ctx.region.id);
          } catch (e: any) {
            completionErrors.set(idx, "Failed to reload completion: " + e.message);
          }
        } else if (kind === "no_exercise") {
          completionNotExercise.set(idx, msg || "No exercise found in this sentence.");
          info("BreakdownPane", "exercise_completion_no_exercise", {
            region_id: ctx.region.id, sentence_index: idx, job_id, reason: msg, correlation_id: cid,
          });
        } else {
          completionErrors.set(idx, "Completion failed: " + (msg || "unknown error"));
          logError("BreakdownPane", "exercise_completion_failed", {
            region_id: ctx.region.id, sentence_index: idx, job_id, error: msg, correlation_id: cid,
          });
        }
        render();
      };

      const close = openJobStream(job_id, (event) => {
        if (event.event === "job-done") void settle("done");
        else if (event.event === "job-failed") {
          if (event.data?.code === "no_exercise") {
            void settle("no_exercise", event.data?.reason);
          } else {
            void settle("failed", event.data?.error);
          }
        } else if (event.event === "snapshot") {
          const status = event.data?.status;
          if (status === "completed") void settle("done");
          else if (status === "failed") {
            const firstErr = event.data?.errors?.[0];
            if (firstErr?.code === "no_exercise") {
              void settle("no_exercise", firstErr.reason);
            } else {
              void settle("failed", firstErr?.message);
            }
          }
        }
      });
      completionStreams.set(idx, close);
    } catch (e: any) {
      completionBusy.delete(idx);
      completionErrors.set(idx, "Failed to start completion: " + e.message);
      logError("BreakdownPane", "exercise_completion_submit_failed", {
        region_id: ctx.region.id, sentence_index: idx, error: e.message, correlation_id: cid,
      });
      render();
    }
  }

  async function loadExisting() {
    loading = true;
    render();
    try {
      breakdown = await getBreakdown(ctx.docId, ctx.chapterId, ctx.region.id);
      if (isExercise && breakdown) {
        try {
          completion = await getExerciseCompletion(ctx.docId, ctx.chapterId, ctx.region.id);
        } catch (e: any) {
          logError("BreakdownPane", "completion_load_failed", {
            region_id: ctx.region.id, error: e.message,
          });
        }
      }
    } catch (e: any) {
      logError("BreakdownPane", "load_failed", {
        region_id: ctx.region.id, error: e.message, stack: e.stack,
      });
      errMsg = "Failed to load breakdown: " + e.message;
      breakdown = null;
    } finally {
      loading = false;
      render();
    }
  }

  async function generate(overwrite: boolean) {
    if (busy) return;
    busy = true;
    errMsg = null;
    render();
    const cid = generateCorrelationId();
    try {
      const { job_id } = await requestBreakdown(
        ctx.docId, ctx.chapterId, ctx.region.id, { overwrite }, cid,
      );
      info("BreakdownPane", "breakdown_started", {
        region_id: ctx.region.id, job_id, correlation_id: cid,
      });

      let settled = false;
      const settle = async (kind: "done" | "failed", msg?: string) => {
        if (settled || destroyed) return;
        settled = true;
        if (closeStream) { closeStream(); closeStream = null; }
        busy = false;
        if (kind === "done") {
          try {
            breakdown = await getBreakdown(ctx.docId, ctx.chapterId, ctx.region.id);
          } catch (e: any) {
            errMsg = "Failed to reload breakdown: " + e.message;
          }
        } else {
          errMsg = "Breakdown failed: " + (msg || "unknown error");
          logError("BreakdownPane", "breakdown_failed", {
            region_id: ctx.region.id, job_id, error: msg, correlation_id: cid,
          });
        }
        render();
      };

      closeStream = openJobStream(job_id, (event) => {
        if (event.event === "job-done") void settle("done");
        else if (event.event === "job-failed") void settle("failed", event.data?.error);
        else if (event.event === "snapshot") {
          const status = event.data?.status;
          if (status === "completed") void settle("done");
          else if (status === "failed") void settle("failed", event.data?.errors?.[0]?.message);
        }
      });
    } catch (e: any) {
      busy = false;
      errMsg = "Failed to start breakdown: " + e.message;
      logError("BreakdownPane", "breakdown_submit_failed", {
        region_id: ctx.region.id, error: e.message, stack: e.stack, correlation_id: cid,
      });
      render();
    }
  }

  void loadExisting();

  return () => {
    destroyed = true;
    if (closeStream) { closeStream(); closeStream = null; }
    for (const close of completionStreams.values()) close();
    completionStreams.clear();
    closePopover();
    document.removeEventListener("click", onDocClick, true);
    document.removeEventListener("keydown", onDocKeydown);
    container.removeEventListener("click", onClick);
    container.removeEventListener("keydown", onKeydown);
    container.innerHTML = "";
  };
}
