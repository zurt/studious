import {
  getDocument, getChapter, pageImageUrl,
  createRegion, deleteRegion, transcribeRegion, listRegions, openJobStream,
  type DocMeta, type Chapter, type Region,
} from "../api";
import { generateCorrelationId, info } from "../logger";
import { navigate, replaceQuery } from "../router";
import { createRegionDrawer, type DrawableRegion } from "../modules/region-drawer";
import { renderRegionList, makeCopyButton } from "../modules/region-list";
import { createZoomPanViewer } from "../modules/zoom-pan";
import { confirmDialog } from "../modules/confirm";
import { attachPageInput } from "../modules/page-input";
import { attachPaneSplitter } from "../modules/pane-splitter";
import { marked } from "marked";

const VALID_TAGS = ["reading_passage", "vocab_list", "grammar_points", "exercises", "instructions", "other"];

export function mountChapterView(params: Record<string, string>, container: HTMLElement) {
  const docId = params.id;
  const chapterId = params.chapterId;
  generateCorrelationId();

  container.innerHTML = `
    <div class="viewer">
      <div class="viewer-top">
        <div class="topbar">
          <a href="/doc/${docId}" id="back-link">Document</a>
          <span id="chapter-title">Loading...</span>
          <button id="prev-chapter-btn" class="chapter-nav-btn" title="Previous chapter" aria-label="Previous chapter" disabled>&larr;</button>
          <button id="next-chapter-btn" class="chapter-nav-btn" title="Next chapter" aria-label="Next chapter" disabled>&rarr;</button>
          <div class="spacer"></div>
          <button id="tracker-btn" title="Untranscribed regions">0 pending</button>
          <button id="prev-btn" disabled>&larr;</button>
          <span id="page-info">-</span>
          <button id="next-btn" disabled>&rarr;</button>
        </div>
      </div>
      <div class="pane-row">
        <div class="pane left" id="left-pane"></div>
        <div class="pane" id="right-pane">
          <div id="region-list-container"></div>
          <div id="region-detail" class="region-detail"></div>
        </div>
      </div>
    </div>
    <div id="tracker-popover" class="tracker-popover" style="display:none"></div>
  `;

  const backLink = container.querySelector<HTMLAnchorElement>("#back-link")!;
  backLink.addEventListener("click", (e) => { e.preventDefault(); navigate(`/doc/${docId}`); });

  const chapterTitle = container.querySelector<HTMLElement>("#chapter-title")!;
  const pageInfo = container.querySelector<HTMLElement>("#page-info")!;
  const prevBtn = container.querySelector<HTMLButtonElement>("#prev-btn")!;
  const nextBtn = container.querySelector<HTMLButtonElement>("#next-btn")!;
  const trackerBtn = container.querySelector<HTMLButtonElement>("#tracker-btn")!;
  const prevChapterBtn = container.querySelector<HTMLButtonElement>("#prev-chapter-btn")!;
  const nextChapterBtn = container.querySelector<HTMLButtonElement>("#next-chapter-btn")!;
  const leftPane = container.querySelector<HTMLElement>("#left-pane")!;
  const regionListContainer = container.querySelector<HTMLElement>("#region-list-container")!;
  const regionDetail = container.querySelector<HTMLElement>("#region-detail")!;
  const trackerPopover = container.querySelector<HTMLElement>("#tracker-popover")!;

  attachPaneSplitter(container.querySelector<HTMLElement>(".pane-row")!);
  const viewer = createZoomPanViewer(leftPane);

  attachPageInput(pageInfo, {
    getMin: () => chapter?.page_start ?? 1,
    getMax: () => chapter?.page_end ?? 1,
    getCurrent: () => page,
    onCommit: (p) => { page = p; updatePage(); },
  });

  const initialQuery = new URLSearchParams(location.search);
  const initialPageParam = parseInt(initialQuery.get("page") || "", 10);
  const initialRegionParam = initialQuery.get("region");

  let doc: DocMeta | null = null;
  let chapter: Chapter | null = null;
  let page = 0;
  let regions: Region[] = [];
  let selectedRegionId: string | null = null;
  let drawer: ReturnType<typeof createRegionDrawer> | null = null;
  let trackerOpen = false;
  const transcribingIds = new Set<string>();

  function syncUrl() {
    replaceQuery({ page: String(page), region: selectedRegionId });
  }

  // ---------- Tracker popover ----------
  function positionTrackerPopover() {
    const btnRect = trackerBtn.getBoundingClientRect();
    const popoverWidth = trackerPopover.offsetWidth || 320;
    let left = btnRect.right - popoverWidth;
    if (left < 8) left = 8;
    trackerPopover.style.left = left + "px";
    trackerPopover.style.right = "auto";
    trackerPopover.style.top = (btnRect.bottom + 4) + "px";
  }

  trackerBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    trackerOpen = !trackerOpen;
    trackerPopover.style.display = trackerOpen ? "flex" : "none";
    if (trackerOpen) {
      renderTracker();
      positionTrackerPopover();
    }
  });

  function onDocClick(e: MouseEvent) {
    if (trackerOpen && !trackerPopover.contains(e.target as Node) && e.target !== trackerBtn) {
      trackerOpen = false;
      trackerPopover.style.display = "none";
    }
  }
  document.addEventListener("click", onDocClick);

  function updateTrackerBtn() {
    const pending = regions.filter((r) => !r.transcription_md).length;
    trackerBtn.textContent = pending > 0 ? `${pending} pending` : "All done";
  }

  function renderTracker() {
    const sorted = [...regions].sort((a, b) =>
      a.page - b.page || a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0]
    );
    const pending = sorted.filter((r) => !r.transcription_md);
    const done = sorted.filter((r) => r.transcription_md);
    trackerPopover.innerHTML = `
      <div class="tracker-header">
        <span>Regions</span>
        <span style="font-size:11px;color:var(--muted)">${done.length}/${regions.length} transcribed</span>
        <div class="grow"></div>
        ${pending.length > 0 ? `<button id="batch-transcribe-btn">Transcribe all</button>` : ""}
      </div>
      <div class="tracker-list">
        ${sorted.length === 0 ? '<div class="sidebar-empty">No regions yet</div>' : ""}
        ${sorted.map((r) => `
          <div class="tracker-item" data-page="${r.page}" data-id="${r.id}">
            <div class="tracker-item-info">
              <div class="tracker-item-title">${r.label || r.tag.replace("_", " ")}</div>
              <div class="tracker-item-meta">p. ${r.page} &middot; ${r.tag.replace("_", " ")}</div>
            </div>
            <span class="tracker-status ${r.transcription_md ? "done" : "pending"}">
              ${r.transcription_md ? "done" : "pending"}
            </span>
          </div>
        `).join("")}
      </div>
    `;

    // Click to navigate to region's page
    trackerPopover.querySelectorAll<HTMLElement>(".tracker-item").forEach((el) => {
      el.addEventListener("click", () => {
        const targetPage = parseInt(el.dataset.page!);
        const targetId = el.dataset.id!;
        if (targetPage !== page) {
          page = targetPage;
          updatePage();
        }
        selectRegion(targetId);
        trackerOpen = false;
        trackerPopover.style.display = "none";
      });
    });

    // Batch transcribe
    const batchBtn = trackerPopover.querySelector<HTMLButtonElement>("#batch-transcribe-btn");
    if (batchBtn) {
      batchBtn.addEventListener("click", () => handleBatchTranscribe());
    }
  }

  async function handleBatchTranscribe() {
    const pending = regions.filter((r) => !r.transcription_md);
    if (pending.length === 0) return;

    info("ChapterView", "batch_transcribe_started", { count: pending.length });

    for (const region of pending) {
      try {
        const { job_id } = await transcribeRegion(docId, chapterId, region.id);
        await new Promise<void>((resolve) => {
          openJobStream(job_id, async (event) => {
            if (event.event === "job-done" || event.event === "job-failed") {
              resolve();
            }
          });
        });
      } catch {
        // Continue with next region on error
      }
    }

    // Reload all regions after batch completes
    regions = await listRegions(docId, chapterId);
    updateTrackerBtn();
    renderTracker();
    refreshRegionUI();
  }

  async function load() {
    doc = await getDocument(docId);
    chapter = await getChapter(docId, chapterId);
    if (!chapter) {
      container.innerHTML = `<div class="library"><p class="error">Chapter not found</p></div>`;
      return;
    }
    // If the URL asks for a page outside this chapter's range, drop chapter
    // context and let the document view handle it.
    if (Number.isFinite(initialPageParam)
        && (initialPageParam < chapter.page_start || initialPageParam > chapter.page_end)) {
      navigate(`/doc/${docId}?page=${initialPageParam}`);
      return;
    }

    chapterTitle.textContent = chapter.title;
    chapterTitle.title = chapter.title;
    updateChapterNav();
    regions = chapter.regions || [];
    page = Number.isFinite(initialPageParam) ? initialPageParam : chapter.page_start;

    // Restore selected region from URL if it exists on the current page.
    if (initialRegionParam) {
      const r = regions.find((reg) => reg.id === initialRegionParam);
      if (r && r.page === page) selectedRegionId = r.id;
    }

    updateTrackerBtn();
    setupDrawer();
    updatePage();
  }

  function setupDrawer() {
    if (drawer) drawer.destroy();
    drawer = createRegionDrawer(viewer.getImage(), {
      regions: toDrawable(pageRegions()),
      onDraw: (bbox) => showTagPopover(bbox),
      onSelect: (id) => selectRegion(id),
    });
  }

  function sortedChapters(): Chapter[] {
    const list = doc?.chapters || [];
    return [...list].sort((a, b) => a.order - b.order || a.page_start - b.page_start);
  }

  function updateChapterNav() {
    const list = sortedChapters();
    const idx = list.findIndex((c) => c.id === chapterId);
    prevChapterBtn.disabled = idx <= 0;
    nextChapterBtn.disabled = idx < 0 || idx >= list.length - 1;
  }

  function jumpChapter(delta: number) {
    const list = sortedChapters();
    const idx = list.findIndex((c) => c.id === chapterId);
    const target = list[idx + delta];
    if (target) navigate(`/doc/${docId}/chapter/${target.id}`);
  }

  prevChapterBtn.addEventListener("click", () => jumpChapter(-1));
  nextChapterBtn.addEventListener("click", () => jumpChapter(1));

  function pageRegions(): Region[] {
    return regions.filter((r) => r.page === page);
  }

  function toDrawable(regs: Region[]): DrawableRegion[] {
    return regs.map((r) => ({
      id: r.id,
      bbox: r.bbox,
      tag: r.tag,
      label: r.label,
      selected: r.id === selectedRegionId,
    }));
  }

  function updatePage() {
    if (!chapter) return;
    viewer.setImage(pageImageUrl(docId, page));
    pageInfo.textContent = `${page} (${chapter.page_start}-${chapter.page_end})`;
    prevBtn.disabled = page <= chapter.page_start;
    nextBtn.disabled = page >= chapter.page_end;
    // Clear selection if it's no longer on this page (e.g. after prev/next).
    if (selectedRegionId) {
      const sel = regions.find((r) => r.id === selectedRegionId);
      if (!sel || sel.page !== page) selectedRegionId = null;
    }
    syncUrl();
    refreshRegionUI();
  }

  function refreshRegionUI() {
    const pr = pageRegions();
    drawer?.setRegions(toDrawable(pr));
    renderRegionList(regionListContainer, pr, selectedRegionId, {
      onTranscribe: handleTranscribe,
      onRetranscribe: handleRetranscribe,
      onDelete: handleDelete,
      onSelect: (r) => selectRegion(r.id),
      transcribingIds,
    });
    renderDetail();
  }

  function selectRegion(id: string) {
    selectedRegionId = id === selectedRegionId ? null : id;
    syncUrl();
    refreshRegionUI();
  }

  function renderDetail() {
    const region = regions.find((r) => r.id === selectedRegionId);
    if (!region) {
      regionDetail.innerHTML = "";
      return;
    }
    const inFlight = transcribingIds.has(region.id);
    if (region.transcription_md) {
      const meta: string[] = [];
      if (region.transcribed_model) meta.push(region.transcribed_model);
      if (region.transcribed_at) meta.push(new Date(region.transcribed_at).toLocaleString());
      const metaHtml = meta.length ? `<div class="region-detail-meta">${meta.join(" · ")}</div>` : "";
      const busyHtml = inFlight ? `<div class="region-detail-busy"><span class="spinner"></span> Re-transcribing…</div>` : "";
      regionDetail.innerHTML = `
        <div class="region-detail-header">
          <span>Transcription</span>
          <span class="region-detail-actions"></span>
        </div>
        ${metaHtml}
        ${busyHtml}
        <div class="markdown">${marked.parse(region.transcription_md)}</div>
      `;
      const detailActions = regionDetail.querySelector(".region-detail-actions");
      if (detailActions) {
        detailActions.appendChild(makeCopyButton(() => region.transcription_md || ""));
      }
    } else if (inFlight) {
      regionDetail.innerHTML = `<div class="region-detail-header">Transcribing…</div><div class="region-detail-busy"><span class="spinner"></span> Working on this region.</div>`;
    } else {
      regionDetail.innerHTML = `<div class="region-detail-header">No transcription yet</div>`;
    }
  }

  function showTagPopover(bbox: [number, number, number, number]) {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `
      <div class="modal" style="width: min(360px, 90vw)">
        <h2>New Region</h2>
        <div class="field">
          <label>Tag</label>
          <select id="tag-select">
            ${VALID_TAGS.map((t) => `<option value="${t}">${t.replace("_", " ")}</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label>Label (optional)</label>
          <input id="region-label" type="text" placeholder="e.g. 本文, 語彙リスト" />
        </div>
        <div class="row">
          <div class="grow"></div>
          <button id="tag-cancel">Cancel</button>
          <button id="tag-save">Create</button>
        </div>
      </div>
    `;
    (document.fullscreenElement ?? document.body).appendChild(bg);

    bg.querySelector("#tag-cancel")!.addEventListener("click", () => bg.remove());
    bg.addEventListener("click", (e) => { if (e.target === bg) bg.remove(); });

    bg.querySelector("#tag-save")!.addEventListener("click", async () => {
      const tag = (bg.querySelector<HTMLSelectElement>("#tag-select")!).value;
      const label = (bg.querySelector<HTMLInputElement>("#region-label")!).value.trim();
      bg.remove();
      try {
        const region = await createRegion(docId, chapterId, { page, bbox, tag, label });
        info("ChapterView", "region_created", { region_id: region.id, tag });
        regions.push(region);
        selectedRegionId = region.id;
        syncUrl();
        updateTrackerBtn();
        refreshRegionUI();
      } catch (e: any) {
        alert("Failed to create region: " + e.message);
      }
    });
  }

  async function handleTranscribe(region: Region) {
    if (transcribingIds.has(region.id)) return;
    transcribingIds.add(region.id);
    refreshRegionUI();
    try {
      const { job_id } = await transcribeRegion(docId, chapterId, region.id);
      info("ChapterView", "transcribe_started", { region_id: region.id, job_id });

      let settled = false;
      const settle = async (kind: "done" | "failed", errMsg?: string) => {
        if (settled) return;
        settled = true;
        transcribingIds.delete(region.id);
        if (kind === "done") {
          regions = await listRegions(docId, chapterId);
          updateTrackerBtn();
        } else {
          alert("Transcription failed: " + (errMsg || "unknown error"));
        }
        refreshRegionUI();
      };

      openJobStream(job_id, async (event) => {
        if (event.event === "job-done") {
          await settle("done");
        } else if (event.event === "job-failed") {
          await settle("failed", event.data?.error);
        } else if (event.event === "snapshot") {
          // Race: job may have completed before the EventSource subscribed.
          // The replayed snapshot is then our only signal.
          const status = event.data?.status;
          if (status === "completed") {
            await settle("done");
          } else if (status === "failed") {
            const msg = event.data?.errors?.[0]?.message;
            await settle("failed", msg);
          }
        }
      });
    } catch (e: any) {
      transcribingIds.delete(region.id);
      refreshRegionUI();
      alert("Failed to start transcription: " + e.message);
    }
  }

  async function handleRetranscribe(region: Region) {
    if (transcribingIds.has(region.id)) return;
    const desc = region.label ? `"${region.label}" (${region.tag})` : region.tag;
    const ok = await confirmDialog(
      "Re-transcribe region?",
      `Re-transcribe ${desc} on page ${region.page}? The existing transcription will be replaced.`,
      "Re-transcribe",
    );
    if (!ok) return;
    handleTranscribe(region);
  }

  async function handleDelete(region: Region) {
    const desc = region.label ? `"${region.label}" (${region.tag})` : region.tag;
    const ok = await confirmDialog(
      "Delete region?",
      `Delete ${desc} on page ${region.page}? Its transcription will be lost.`,
    );
    if (!ok) return;
    try {
      await deleteRegion(docId, chapterId, region.id);
      regions = regions.filter((r) => r.id !== region.id);
      if (selectedRegionId === region.id) {
        selectedRegionId = null;
        syncUrl();
      }
      updateTrackerBtn();
      refreshRegionUI();
    } catch (e: any) {
      alert("Failed to delete region: " + e.message);
    }
  }

  prevBtn.addEventListener("click", () => {
    if (chapter && page > chapter.page_start) { page--; updatePage(); }
  });
  nextBtn.addEventListener("click", () => {
    if (chapter && page < chapter.page_end) { page++; updatePage(); }
  });

  function onKey(e: KeyboardEvent) {
    if (e.metaKey || e.ctrlKey) return; // let zoom-pan handle Cmd keys
    if (e.key === "ArrowLeft") prevBtn.click();
    if (e.key === "ArrowRight") nextBtn.click();
  }
  document.addEventListener("keydown", onKey);

  load();

  return () => {
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("click", onDocClick);
    drawer?.destroy();
    viewer.destroy();
  };
}
