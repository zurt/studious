import { marked } from "marked";
import type { Region } from "../api";

export type RegionListOptions = {
  onTranscribe: (region: Region) => void;
  onRetranscribe: (region: Region) => void;
  onDelete: (region: Region) => void;
  onSelect: (region: Region) => void;
  onHover?: (region: Region | null) => void;
  transcribingIds?: Set<string>;
};

const ICON_TRASH = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>`;
export const ICON_REDO = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`;
const ICON_COPY = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
const ICON_CHECK = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>`;

const COPY_TITLE = "Copy to clipboard (Alt/Option for rich text)";

export async function markdownToRichHtml(md: string): Promise<string> {
  const html = await Promise.resolve(marked.parse(md));
  return (html as string).replace(
    /(<\/(?:p|h[1-6]|ul|ol|blockquote|pre|table)>)\s*(<(?:p|h[1-6]|ul|ol|blockquote|pre|table|hr)\b)/gi,
    "$1<p><br></p>$2"
  );
}

export function makeCopyButton(getText: () => string): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.className = "icon-btn";
  btn.title = COPY_TITLE;
  btn.setAttribute("aria-label", "Copy to clipboard");
  btn.innerHTML = ICON_COPY;
  btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const md = getText();
    const wantHtml = e.altKey;
    try {
      if (wantHtml && typeof ClipboardItem !== "undefined") {
        const spaced = await markdownToRichHtml(md);
        await navigator.clipboard.write([
          new ClipboardItem({
            "text/html": new Blob([spaced], { type: "text/html" }),
            "text/plain": new Blob([md], { type: "text/plain" }),
          }),
        ]);
      } else {
        await navigator.clipboard.writeText(md);
      }
      btn.innerHTML = ICON_CHECK;
      btn.title = wantHtml ? "Copied rich text!" : "Copied!";
      setTimeout(() => {
        btn.innerHTML = ICON_COPY;
        btn.title = COPY_TITLE;
      }, 1200);
    } catch {
      btn.title = "Copy failed";
    }
  });
  return btn;
}

const TAG_LABELS: Record<string, string> = {
  reading_passage: "Reading",
  vocab_list: "Vocab",
  grammar_points: "Grammar",
  exercises: "Exercises",
  instructions: "Instructions",
  other: "Other",
};

export function renderRegionList(
  container: HTMLElement,
  regions: Region[],
  selectedId: string | null,
  opts: RegionListOptions
) {
  container.innerHTML = "";

  if (regions.length === 0) {
    container.innerHTML = `<p class="empty">No regions on this page. Draw a rectangle on the image to create one.</p>`;
    return;
  }

  for (const region of regions) {
    const card = document.createElement("div");
    card.className = "region-card" + (region.id === selectedId ? " selected" : "");
    card.addEventListener("click", () => opts.onSelect(region));
    if (opts.onHover) {
      card.addEventListener("mouseenter", () => opts.onHover!(region));
      card.addEventListener("mouseleave", () => opts.onHover!(null));
    }

    const header = document.createElement("div");
    header.className = "region-header";

    const badge = document.createElement("span");
    badge.className = `badge tag-${region.tag}`;
    badge.textContent = TAG_LABELS[region.tag] || region.tag;
    header.appendChild(badge);

    if (region.label) {
      const label = document.createElement("span");
      label.className = "region-label";
      label.textContent = region.label;
      header.appendChild(label);
    }

    card.appendChild(header);

    if (region.transcription_md) {
      const preview = document.createElement("div");
      preview.className = "region-preview";
      preview.textContent = region.transcription_md.slice(0, 120) + (region.transcription_md.length > 120 ? "..." : "");
      card.appendChild(preview);
    }

    const actions = document.createElement("div");
    actions.className = "region-actions";

    const inFlight = opts.transcribingIds?.has(region.id);

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "icon-btn btn-danger";
    deleteBtn.title = "Delete";
    deleteBtn.setAttribute("aria-label", "Delete");
    deleteBtn.innerHTML = ICON_TRASH;
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      opts.onDelete(region);
    });
    actions.appendChild(deleteBtn);

    if (!region.transcription_md) {
      const transcribeBtn = document.createElement("button");
      if (inFlight) {
        transcribeBtn.textContent = "Transcribing…";
        transcribeBtn.disabled = true;
        transcribeBtn.classList.add("is-busy");
      } else {
        transcribeBtn.textContent = "Transcribe";
        transcribeBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          opts.onTranscribe(region);
        });
      }
      actions.appendChild(transcribeBtn);
    } else {
      const retranscribeBtn = document.createElement("button");
      retranscribeBtn.className = "icon-btn";
      retranscribeBtn.title = "Re-transcribe";
      retranscribeBtn.setAttribute("aria-label", "Re-transcribe");
      if (inFlight) {
        retranscribeBtn.disabled = true;
        retranscribeBtn.classList.add("is-busy");
        retranscribeBtn.innerHTML = `<span class="spinner"></span>`;
        retranscribeBtn.title = "Re-transcribing…";
      } else {
        retranscribeBtn.innerHTML = ICON_REDO;
        retranscribeBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          opts.onRetranscribe(region);
        });
      }
      actions.appendChild(retranscribeBtn);

      const copyBtn = makeCopyButton(() => region.transcription_md || "");
      actions.appendChild(copyBtn);
    }

    card.appendChild(actions);
    container.appendChild(card);
  }
}
