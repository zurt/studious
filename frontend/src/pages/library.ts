import {
  listDocuments,
  uploadDocument,
  reuploadDocument,
  deleteDocument,
  pageImageUrl,
  type DocMeta,
} from "../api";
import { confirmDialog } from "../modules/confirm";
import { generateCorrelationId, info, error as logError } from "../logger";
import { navigate } from "../router";

export function mountLibrary(_params: Record<string, string>, container: HTMLElement) {
  container.innerHTML = `
    <div class="library">
      <div class="row" style="margin-bottom: 16px">
        <h2 style="margin:0">Documents</h2>
        <div class="grow"></div>
        <button id="upload-btn">Upload PDF / Image</button>
        <input id="upload-input" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp" hidden />
      </div>
      <div id="doc-grid" class="grid"></div>
    </div>
  `;

  const grid = container.querySelector<HTMLElement>("#doc-grid")!;
  const uploadBtn = container.querySelector<HTMLButtonElement>("#upload-btn")!;
  const uploadInput = container.querySelector<HTMLInputElement>("#upload-input")!;

  uploadBtn.addEventListener("click", () => uploadInput.click());
  uploadInput.addEventListener("change", async () => {
    const file = uploadInput.files?.[0];
    if (!file) return;
    uploadBtn.disabled = true;
    uploadBtn.textContent = "Uploading...";
    generateCorrelationId();
    info("Library", "upload_start", { filename: file.name, size: file.size });
    try {
      const doc = await uploadDocument(file);
      info("Library", "upload_done", { doc_id: doc.id });
      navigate(`/doc/${doc.id}`);
    } catch (e: any) {
      logError("Library", "upload_error", { error: e.message });
      alert("Upload failed: " + e.message);
    } finally {
      uploadBtn.disabled = false;
      uploadBtn.textContent = "Upload PDF / Image";
      uploadInput.value = "";
    }
  });

  loadDocs(grid);
}

async function loadDocs(grid: HTMLElement) {
  try {
    const docs = await listDocuments();
    if (docs.length === 0) {
      grid.innerHTML = `<p class="empty">No documents yet. Upload a PDF or image to get started.</p>`;
      return;
    }
    grid.innerHTML = "";
    for (const doc of docs) {
      grid.appendChild(createCard(doc));
    }
  } catch (e: any) {
    grid.innerHTML = `<p class="error">Failed to load documents: ${e.message}</p>`;
  }
}

function createCard(doc: DocMeta): HTMLElement {
  const card = document.createElement("div");
  card.className = "doc-card";
  card.style.cursor = "pointer";
  card.addEventListener("click", () => navigate(`/doc/${doc.id}`));

  const img = document.createElement("img");
  img.src = pageImageUrl(doc.id, 1);
  img.alt = doc.name;
  img.loading = "lazy";
  card.appendChild(img);

  const name = document.createElement("div");
  name.className = "name";
  name.textContent = doc.name;
  card.appendChild(name);

  const meta = document.createElement("div");
  meta.className = "meta";
  const chapterCount = doc.chapters?.length ?? 0;
  meta.textContent = `${doc.source_type.toUpperCase()} - ${doc.page_count} pages` +
    (chapterCount > 0 ? ` - ${chapterCount} ch.` : "");
  card.appendChild(meta);

  card.appendChild(createCardMenu(doc));

  return card;
}

function createCardMenu(doc: DocMeta): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = "card-menu";

  const btn = document.createElement("button");
  btn.className = "card-menu-btn";
  btn.type = "button";
  btn.title = "More actions";
  btn.setAttribute("aria-label", "More actions");
  btn.textContent = "⋮"; // vertical ellipsis
  wrap.appendChild(btn);

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    openCardMenu(doc, btn);
  });

  return wrap;
}

function openCardMenu(doc: DocMeta, anchor: HTMLElement) {
  closeCardMenu();
  const popup = document.createElement("div");
  popup.className = "card-menu-popup";
  popup.dataset.cardMenu = "true";
  popup.innerHTML = `
    <button type="button" data-action="reupload">Re-upload...</button>
    <button type="button" data-action="delete" class="danger">Delete...</button>
  `;
  popup.addEventListener("click", (e) => e.stopPropagation());

  const rect = anchor.getBoundingClientRect();
  popup.style.position = "fixed";
  popup.style.right = `${window.innerWidth - rect.right}px`;
  popup.style.bottom = `${window.innerHeight - rect.top + 4}px`;
  document.body.appendChild(popup);

  const onAway = (e: MouseEvent) => {
    if (!popup.contains(e.target as Node)) closeCardMenu();
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") closeCardMenu();
  };
  setTimeout(() => {
    document.addEventListener("click", onAway);
    document.addEventListener("keydown", onKey);
  }, 0);
  popup.addEventListener("remove" as any, () => {
    document.removeEventListener("click", onAway);
    document.removeEventListener("keydown", onKey);
  });

  popup.querySelector<HTMLButtonElement>('[data-action="reupload"]')!.addEventListener("click", () => {
    closeCardMenu();
    void handleReupload(doc);
  });
  popup.querySelector<HTMLButtonElement>('[data-action="delete"]')!.addEventListener("click", () => {
    closeCardMenu();
    void handleDelete(doc);
  });
}

function closeCardMenu() {
  document.querySelectorAll('[data-card-menu="true"]').forEach((el) => {
    el.dispatchEvent(new Event("remove"));
    el.remove();
  });
}

async function handleReupload(doc: DocMeta) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp";
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    const ok = await confirmDialog(
      "Re-upload document?",
      `Replace "${doc.name}" with "${file.name}"? The current file and rendered pages will be discarded. Chapters and regions are kept, but their page references may no longer match the new file.`,
      "Re-upload",
    );
    if (!ok) return;
    generateCorrelationId();
    info("Library", "reupload_start", { doc_id: doc.id, filename: file.name });
    try {
      await reuploadDocument(doc.id, file);
      info("Library", "reupload_done", { doc_id: doc.id });
      const grid = document.querySelector<HTMLElement>("#doc-grid");
      if (grid) await loadDocs(grid);
    } catch (e: any) {
      logError("Library", "reupload_error", { error: e.message });
      alert("Re-upload failed: " + e.message);
    }
  });
  input.click();
}

async function handleDelete(doc: DocMeta) {
  const ok = await confirmDialog(
    "Delete document?",
    `Permanently delete "${doc.name}"? This removes the original file, all rendered pages, chapters, regions, and transcriptions. This cannot be undone.`,
    "Delete",
  );
  if (!ok) return;
  generateCorrelationId();
  info("Library", "delete_start", { doc_id: doc.id });
  try {
    await deleteDocument(doc.id);
    info("Library", "delete_done", { doc_id: doc.id });
    const grid = document.querySelector<HTMLElement>("#doc-grid");
    if (grid) await loadDocs(grid);
  } catch (e: any) {
    logError("Library", "delete_error", { error: e.message });
    alert("Delete failed: " + e.message);
  }
}
