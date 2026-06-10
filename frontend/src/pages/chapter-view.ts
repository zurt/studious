import {
  getDocument, getChapter, pageImageUrl,
  createRegion, deleteRegion, transcribeRegion, listRegions, openJobStream, linkRegion,
  requestGrammarGuide,
  type DocMeta, type Chapter, type Region,
} from "../api";
import { generateCorrelationId, info, error as logError } from "../logger";
import { navigate, replaceQuery } from "../router";
import { createRegionDrawer, type DrawableRegion } from "../modules/region-drawer";
import { renderRegionList, makeCopyButton } from "../modules/region-list";
import { createZoomPanViewer } from "../modules/zoom-pan";
import { confirmDialog } from "../modules/confirm";
import { mountBreakdownPane } from "../modules/breakdown-pane";
import { applyPaneCollapsed, chevronHtml, isPaneCollapsed, setChevronCollapsed, setPaneCollapsed } from "../modules/collapsible";
import { attachPageInput } from "../modules/page-input";
import { attachPaneSplitter } from "../modules/pane-splitter";
import { marked } from "marked";

const VALID_TAGS = ["reading_passage", "vocab_list", "grammar_points", "exercises", "instructions", "other"];

type TextSize = 1 | 2 | 3;
const TEXT_SIZE_KEY = "studious.transcription.textSize";
function getTranscriptionTextSize(): TextSize {
  const v = Number(localStorage.getItem(TEXT_SIZE_KEY));
  return v === 2 || v === 3 ? v : 1;
}
function setTranscriptionTextSize(size: TextSize) {
  localStorage.setItem(TEXT_SIZE_KEY, String(size));
}

const LAST_REGION_KEY = "studious.lastRegion";
function lastRegionMap(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(LAST_REGION_KEY) || "{}");
  } catch {
    return {};
  }
}
function getRememberedRegion(chapterId: string, page: number): string | null {
  return lastRegionMap()[`${chapterId}:${page}`] || null;
}
function rememberRegion(chapterId: string, page: number, regionId: string | null) {
  const map = lastRegionMap();
  const key = `${chapterId}:${page}`;
  if (regionId) map[key] = regionId;
  else delete map[key];
  localStorage.setItem(LAST_REGION_KEY, JSON.stringify(map));
}

function pickFirstRegion(regs: Region[]): Region | null {
  if (regs.length === 0) return null;
  return [...regs].sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0])[0];
}

