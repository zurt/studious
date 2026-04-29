import type { Region } from "../api";

export type RegionListOptions = {
  onTranscribe: (region: Region) => void;
  onDelete: (region: Region) => void;
  onSelect: (region: Region) => void;
  transcribingIds?: Set<string>;
};

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

    if (!region.transcription_md) {
      const transcribeBtn = document.createElement("button");
      const inFlight = opts.transcribingIds?.has(region.id);
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
    }

    const deleteBtn = document.createElement("button");
    deleteBtn.textContent = "Delete";
    deleteBtn.className = "btn-danger";
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      opts.onDelete(region);
    });
    actions.appendChild(deleteBtn);

    card.appendChild(actions);
    container.appendChild(card);
  }
}
