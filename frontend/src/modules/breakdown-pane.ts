import {
  getBreakdown, requestBreakdown, openJobStream,
  type Breakdown, type BreakdownSentence, type Region,
} from "../api";
import { generateCorrelationId, info, error as logError } from "../logger";
import { confirmDialog } from "./confirm";
import { applyPaneCollapsed, chevronHtml, isPaneCollapsed, setPaneCollapsed } from "./collapsible";
import { makeCopyButton } from "./region-list";

type Ctx = { docId: string; chapterId: string; region: Region };

export function mountBreakdownPane(container: HTMLElement, ctx: Ctx): () => void {
  let breakdown: Breakdown | null = null;
  let loading = true;
  let busy = false;
  let errMsg: string | null = null;
  let closeStream: (() => void) | null = null;
  let destroyed = false;

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
    return b.sentences.map(sentenceToMarkdown).join("\n\n");
  }

  function escapeHtml(s: string): string {
    return s
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function headerHtml(actionsHtml: string = ""): string {
    const collapsed = isPaneCollapsed("breakdown");
    return `
      <div class="breakdown-pane-header pane-collapsible-header" role="button" tabindex="0" aria-expanded="${!collapsed}">
        <span class="pane-header-label">${chevronHtml(collapsed)}<span>Sentence breakdown</span></span>
        ${actionsHtml ? `<span class="breakdown-pane-actions">${actionsHtml}</span>` : ""}
      </div>`;
  }

  function render() {
    if (destroyed) return;
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
    const metaHtml = meta.length
      ? `<div class="region-detail-meta">${meta.map(escapeHtml).join(" · ")}</div>`
      : "";

    const cards = breakdown.sentences.map((s, i) => {
      const vocab = (s.vocab || []).map((v) => `
        <tr>
          <td class="bd-vocab-word">${escapeHtml(v.word)}</td>
          <td class="bd-vocab-reading">${escapeHtml(v.reading || "")}</td>
          <td class="bd-vocab-meaning">${escapeHtml(v.meaning)}</td>
        </tr>`).join("");
      const grammar = (s.grammar || []).map((g) => `
        <li><span class="bd-grammar-pattern">${escapeHtml(g.pattern)}</span> — ${escapeHtml(g.explanation)}</li>`).join("");
      return `
        <div class="breakdown-card" data-idx="${i}">
          <div class="breakdown-card-header">
            <div class="breakdown-text" lang="ja">${escapeHtml(s.text)}</div>
            <span class="breakdown-card-actions" data-copy-slot="${i}"></span>
          </div>
          ${vocab ? `<table class="breakdown-vocab"><tbody>${vocab}</tbody></table>` : ""}
          ${grammar ? `<ul class="breakdown-grammar">${grammar}</ul>` : ""}
          <div class="breakdown-gloss-row">
            <div class="breakdown-gloss is-blurred">${escapeHtml(s.gloss)}</div>
            <button type="button" class="icon-btn breakdown-gloss-toggle" data-gloss-toggle="${i}" title="Show gloss" aria-label="Show gloss" aria-pressed="false">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>
            </button>
          </div>
        </div>`;
    }).join("");

    container.innerHTML = `
      ${headerHtml(`<span class="breakdown-copy-all-slot"></span><button type="button" id="bd-regenerate">Regenerate</button>`)}
      ${metaHtml}
      <div class="breakdown-list">${cards}</div>`;

    const copyAllSlot = container.querySelector<HTMLElement>(".breakdown-copy-all-slot");
    if (copyAllSlot) {
      const copyAllBtn = makeCopyButton(() => allSentencesToMarkdown(breakdown!));
      copyAllBtn.title = "Copy all";
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
      const chev = header.querySelector(".pane-chevron");
      if (chev) chev.textContent = next ? "▸" : "▾";
    }
  }

  function onClick(e: MouseEvent) {
    const target = e.target as HTMLElement;
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

  async function loadExisting() {
    loading = true;
    render();
    try {
      breakdown = await getBreakdown(ctx.docId, ctx.chapterId, ctx.region.id);
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
    container.removeEventListener("click", onClick);
    container.removeEventListener("keydown", onKeydown);
    container.innerHTML = "";
  };
}
