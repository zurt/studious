import {
  getChapter, getGrammarGuide, requestGrammarGuide, openJobStream,
  type Chapter, type GrammarGuide, type GrammarGuidePoint,
} from "../api";
import { generateCorrelationId, info, error as logError } from "../logger";
import { navigate } from "../router";
import { confirmDialog } from "../modules/confirm";
import { makeCopyButton, ICON_REDO } from "../modules/region-list";
import { renderMarkdown } from "../modules/markdown";

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function pointToMarkdown(p: GrammarGuidePoint, idx: number): string {
  const lines: string[] = [];
  lines.push(`## ${idx + 1}. ${p.title}`);
  if (p.subtitle) lines.push(`**${p.subtitle}**`);
  for (const s of p.sections) {
    lines.push(`\n### ${s.heading}\n\n${s.body_md.trim()}`);
  }
  return lines.join("\n\n");
}

function guideToMarkdown(chapter: Chapter, guide: GrammarGuide): string {
  const out: string[] = [`# ${chapter.title} — Grammar Guide`];
  if (guide.intro) out.push(guide.intro.trim());
  guide.points.forEach((p, i) => out.push(pointToMarkdown(p, i)));
  return out.join("\n\n");
}

export function mountGrammarGuide(params: Record<string, string>, container: HTMLElement) {
  const docId = params.id;
  const chapterId = params.chapterId;

  container.innerHTML = `
    <div class="viewer">
      <div class="viewer-top">
        <div class="topbar">
          <a href="/doc/${docId}/chapter/${chapterId}" id="back-link">Chapter</a>
          <span id="gg-title">Grammar Guide</span>
          <div class="spacer"></div>
          <span id="gg-meta" class="region-detail-meta" style="font-size:11px;color:var(--muted)"></span>
          <span class="gg-actions">
            <button id="gg-regen-btn" class="icon-btn" title="Regenerate" aria-label="Regenerate" disabled>${ICON_REDO}</button>
            <span id="gg-copy-slot"></span>
          </span>
        </div>
      </div>
      <div id="gg-stale-banner" style="display:none;padding:8px 16px;background:#fff7e6;border-bottom:1px solid #f0c36d;color:#8a5a00;font-size:13px">
        Source has changed since this guide was generated. Regenerate to refresh.
      </div>
      <div id="gg-body" class="gg-body markdown" style="overflow:auto;flex:1;padding:24px;max-width:880px;margin:0 auto;width:100%"></div>
    </div>
  `;

  const backLink = container.querySelector<HTMLAnchorElement>("#back-link")!;
  backLink.addEventListener("click", (e) => {
    e.preventDefault();
    navigate(`/doc/${docId}/chapter/${chapterId}`);
  });

  const titleEl = container.querySelector<HTMLElement>("#gg-title")!;
  const metaEl = container.querySelector<HTMLElement>("#gg-meta")!;
  const bodyEl = container.querySelector<HTMLElement>("#gg-body")!;
  const regenBtn = container.querySelector<HTMLButtonElement>("#gg-regen-btn")!;
  const copySlot = container.querySelector<HTMLElement>("#gg-copy-slot")!;
  const staleBanner = container.querySelector<HTMLElement>("#gg-stale-banner")!;

  let chapter: Chapter | null = null;
  let guide: GrammarGuide | null = null;
  let busy = false;
  let closeStream: (() => void) | null = null;
  let destroyed = false;

const copyBtn = makeCopyButton(() => (chapter && guide) ? guideToMarkdown(chapter, guide) : "");
  copyBtn.title = "Copy to clipboard (Alt/Option for markdown)";
  copyBtn.setAttribute("aria-label", "Copy to clipboard");
  copySlot.appendChild(copyBtn);

  function renderBody() {
    if (!guide || !chapter) return;
    titleEl.textContent = `${chapter.title} — Grammar Guide`;
    const meta: string[] = [];
    if (guide.model) meta.push(guide.model);
    if (guide.updated_at) meta.push(new Date(guide.updated_at).toLocaleString());
    metaEl.textContent = meta.join(" · ");
    staleBanner.style.display = guide.is_stale ? "" : "none";
    const md = guideToMarkdown(chapter, guide);
    bodyEl.innerHTML = renderMarkdown(md);
  }

  function renderBusy(msg: string) {
    bodyEl.innerHTML = `<div class="region-detail-busy"><span class="spinner"></span> ${escapeHtml(msg)}</div>`;
  }

  function renderError(msg: string) {
    bodyEl.innerHTML = `<div class="breakdown-error">${escapeHtml(msg)}</div>`;
  }

  async function regenerate() {
    if (busy) return;
    const ok = await confirmDialog(
      "Regenerate grammar guide?",
      "The existing guide will be replaced.",
      "Regenerate",
    );
    if (!ok) return;
    busy = true;
    regenBtn.disabled = true;
    renderBusy("Generating grammar guide…");
    const cid = generateCorrelationId();
    try {
      const { job_id } = await requestGrammarGuide(docId, chapterId, { overwrite: true }, cid);
      info("GrammarGuide", "regenerate_started", { chapter_id: chapterId, job_id, correlation_id: cid });
      let settled = false;
      const settle = async (kind: "done" | "failed", errMsg?: string) => {
        if (settled || destroyed) return;
        settled = true;
        if (closeStream) { closeStream(); closeStream = null; }
        busy = false;
        regenBtn.disabled = false;
        if (kind === "done") {
          await reload();
        } else {
          logError("GrammarGuide", "regenerate_failed", {
            chapter_id: chapterId, job_id, error: errMsg, correlation_id: cid,
          });
          renderError("Regenerate failed: " + (errMsg || "unknown error"));
        }
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
      regenBtn.disabled = false;
      logError("GrammarGuide", "regenerate_submit_failed", {
        chapter_id: chapterId, error: e.message, stack: e.stack, correlation_id: cid,
      });
      renderError("Failed to start regenerate: " + e.message);
    }
  }

  regenBtn.addEventListener("click", () => void regenerate());

  async function reload() {
    renderBusy("Loading…");
    try {
      chapter = await getChapter(docId, chapterId);
      guide = await getGrammarGuide(docId, chapterId);
    } catch (e: any) {
      logError("GrammarGuide", "load_failed", {
        chapter_id: chapterId, error: e.message, stack: e.stack,
      });
      renderError("Failed to load: " + e.message);
      return;
    }
    if (!guide) {
      renderError("No grammar guide exists for this chapter yet. Generate one from the chapter view.");
      regenBtn.disabled = true;
      return;
    }
    regenBtn.disabled = busy;
    renderBody();
  }

  void reload();

  return () => {
    destroyed = true;
    if (closeStream) { closeStream(); closeStream = null; }
  };
}
