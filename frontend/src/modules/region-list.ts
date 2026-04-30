import type { Region } from "../api";

export type RegionListOptions = {
  onTranscribe: (region: Region) => void;
  onRetranscribe: (region: Region) => void;
  onDelete: (region: Region) => void;
  onSelect: (region: Region) => void;
  transcribingIds?: Set<string>;
};

const ICON_TRASH = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>`;
const ICON_REDO = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`;

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
      retranscribeBtn.innerHTML = ICON_REDO;
      if (inFlight) {
        retranscribeBtn.disabled = true;
        retranscribeBtn.classList.add("is-busy");
      } else {
        retranscribeBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          opts.onRetranscribe(region);
        });
      }
      actions.appendChild(retranscribeBtn);
    }

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

    card.appendChild(actions);
    container.appendChild(card);
  }
}
