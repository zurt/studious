import {
  getDocument, getChapter, pageImageUrl,
  createRegion, deleteRegion, transcribeRegion, listRegions, openJobStream,
  type DocMeta, type Chapter, type Region,
} from "../api";
import { generateCorrelationId, info } from "../logger";
import { navigate } from "../router";
import { createRegionDrawer, type DrawableRegion } from "../modules/region-drawer";
import { renderRegionList } from "../modules/region-list";
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
          <div class="spacer"></div>
          <button id="prev-btn" disabled>&larr;</button>
          <span id="page-info">-</span>
          <button id="next-btn" disabled>&rarr;</button>
        </div>
      </div>
      <div class="pane-row">
        <div class="pane left">
          <img id="page-img" class="page-img" alt="Page" />
        </div>
        <div class="pane" id="right-pane">
          <div id="region-list-container"></div>
          <div id="region-detail" class="region-detail"></div>
        </div>
      </div>
    </div>
  `;

  const backLink = container.querySelector<HTMLAnchorElement>("#back-link")!;
  backLink.addEventListener("click", (e) => { e.preventDefault(); navigate(`/doc/${docId}`); });

  const chapterTitle = container.querySelector<HTMLElement>("#chapter-title")!;
  const pageInfo = container.querySelector<HTMLElement>("#page-info")!;
  const prevBtn = container.querySelector<HTMLButtonElement>("#prev-btn")!;
  const nextBtn = container.querySelector<HTMLButtonElement>("#next-btn")!;
  const pageImg = container.querySelector<HTMLImageElement>("#page-img")!;
  const regionListContainer = container.querySelector<HTMLElement>("#region-list-container")!;
  const regionDetail = container.querySelector<HTMLElement>("#region-detail")!;

  let doc: DocMeta | null = null;
  let chapter: Chapter | null = null;
  let page = 0;
  let regions: Region[] = [];
  let selectedRegionId: string | null = null;
  let drawer: ReturnType<typeof createRegionDrawer> | null = null;

  async function load() {
    doc = await getDocument(docId);
    chapter = await getChapter(docId, chapterId);
    if (!chapter) {
      container.innerHTML = `<div class="library"><p class="error">Chapter not found</p></div>`;
      return;
    }
    chapterTitle.textContent = chapter.title;
    page = chapter.page_start;
    regions = chapter.regions || [];
    setupDrawer();
    updatePage();
  }

  function setupDrawer() {
    if (drawer) drawer.destroy();
    drawer = createRegionDrawer(pageImg, {
      regions: toDrawable(pageRegions()),
      onDraw: (bbox) => showTagPopover(bbox),
      onSelect: (id) => selectRegion(id),
    });
  }

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
    pageImg.src = pageImageUrl(docId, page);
    pageInfo.textContent = `${page} (${chapter.page_start}-${chapter.page_end})`;
    prevBtn.disabled = page <= chapter.page_start;
    nextBtn.disabled = page >= chapter.page_end;
    selectedRegionId = null;
    refreshRegionUI();
  }

  function refreshRegionUI() {
    const pr = pageRegions();
    drawer?.setRegions(toDrawable(pr));
    renderRegionList(regionListContainer, pr, selectedRegionId, {
      onTranscribe: handleTranscribe,
      onDelete: handleDelete,
      onSelect: (r) => selectRegion(r.id),
    });
    renderDetail();
  }

  function selectRegion(id: string) {
    selectedRegionId = id === selectedRegionId ? null : id;
    refreshRegionUI();
  }

  function renderDetail() {
    const region = regions.find((r) => r.id === selectedRegionId);
    if (!region) {
      regionDetail.innerHTML = "";
      return;
    }
    if (region.transcription_md) {
      regionDetail.innerHTML = `
        <div class="region-detail-header">Transcription</div>
        <div class="markdown">${marked.parse(region.transcription_md)}</div>
      `;
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
    document.body.appendChild(bg);

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
        refreshRegionUI();
      } catch (e: any) {
        alert("Failed to create region: " + e.message);
      }
    });
  }

  async function handleTranscribe(region: Region) {
    try {
      const { job_id } = await transcribeRegion(docId, chapterId, region.id);
      info("ChapterView", "transcribe_started", { region_id: region.id, job_id });

      openJobStream(job_id, async (event) => {
        if (event.event === "job-done") {
          // Reload regions to get updated transcription
          regions = await listRegions(docId, chapterId);
          refreshRegionUI();
        } else if (event.event === "job-failed") {
          alert("Transcription failed: " + (event.data?.error || "unknown error"));
        }
      });
    } catch (e: any) {
      alert("Failed to start transcription: " + e.message);
    }
  }

  async function handleDelete(region: Region) {
    try {
      await deleteRegion(docId, chapterId, region.id);
      regions = regions.filter((r) => r.id !== region.id);
      if (selectedRegionId === region.id) selectedRegionId = null;
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
    if (e.key === "ArrowLeft") prevBtn.click();
    if (e.key === "ArrowRight") nextBtn.click();
  }
  document.addEventListener("keydown", onKey);

  load();

  return () => {
    document.removeEventListener("keydown", onKey);
    drawer?.destroy();
  };
}
