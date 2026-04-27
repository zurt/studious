import {
  getDocument, getTranscription, pageImageUrl, createChapter,
  type DocMeta, type Transcription, type Chapter,
} from "../api";
import { generateCorrelationId } from "../logger";
import { navigate } from "../router";
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
          <button id="new-chapter-btn">New Chapter</button>
        </div>
      </div>
      <div class="pane-row">
        <div class="pane left" style="display:flex">
          <div id="chapter-sidebar" class="chapter-sidebar"></div>
          <div style="flex:1; overflow:auto; padding:12px">
            <img id="page-img" class="page-img" alt="Page" />
          </div>
        </div>
        <div class="pane" id="right-pane">
          <div class="empty">Select a page to view</div>
        </div>
      </div>
    </div>
  `;

  const backLink = container.querySelector<HTMLAnchorElement>("#back-link")!;
  backLink.addEventListener("click", (e) => { e.preventDefault(); navigate("/"); });

  const docTitle = container.querySelector<HTMLElement>("#doc-title")!;
  const pageInfo = container.querySelector<HTMLElement>("#page-info")!;
  const prevBtn = container.querySelector<HTMLButtonElement>("#prev-btn")!;
  const nextBtn = container.querySelector<HTMLButtonElement>("#next-btn")!;
  const newChapterBtn = container.querySelector<HTMLButtonElement>("#new-chapter-btn")!;
  const pageImg = container.querySelector<HTMLImageElement>("#page-img")!;
  const rightPane = container.querySelector<HTMLElement>("#right-pane")!;
  const sidebar = container.querySelector<HTMLElement>("#chapter-sidebar")!;

  let doc: DocMeta | null = null;
  let page = 1;

  async function load() {
    doc = await getDocument(docId);
    docTitle.textContent = doc.name;
    updatePage();
    renderSidebar();
  }

  function updatePage() {
    if (!doc) return;
    pageImg.src = pageImageUrl(docId, page);
    pageInfo.textContent = `${page} / ${doc.page_count}`;
    prevBtn.disabled = page <= 1;
    nextBtn.disabled = page >= doc.page_count;
    loadTranscription();
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

  function renderSidebar() {
    if (!doc) return;
    const chapters = doc.chapters || [];
    sidebar.innerHTML = `
      <div class="sidebar-header">Chapters</div>
      ${chapters.length === 0 ? '<div class="sidebar-empty">No chapters yet</div>' : ""}
      ${chapters.map((ch) => `
        <a href="/doc/${docId}/chapter/${ch.id}" class="sidebar-item" data-chapter-id="${ch.id}">
          <div class="sidebar-item-title">${ch.title}</div>
          <div class="sidebar-item-meta">pp. ${ch.page_start}-${ch.page_end}</div>
        </a>
      `).join("")}
    `;
    sidebar.querySelectorAll<HTMLAnchorElement>(".sidebar-item").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        navigate(a.getAttribute("href")!);
      });
    });
  }

  prevBtn.addEventListener("click", () => { if (page > 1) { page--; updatePage(); } });
  nextBtn.addEventListener("click", () => { if (doc && page < doc.page_count) { page++; updatePage(); } });

  // Keyboard navigation
  function onKey(e: KeyboardEvent) {
    if (e.key === "ArrowLeft") prevBtn.click();
    if (e.key === "ArrowRight") nextBtn.click();
  }
  document.addEventListener("keydown", onKey);

  // New chapter modal
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
        renderSidebar();
        navigate(`/doc/${docId}/chapter/${ch.id}`);
      } catch (e: any) {
        errEl.textContent = e.message;
      }
    });
  }

  load();

  return () => {
    document.removeEventListener("keydown", onKey);
  };
}