export function mountChapterView(params: Record<string, string>, container: HTMLElement) {
  const docId = params.id;
  const chapterId = params.chapterId;

  container.innerHTML = `
    <div class="viewer">
      <div class="viewer-top">
        <div class="topbar">
          <a href="/doc/${docId}" id="back-link">Document</a>
          <span id="chapter-title">Loading...</span>
          <button id="prev-chapter-btn" class="chapter-nav-btn" title="Previous chapter" aria-label="Previous chapter" disabled>&larr;</button>
          <button id="next-chapter-btn" class="chapter-nav-btn" title="Next chapter" aria-label="Next chapter" disabled>&rarr;</button>
          <div class="spacer"></div>
          <a id="grammar-guide-btn" class="topbar-link-btn" style="display:none" href=""></a>
          <button id="link-mode-btn" title="Link continuation region (L)">Link</button>
          <button id="tracker-btn" title="Untranscribed regions">0 pending</button>
          <button id="prev-btn" disabled>&larr;</button>
          <span id="page-info">-</span>
          <button id="next-btn" disabled>&rarr;</button>
        </div>
      </div>
      <div id="link-mode-banner" style="display:none; padding:6px 10px; background:rgba(16,185,129,0.12); color:rgb(16,185,129); font-size:12px; border-bottom:1px solid rgba(16,185,129,0.3);"></div>
      <div class="pane-row">
        <div class="pane left" id="left-pane"></div>
        <div class="pane" id="right-pane">
          <div id="region-list-container"></div>
          <div id="region-detail" class="region-detail"></div>
          <div id="breakdown-pane" class="breakdown-pane"></div>
        </div>
      </div>
    </div>
    <div id="tracker-popover" class="tracker-popover" style="display:none"></div>
  `;

  const backLink = container.querySelector<HTMLAnchorElement>("#back-link")!;
  backLink.addEventListener("click", (e) => {
    e.preventDefault();
    navigate(page > 0 ? `/doc/${docId}?page=${page}` : `/doc/${docId}`);
  });

  const chapterTitle = container.querySelector<HTMLElement>("#chapter-title")!;
  const pageInfo = container.querySelector<HTMLElement>("#page-info")!;
  const prevBtn = container.querySelector<HTMLButtonElement>("#prev-btn")!;
  const nextBtn = container.querySelector<HTMLButtonElement>("#next-btn")!;
  const trackerBtn = container.querySelector<HTMLButtonElement>("#tracker-btn")!;
  const linkModeBtn = container.querySelector<HTMLButtonElement>("#link-mode-btn")!;
  const linkBanner = container.querySelector<HTMLElement>("#link-mode-banner")!;
  const grammarGuideBtn = container.querySelector<HTMLAnchorElement>("#grammar-guide-btn")!;
  const prevChapterBtn = container.querySelector<HTMLButtonElement>("#prev-chapter-btn")!;
  const nextChapterBtn = container.querySelector<HTMLButtonElement>("#next-chapter-btn")!;
  const leftPane = container.querySelector<HTMLElement>("#left-pane")!;
  const regionListContainer = container.querySelector<HTMLElement>("#region-list-container")!;
  const regionDetail = container.querySelector<HTMLElement>("#region-detail")!;
  const breakdownPane = container.querySelector<HTMLElement>("#breakdown-pane")!;
  let breakdownDestroy: (() => void) | null = null;
  let breakdownMountKey: string | null = null;
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
  let batchInFlight = false;
  let batchTotalCount = 0;
  let batchDoneCount = 0;
  let linkMode = false;
  let pendingLinkSourceId: string | null = null;

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

  let grammarGuideBusy = false;

  function updateGrammarGuideBtn() {
    const grammar = regions.filter((r) => r.tag === "grammar_points");
    if (grammar.length === 0) {
      grammarGuideBtn.style.display = "none";
      return;
    }
    grammarGuideBtn.style.display = "";
    const pending = grammar.filter((r) => !r.transcription_md).length;
    const setDisabled = (disabled: boolean) => {
      if (disabled) grammarGuideBtn.setAttribute("aria-disabled", "true");
      else grammarGuideBtn.removeAttribute("aria-disabled");
    };
    if (grammarGuideBusy) {
      setDisabled(true);
      grammarGuideBtn.removeAttribute("href");
      grammarGuideBtn.textContent = "Generating…";
      grammarGuideBtn.title = "Grammar guide generation in progress";
      return;
    }
    if (pending > 0) {
      setDisabled(true);
      grammarGuideBtn.removeAttribute("href");
      grammarGuideBtn.textContent = "Grammar guide";
      grammarGuideBtn.title = `Transcribe ${pending} grammar region${pending === 1 ? "" : "s"} first`;
      return;
    }
    setDisabled(false);
    if (chapter?.has_grammar_guide) {
      grammarGuideBtn.href = `/doc/${docId}/chapter/${chapterId}/grammar-guide`;
      grammarGuideBtn.textContent = "Open grammar guide";
      grammarGuideBtn.title = "Open the chapter grammar guide";
    } else {
      grammarGuideBtn.removeAttribute("href");
      grammarGuideBtn.textContent = "Generate grammar guide";
      grammarGuideBtn.title = "Generate a grammar guide from this chapter's grammar regions";
    }
  }

  async function handleGrammarGuideClick(e: MouseEvent) {
    if (grammarGuideBtn.getAttribute("aria-disabled") === "true") {
      e.preventDefault();
      return;
    }
    if (chapter?.has_grammar_guide) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
      e.preventDefault();
      navigate(`/doc/${docId}/chapter/${chapterId}/grammar-guide`);
      return;
    }
    e.preventDefault();
    grammarGuideBusy = true;
    updateGrammarGuideBtn();
    const cid = generateCorrelationId();
    try {
      const { job_id } = await requestGrammarGuide(docId, chapterId, {}, cid);
      info("ChapterView", "grammar_guide_started", { chapter_id: chapterId, job_id, correlation_id: cid });
      let settled = false;
      const settle = async (kind: "done" | "failed", msg?: string) => {
        if (settled) return;
        settled = true;
        grammarGuideBusy = false;
        if (kind === "done") {
          if (chapter) chapter.has_grammar_guide = true;
          updateGrammarGuideBtn();
          navigate(`/doc/${docId}/chapter/${chapterId}/grammar-guide`);
        } else {
          logError("ChapterView", "grammar_guide_failed", {
            chapter_id: chapterId, job_id, error: msg, correlation_id: cid,
          });
          alert("Grammar guide generation failed: " + (msg || "unknown error"));
          updateGrammarGuideBtn();
        }
      };
      openJobStream(job_id, (event) => {
        if (event.event === "job-done") void settle("done");
        else if (event.event === "job-failed") void settle("failed", event.data?.error);
        else if (event.event === "snapshot") {
          const status = event.data?.status;
          if (status === "completed") void settle("done");
          else if (status === "failed") void settle("failed", event.data?.errors?.[0]?.message);
        }
      });
    } catch (e: any) {
      grammarGuideBusy = false;
      logError("ChapterView", "grammar_guide_submit_failed", {
        chapter_id: chapterId, error: e.message, stack: e.stack, correlation_id: cid,
      });
      alert("Failed to start grammar guide: " + e.message);
      updateGrammarGuideBtn();
    }
  }

  grammarGuideBtn.addEventListener("click", (e) => void handleGrammarGuideClick(e));

  function updateTrackerBtn() {
    const pending = regions.filter((r) => !r.transcription_md).length;
    trackerBtn.textContent = pending > 0 ? `${pending} pending` : "Regions";
    updateGrammarGuideBtn();
  }

  function renderTracker() {
    const sorted = [...regions].sort((a, b) =>
      a.page - b.page || a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0]
    );
    const pending = sorted.filter((r) => !r.transcription_md);
    const done = sorted.filter((r) => r.transcription_md);
    const batchTotal = batchInFlight ? batchTotalCount : 0;
    const batchDone = batchInFlight ? batchDoneCount : 0;
    const progressPct = batchTotal > 0 ? Math.round((batchDone / batchTotal) * 100) : 0;
    const batchProgressHtml = batchInFlight ? `
      <div class="tracker-progress">
        <div class="tracker-progress-text">Transcribing ${batchDone}/${batchTotal}…</div>
        <div class="tracker-progress-bar"><div class="tracker-progress-fill" style="width:${progressPct}%"></div></div>
      </div>` : "";
    const batchBtnHtml = pending.length > 0
      ? `<button id="batch-transcribe-btn"${batchInFlight ? " disabled" : ""}>${batchInFlight ? `Transcribing ${batchDone}/${batchTotal}…` : "Transcribe all"}</button>`
      : "";
    trackerPopover.innerHTML = `
      <div class="tracker-header">
        <span>Regions</span>
        <span style="font-size:11px;color:var(--muted)">${done.length}/${regions.length} transcribed</span>
        <div class="grow"></div>
        ${batchBtnHtml}
      </div>
      ${batchProgressHtml}
      <div class="tracker-list">
        ${sorted.length === 0 ? '<div class="sidebar-empty">No regions yet</div>' : ""}
        ${sorted.map((r) => {
          const isTranscribing = transcribingIds.has(r.id);
          const statusClass = r.transcription_md ? "done" : (isTranscribing ? "transcribing" : "pending");
          const statusLabel = r.transcription_md
            ? "done"
            : isTranscribing
              ? `<span class="spinner spinner-xs"></span> transcribing`
              : "pending";
          return `
          <div class="tracker-item${isTranscribing ? " is-transcribing" : ""}" data-page="${r.page}" data-id="${r.id}">
            <div class="tracker-item-info">
              <div class="tracker-item-title">${r.label || r.tag.replace("_", " ")}</div>
              <div class="tracker-item-meta">p. ${r.page} &middot; ${r.tag.replace("_", " ")}</div>
            </div>
            <span class="tracker-status ${statusClass}">${statusLabel}</span>
          </div>`;
        }).join("")}
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
    if (batchInFlight) return;
    const pending = regions.filter((r) => !r.transcription_md);
    if (pending.length === 0) return;

    const batchCid = generateCorrelationId();
    info("ChapterView", "batch_transcribe_started", { count: pending.length, correlation_id: batchCid });

    batchInFlight = true;
    batchTotalCount = pending.length;
    batchDoneCount = 0;
    renderTracker();

    for (const region of pending) {
      transcribingIds.add(region.id);
      renderTracker();
      refreshRegionUI();
      try {
        const { job_id } = await transcribeRegion(docId, chapterId, region.id, batchCid);
        await new Promise<void>((resolve) => {
          openJobStream(job_id, async (event) => {
            if (event.event === "job-done" || event.event === "job-failed") {
              resolve();
            }
          });
        });
      } catch (e: any) {
        logError("ChapterView", "batch_transcribe_region_failed", {
          region_id: region.id,
          error: e.message,
          stack: e.stack,
          correlation_id: batchCid,
        });
      }
      transcribingIds.delete(region.id);
      batchDoneCount += 1;
      try {
        regions = await listRegions(docId, chapterId);
      } catch {
        /* ignore — final reload below will retry */
      }
      updateTrackerBtn();
      renderTracker();
      refreshRegionUI();
    }

    batchInFlight = false;
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
      linkMode,
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
    const incomingTargets = new Set(
      regions.map((r) => r.continues_to).filter((x): x is string => !!x),
    );
    return regs.map((r) => ({
      id: r.id,
      bbox: r.bbox,
      tag: r.tag,
      label: r.label,
      selected: r.id === selectedRegionId,
      linkedTo: !!r.continues_to,
      linkedFrom: incomingTargets.has(r.id),
      linkPending: r.id === pendingLinkSourceId,
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
    // Restore remembered selection for this page, or fall back to the first region.
    if (!selectedRegionId) {
      const remembered = getRememberedRegion(chapterId, page);
      const onPage = pageRegions();
      const restored = remembered ? onPage.find((r) => r.id === remembered) : null;
      const target = restored || pickFirstRegion(onPage);
      selectedRegionId = target ? target.id : null;
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
      onHover: (r) => drawer?.setHover(r ? r.id : null),
      onJumpToRegion: (id) => jumpToRegion(id),
      onUnlink: (r) => handleUnlink(r),
      allRegions: regions,
      transcribingIds,
    });
    renderDetail();
  }

  function jumpToRegion(regionId: string) {
    const target = regions.find((r) => r.id === regionId);
    if (!target) return;
    if (target.page !== page) {
      page = target.page;
      selectedRegionId = target.id;
      updatePage();
    } else {
      selectRegion(target.id);
    }
  }

  async function handleUnlink(region: Region) {
    try {
      await linkRegion(docId, chapterId, region.id, null);
      const idx = regions.findIndex((r) => r.id === region.id);
      if (idx >= 0) regions[idx] = { ...regions[idx], continues_to: null };
      refreshRegionUI();
    } catch (e: any) {
      alert("Failed to unlink: " + e.message);
    }
  }

  function updateLinkBanner() {
    if (!linkMode) {
      linkBanner.style.display = "none";
      linkModeBtn.classList.remove("is-active");
      return;
    }
    linkBanner.style.display = "";
    linkModeBtn.classList.add("is-active");
    if (!pendingLinkSourceId) {
      linkBanner.textContent = "Link mode: click the source region (the one that continues onto a later page). Esc to cancel.";
    } else {
      const src = regions.find((r) => r.id === pendingLinkSourceId);
      const where = src ? ` (selected: p.${src.page})` : "";
      linkBanner.textContent = `Link mode${where}: navigate to a later page and click the continuation region. Esc to cancel.`;
    }
  }

  function toggleLinkMode(force?: boolean) {
    linkMode = force ?? !linkMode;
    if (!linkMode) pendingLinkSourceId = null;
    drawer?.setLinkMode(linkMode);
    updateLinkBanner();
    refreshRegionUI();
  }

  async function tryCompleteLink(targetId: string) {
    const src = regions.find((r) => r.id === pendingLinkSourceId);
    const tgt = regions.find((r) => r.id === targetId);
    if (!src || !tgt) return;
    if (src.id === tgt.id) {
      alert("Pick a different region as the continuation.");
      return;
    }
    if (tgt.page <= src.page) {
      alert("Continuation must be on a later page than the source.");
      return;
    }
    try {
      const updated = await linkRegion(docId, chapterId, src.id, tgt.id);
      const idx = regions.findIndex((r) => r.id === src.id);
      if (idx >= 0) regions[idx] = { ...regions[idx], continues_to: updated.continues_to ?? tgt.id };
      pendingLinkSourceId = null;
      toggleLinkMode(false);
    } catch (e: any) {
      alert("Failed to link: " + e.message);
    }
  }

  linkModeBtn.addEventListener("click", () => toggleLinkMode());

  function selectRegion(id: string) {
    if (linkMode) {
      if (!pendingLinkSourceId) {
        pendingLinkSourceId = id;
        updateLinkBanner();
        refreshRegionUI();
      } else {
        void tryCompleteLink(id);
      }
      return;
    }
    selectedRegionId = id === selectedRegionId ? null : id;
    rememberRegion(chapterId, page, selectedRegionId);
    syncUrl();
    refreshRegionUI();
  }

  function syncBreakdownPane(region: Region | undefined) {
    // Show the breakdown pane only on regions that (a) aren't vocab_list and
    // (b) have an existing transcription. Remount when the target region or
    // its transcription changes; otherwise leave it alone to avoid blowing
    // away in-progress state.
    const eligible = region && region.tag !== "vocab_list" && !!region.transcription_md;
    const key = eligible ? `${region.id}:${region.transcribed_at || ""}` : null;
    if (key === breakdownMountKey) return;
    if (breakdownDestroy) { breakdownDestroy(); breakdownDestroy = null; }
    breakdownMountKey = key;
    if (eligible && region) {
      breakdownPane.style.display = "";
      breakdownDestroy = mountBreakdownPane(breakdownPane, { docId, chapterId, region });
    } else {
      breakdownPane.style.display = "none";
      breakdownPane.innerHTML = "";
    }
  }

  function renderDetail() {
    const region = regions.find((r) => r.id === selectedRegionId);
    syncBreakdownPane(region);
    if (!region) {
      regionDetail.innerHTML = "";
      return;
    }
    const inFlight = transcribingIds.has(region.id);
    if (region.transcription_md) {
      const meta: string[] = [];
      if (region.transcribed_model) meta.push(region.transcribed_model);
      if (region.transcribed_at) meta.push(new Date(region.transcribed_at).toLocaleString());
      const metaInline = meta.length ? `<span class="region-detail-meta is-hidden" data-meta-target="transcription">${meta.join(" · ")}</span>` : "";
      const infoBtnHtml = meta.length ? `<button type="button" class="pane-info-btn" data-meta-toggle="transcription" title="Model details" aria-label="Model details" aria-pressed="false"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg></button>${metaInline}` : "";
      const busyHtml = inFlight ? `<div class="region-detail-busy"><span class="spinner"></span> Re-transcribing…</div>` : "";
      const size = getTranscriptionTextSize();
      const collapsed = isPaneCollapsed("transcription");
      regionDetail.innerHTML = `
        <div class="region-detail-header pane-collapsible-header" role="button" tabindex="0" aria-expanded="${!collapsed}">
          <span class="pane-header-label">${chevronHtml(collapsed)}<span>Transcription</span>${infoBtnHtml}</span>
          <span class="region-detail-actions">
            <span class="text-size-toggle" role="group" aria-label="Text size">
              <button type="button" class="icon-btn text-size-btn size-1${size === 1 ? " active" : ""}" data-size="1" title="100%" aria-label="100%" aria-pressed="${size === 1}">A</button>
              <button type="button" class="icon-btn text-size-btn size-2${size === 2 ? " active" : ""}" data-size="2" title="150%" aria-label="150%" aria-pressed="${size === 2}">A</button>
              <button type="button" class="icon-btn text-size-btn size-3${size === 3 ? " active" : ""}" data-size="3" title="200%" aria-label="200%" aria-pressed="${size === 3}">A</button>
            </span>
          </span>
        </div>
        ${busyHtml}
        <div class="markdown text-size-${size}">${marked.parse(region.transcription_md)}</div>
      `;
      const detailActions = regionDetail.querySelector(".region-detail-actions");
      if (detailActions) {
        detailActions.appendChild(makeCopyButton(() => region.transcription_md || ""));
      }
      const infoBtn = regionDetail.querySelector<HTMLButtonElement>('.pane-info-btn[data-meta-toggle="transcription"]');
      const metaEl = regionDetail.querySelector<HTMLElement>('.region-detail-meta[data-meta-target="transcription"]');
      if (infoBtn && metaEl) {
        infoBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          const hidden = metaEl.classList.toggle("is-hidden");
          infoBtn.setAttribute("aria-pressed", String(!hidden));
        });
      }
      regionDetail.querySelectorAll<HTMLButtonElement>(".text-size-btn").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const s = Number(btn.dataset.size) as 1 | 2 | 3;
          setTranscriptionTextSize(s);
          renderDetail();
        });
      });
      applyPaneCollapsed(regionDetail, "transcription");
    } else if (inFlight) {
      regionDetail.innerHTML = `<div class="region-detail-header">Transcribing…</div><div class="region-detail-busy"><span class="spinner"></span> Working on this region.</div>`;
      regionDetail.classList.remove("is-collapsed");
    } else {
      regionDetail.innerHTML = `<div class="region-detail-header">No transcription yet</div>`;
      regionDetail.classList.remove("is-collapsed");
    }
  }

  function toggleTranscriptionCollapsed() {
    const next = !isPaneCollapsed("transcription");
    setPaneCollapsed("transcription", next);
    applyPaneCollapsed(regionDetail, "transcription");
    const header = regionDetail.querySelector<HTMLElement>(".pane-collapsible-header");
    if (header) {
      header.setAttribute("aria-expanded", String(!next));
      const chev = header.querySelector<HTMLElement>(".pane-chevron");
      if (chev) setChevronCollapsed(chev, next);
    }
  }

  regionDetail.addEventListener("click", (e) => {
    const target = e.target as HTMLElement;
    if (!target.closest(".pane-collapsible-header")) return;
    if (target.closest(".region-detail-actions")) return;
    if (target.closest(".pane-info-btn")) return;
    toggleTranscriptionCollapsed();
  });
  regionDetail.addEventListener("keydown", (e) => {
    const target = e.target as HTMLElement;
    if (!target.classList.contains("pane-collapsible-header")) return;
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    toggleTranscriptionCollapsed();
  });

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
        logError("ChapterView", "region_create_failed", {
          chapter_id: chapterId, page, tag, error: e.message, stack: e.stack,
        });
        alert("Failed to create region: " + e.message);
      }
    });
  }

  async function handleTranscribe(region: Region) {
    if (transcribingIds.has(region.id)) return;
    transcribingIds.add(region.id);
    refreshRegionUI();
    const cid = generateCorrelationId();
    try {
      const { job_id } = await transcribeRegion(docId, chapterId, region.id, cid);
      info("ChapterView", "transcribe_started", { region_id: region.id, job_id, correlation_id: cid });

      let settled = false;
      const settle = async (kind: "done" | "failed", errMsg?: string) => {
        if (settled) return;
        settled = true;
        transcribingIds.delete(region.id);
        if (kind === "done") {
          regions = await listRegions(docId, chapterId);
          updateTrackerBtn();
        } else {
          logError("ChapterView", "transcribe_failed", {
            region_id: region.id, job_id, error: errMsg || "unknown", correlation_id: cid,
          });
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
      logError("ChapterView", "transcribe_submit_failed", {
        region_id: region.id, error: e.message, stack: e.stack, correlation_id: cid,
      });
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
      logError("ChapterView", "region_delete_failed", {
        region_id: region.id, error: e.message, stack: e.stack,
      });
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
    const tag = (e.target as HTMLElement | null)?.tagName;
    const inField = tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement | null)?.isContentEditable;
    if (e.key === "Escape" && linkMode) { toggleLinkMode(false); return; }
    if (!inField && (e.key === "l" || e.key === "L")) { toggleLinkMode(); return; }
    if (e.key === "ArrowLeft") prevBtn.click();
    if (e.key === "ArrowRight") nextBtn.click();
  }
  document.addEventListener("keydown", onKey);

  load();

  return () => {
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("click", onDocClick);
    if (breakdownDestroy) breakdownDestroy();
    drawer?.destroy();
    viewer.destroy();
  };
}
