import { listDocuments, uploadDocument, pageImageUrl, type DocMeta } from "../api";
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

  return card;
}
