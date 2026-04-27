import {
  getDocument, getTranscription, pageImageUrl, createChapter, updateChapter,
  type DocMeta, type Transcription, type Chapter,
} from "../api";
import { generateCorrelationId } from "../logger";
import { navigate } from "../router";
import { createZoomPanViewer } from "../modules/zoom-pan";
import { marked } from "marked";

export function mountDocumentView(params: Record<string, string>, container: HTMLElement) {
  const docId = params.id;
  generateCorrelationId();

  container.innerHTML = `
    <div class="viewer">
      <div class="viewer-top">
        <div class="topbar">
          <a href="/" id="back-link">Library</a>
          <span id="doc-title">Loading...</span>
          <div class="spacer"></div>
          <button id="prev-btn" disabled>&larr;</button>
          <span id="page-info">-</span>
          <button id="next-btn" disabled>&rarr;</button>
          <div class="spacer"></div>
          <button id="chapters-btn">Chapters</button>
          <button id="new-chapter-btn">+ Chapter</button>
        </div>
        <div id="chapter-banner" class="chapter-banner" style="display:none"></div>
      </div>
      <div class="pane-row">
        <div class="pane left" id="left-pane"></div>
        <div class="pane" id="right-pane">
          <div class="empty">Select a page to view</div>
        </div>
      </div>
    </div>
    <div id="chapters-popover" class="popover-panel" style="display:none"></div>
  `;

  const backLink = container.querySelector<HTMLAnchorElement>("#back-link")!;
  backLink.addEventListener("click", (e) => { e.preventDefault(); navigate("/"); });

  const docTitle = container.querySelector<HTMLElement>("#doc-title")!;
  const pageInfo = container.querySelector<HTMLElement>("#page-info")!;
  const prevBtn = container.querySelector<HTMLButtonElement>("#prev-btn")!;
  const nextBtn = container.querySelector<HTMLButtonElement>("#next-btn")!;
  const chaptersBtn = container.querySelector<HTMLButtonElement>("#chapters-btn")!;
  const newChapterBtn = container.querySelector<HTMLButtonElement>("#new-chapter-btn")!;
  const rightPane = container.querySelector<HTMLElement>("#right-pane")!;
  const leftPane = container.querySelector<HTMLElement>("#left-pane")!;
  const chapterBanner = container.querySelector<HTMLElement>("#chapter-banner")!;
  const chaptersPopover = container.querySelector<HTMLElement>("#chapters-popover")!;

  const viewer = createZoomPanViewer(leftPane);

  let doc: DocMeta | null = null;
  let page = 1;
  let popoverOpen = false;

  // ---------- Chapter popover (toggle) ----------
  chaptersBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    popoverOpen = !popoverOpen;
    chaptersPopover.style.display = popoverOpen ? "flex" : "none";
    if (popoverOpen) renderPopover();
  });

  // Close popover on outside click
  function onDocClick(e: MouseEvent) {
    if (popoverOpen && !chaptersPopover.contains(e.target as Node) && e.target !== chaptersBtn) {
      popoverOpen = false;
      chaptersPopover.style.display = "none";
    }
  }
  document.addEventListener("click", onDocClick);

  async function load() {
    doc = await getDocument(docId);
    docTitle.textContent = doc.name;
    updatePage();
  }

  function updatePage() {
    if (!doc) return;
    viewer.setImage(pageImageUrl(docId, page));
    pageInfo.textContent = `${page} / ${doc.page_count}`;
    prevBtn.disabled = page <= 1;
    nextBtn.disabled = page >= doc.page_count;
    loadTranscription();
    updateChapterBanner();
  }

  function updateChapterBanner() {
    if (!doc) return;
    const chapters = doc.chapters || [];
    const current = chapters.find((ch) => page >= ch.page_start && page <= ch.page_end);
    if (current) {
      chapterBanner.style.display = "flex";
      chapterBanner.innerHTML = `
        <a href="/doc/${docId}/chapter/${current.id}" id="banner-link" class="chapter-banner-link">
          ${current.title}
        </a>
        <span class="chapter-banner-meta">pp. ${current.page_start}-${current.page_end}</span>
      `;
      chapterBanner.querySelector("#banner-link")!.addEventListener("click", (e) => {
        e.preventDefault();
        navigate(`/doc/${docId}/chapter/${current.id}`);
      });
    } else {
      chapterBanner.style.display = "none";
    }
  }

  async function loadTranscription() {
    const t = await getTranscription(docId, page);
    renderTranscription(t);
  }

  function renderTranscription(t: Transcription | null) {
    if (!t) {
      rightPane.innerHTML = `<div class="empty">No transcription for this page</div>`;
      return;
    }
    rightPane.innerHTML = `
      <div style="margin-bottom:8px">
        <span class="badge">${t.engine.toUpperCase()} / ${t.provider}</span>
        ${t.model ? `<span class="badge">${t.model}</span>` : ""}
        ${t.duration_ms ? `<span class="badge">${t.duration_ms}ms</span>` : ""}
      </div>
      <div class="markdown">${marked.parse(t.markdown)}</div>
    `;
  }

  // ---------- Chapters popover with drag-to-reorder ----------
  function renderPopover() {
    if (!doc) return;
    const chapters = doc.chapters || [];
    chaptersPopover.innerHTML = `
      <div class="popover-header">
        <span>Chapters</span>
      </div>
      <div id="chapter-drag-list" class="chapter-drag-list">
        ${chapters.length === 0 ? '<div class="sidebar-empty">No chapters yet</div>' : ""}
        ${chapters.map((ch, i) => `
          <div class="chapter-drag-item" data-index="${i}" data-id="${ch.id}" draggable="true">
            <span class="drag-handle" title="Drag to reorder">&#x2630;</span>
            <a href="/doc/${docId}/chapter/${ch.id}" class="chapter-drag-link">
              <span class="sidebar-item-title">${ch.title}</span>
              <span class="sidebar-item-meta">pp. ${ch.page_start}-${ch.page_end}</span>
            </a>
          </div>
        `).join("")}
      </div>
    `;

    // Wire chapter links
    chaptersPopover.querySelectorAll<HTMLAnchorElement>(".chapter-drag-link").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        popoverOpen = false;
        chaptersPopover.style.display = "none";
        navigate(a.getAttribute("href")!);
      });
    });

    // Drag and drop reorder
    const list = chaptersPopover.querySelector<HTMLElement>("#chapter-drag-list")!;
    let dragIndex: number | null = null;

    list.addEventListener("dragstart", (e) => {
      const item = (e.target as HTMLElement).closest(".chapter-drag-item") as HTMLElement | null;
      if (!item) return;
      dragIndex = parseInt(item.dataset.index!);
      item.classList.add("dragging");
      e.dataTransfer!.effectAllowed = "move";
    });

    list.addEventListener("dragend", (e) => {
      const item = (e.target as HTMLElement).closest(".chapter-drag-item") as HTMLElement | null;
      if (item) item.classList.remove("dragging");
      dragIndex = null;
    });

    list.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer!.dropEffect = "move";
      const afterEl = getDragAfterElement(list, e.clientY);
      const dragging = list.querySelector(".dragging");
      if (!dragging) return;
      if (afterEl) {
        list.insertBefore(dragging, afterEl);
      } else {
        list.appendChild(dragging);
      }
    });

    list.addEventListener("drop", async (e) => {
      e.preventDefault();
      if (dragIndex === null || !doc) return;
      // Read new order from DOM
      const items = list.querySelectorAll<HTMLElement>(".chapter-drag-item");
      const chapters = doc.chapters || [];
      const updates: Promise<any>[] = [];
      items.forEach((item, newIndex) => {
        const id = item.dataset.id!;
        const ch = chapters.find((c) => c.id === id);
        if (ch && ch.order !== newIndex + 1) {
          updates.push(updateChapter(docId, id, { order: newIndex + 1 }));
        }
      });
      if (updates.length > 0) {
        await Promise.all(updates);
        doc = await getDocument(docId);
        renderPopover();
      }
    });
  }

  function getDragAfterElement(list: HTMLElement, y: number): Element | null {
    const items = [...list.querySelectorAll<HTMLElement>(".chapter-drag-item:not(.dragging)")];
    let closest: Element | null = null;
    let closestOffset = Number.NEGATIVE_INFINITY;
    for (const item of items) {
      const box = item.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closestOffset) {
        closestOffset = offset;
        closest = item;
      }
    }
    return closest;
  }

  prevBtn.addEventListener("click", () => { if (page > 1) { page--; updatePage(); } });
  nextBtn.addEventListener("click", () => { if (doc && page < doc.page_count) { page++; updatePage(); } });

  function onKey(e: KeyboardEvent) {
    if (e.metaKey || e.ctrlKey) return; // let zoom-pan handle Cmd keys
    if (e.key === "ArrowLeft") prevBtn.click();
    if (e.key === "ArrowRight") nextBtn.click();
  }
  document.addEventListener("keydown", onKey);

  newChapterBtn.addEventListener("click", () => showNewChapterModal());

  function showNewChapterModal() {
    if (!doc) return;
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `
      <div class="modal">
        <h2>New Chapter</h2>
        <div class="field">
          <label>Title</label>
          <input id="ch-title" type="text" placeholder="e.g. 第14課 男の料理と市民権" />
        </div>
        <div class="row">
          <div class="field grow">
            <label>Start page</label>
            <input id="ch-start" type="number" min="1" max="${doc.page_count}" value="${page}" />
          </div>
          <div class="field grow">
            <label>End page</label>
            <input id="ch-end" type="number" min="1" max="${doc.page_count}" value="${Math.min(page + 9, doc.page_count)}" />
          </div>
          <div class="field grow">
            <label>Order</label>
            <input id="ch-order" type="number" min="0" value="${(doc.chapters?.length ?? 0) + 1}" />
          </div>
        </div>
        <div class="row">
          <div class="grow"></div>
          <button id="ch-cancel">Cancel</button>
          <button id="ch-save">Create</button>
        </div>
        <div id="ch-error" class="error"></div>
      </div>
    `;
    document.body.appendChild(bg);

    bg.querySelector("#ch-cancel")!.addEventListener("click", () => bg.remove());
    bg.addEventListener("click", (e) => { if (e.target === bg) bg.remove(); });

    bg.querySelector("#ch-save")!.addEventListener("click", async () => {
      const title = (bg.querySelector<HTMLInputElement>("#ch-title")!).value.trim();
      const startPage = parseInt((bg.querySelector<HTMLInputElement>("#ch-start")!).value);
      const endPage = parseInt((bg.querySelector<HTMLInputElement>("#ch-end")!).value);
      const order = parseInt((bg.querySelector<HTMLInputElement>("#ch-order")!).value);
      const errEl = bg.querySelector<HTMLElement>("#ch-error")!;

      if (!title) { errEl.textContent = "Title is required"; return; }
      if (isNaN(startPage) || isNaN(endPage)) { errEl.textContent = "Invalid page numbers"; return; }

      try {
        const ch = await createChapter(docId, {
          title, page_start: startPage, page_end: endPage, order,
        });
        bg.remove();
        doc = await getDocument(docId);
        navigate(`/doc/${docId}/chapter/${ch.id}`);
      } catch (e: any) {
        errEl.textContent = e.message;
      }
    });
  }

  load();

  return () => {
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("click", onDocClick);
    viewer.destroy();
  };
}
