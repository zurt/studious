import {
  getDocument, listDocuments, listRegions,
  type Chapter, type DocMeta, type Region, type RegionReference,
} from "../api";

// Reading references (Phase 2.5): an exercises region cites the
// reading_passage regions it asks about — possibly in another chapter or
// another document — so exercise completion gets them as context. This
// module holds the picker modal plus the label helpers the chapter view's
// References section shares with it.

export type ReferenceInfo = {
  ref: RegionReference;
  region: Region | null; // null when the target no longer resolves
  docName: string;
  chapterTitle: string;
};

export type ReferenceResolver = {
  getDoc(docId: string): Promise<DocMeta | null>;
  getRegions(docId: string, chapterId: string): Promise<Region[]>;
  resolve(ref: RegionReference): Promise<ReferenceInfo>;
  /** A previously resolved info, without fetching. */
  peek(ref: RegionReference): ReferenceInfo | undefined;
};

export function refKey(ref: RegionReference): string {
  return `${ref.doc_id}:${ref.chapter_id}:${ref.region_id}`;
}

/** Fetches (and caches) the documents/region lists needed to label references. */
export function createReferenceResolver(): ReferenceResolver {
  const docs = new Map<string, Promise<DocMeta | null>>();
  const regionLists = new Map<string, Promise<Region[]>>();
  const infos = new Map<string, ReferenceInfo>();

  function getDoc(docId: string): Promise<DocMeta | null> {
    let p = docs.get(docId);
    if (!p) {
      p = getDocument(docId).catch(() => null);
      docs.set(docId, p);
    }
    return p;
  }

  function getRegions(docId: string, chapterId: string): Promise<Region[]> {
    const key = `${docId}:${chapterId}`;
    let p = regionLists.get(key);
    if (!p) {
      p = listRegions(docId, chapterId).catch(() => []);
      regionLists.set(key, p);
    }
    return p;
  }

  async function resolve(ref: RegionReference): Promise<ReferenceInfo> {
    const [doc, regs] = await Promise.all([getDoc(ref.doc_id), getRegions(ref.doc_id, ref.chapter_id)]);
    const chapter = doc?.chapters?.find((c) => c.id === ref.chapter_id);
    const info: ReferenceInfo = {
      ref,
      region: regs.find((r) => r.id === ref.region_id) ?? null,
      docName: doc?.name ?? "",
      chapterTitle: chapter?.title ?? "",
    };
    infos.set(refKey(ref), info);
    return info;
  }

  return { getDoc, getRegions, resolve, peek: (ref) => infos.get(refKey(ref)) };
}

/** First non-empty line of a region's transcription, markdown markers stripped. */
export function regionSnippet(region: Region, max = 40): string {
  const line = (region.transcription_md || "")
    .split("\n")
    .map((l) => l.replace(/^[#>*\-\s]+/, "").trim())
    .find((l) => l) || "";
  return line.length > max ? line.slice(0, max) + "…" : line;
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "…" : s;
}

/**
 * Label for one reference: where it is (document and chapter only when they
 * differ from `here`, then the page) and what it is (region label, else the
 * transcription's first line).
 */
export function renderReferenceLabel(
  info: ReferenceInfo,
  here: { docId: string; chapterId: string },
): HTMLElement {
  const el = document.createElement("span");
  el.className = "reference-label";
  if (!info.region) {
    el.classList.add("is-missing");
    el.textContent = "Missing — the region was deleted or moved";
    el.title = "Ignored as context; removed the next time references are saved";
    return el;
  }
  const where: string[] = [];
  if (info.ref.doc_id !== here.docId) where.push(truncate(info.docName || info.ref.doc_id, 28));
  if (info.ref.doc_id !== here.docId || info.ref.chapter_id !== here.chapterId) {
    where.push(info.chapterTitle || "?");
  }
  where.push(`p.${info.region.page}`);
  const whereEl = document.createElement("span");
  whereEl.className = "reference-where";
  whereEl.textContent = where.join(" › ");
  if (info.ref.doc_id !== here.docId) whereEl.title = info.docName;
  const what = document.createElement("span");
  what.className = "reference-what";
  what.lang = "ja";
  const title = info.region.label || regionSnippet(info.region);
  what.textContent = title || "(untitled)";
  el.append(whereEl, what);
  if (!info.region.transcription_md) {
    const warn = document.createElement("span");
    warn.className = "reference-untranscribed";
    warn.textContent = "not transcribed";
    warn.title = "Skipped as context until this region is transcribed";
    el.appendChild(warn);
  }
  return el;
}

function sortedChapters(doc: DocMeta | null): Chapter[] {
  return [...(doc?.chapters || [])].sort((a, b) => a.order - b.order || a.page_start - b.page_start);
}

function readingOrder(a: Region, b: Region): number {
  return a.page - b.page || a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0];
}

export type ReferencePickerOptions = {
  /** Where the exercises region lives — the browse pane starts here. */
  docId: string;
  chapterId: string;
  initial: RegionReference[];
};

/**
 * Modal for choosing an ordered list of reading_passage regions from any
 * document/chapter. Resolves the new list on Save, or null on Cancel.
 */
export function openReferencePicker(opts: ReferencePickerOptions): Promise<RegionReference[] | null> {
  const here = { docId: opts.docId, chapterId: opts.chapterId };
  // Fresh per open, so region lists reflect transcriptions done since the
  // chapter view loaded.
  const resolver = createReferenceResolver();

  return new Promise((resolve) => {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `
      <div class="modal reference-picker" role="dialog" aria-label="Reading references">
        <h2>Reading references</h2>
        <p class="reference-picker-intro">Pick the reading passage regions these exercises ask about. They're given to exercise completion as context, in this order.</p>
        <div class="reference-picker-body">
          <div class="reference-picker-browse">
            <div class="reference-picker-selects">
              <select class="reference-picker-doc" aria-label="Document"></select>
              <select class="reference-picker-chapter" aria-label="Chapter"></select>
            </div>
            <div class="reference-picker-candidates"><p class="reference-picker-empty">Loading…</p></div>
          </div>
          <div class="reference-picker-selected">
            <div class="reference-picker-selected-header">Selected <span class="reference-picker-count"></span></div>
            <ol class="reference-picker-tray"></ol>
          </div>
        </div>
        <div class="row">
          <div class="grow"></div>
          <button id="reference-cancel">Cancel</button>
          <button id="reference-save">Save</button>
        </div>
      </div>
    `;
    (document.fullscreenElement ?? document.body).appendChild(bg);

    const docSelect = bg.querySelector<HTMLSelectElement>(".reference-picker-doc")!;
    const chapterSelect = bg.querySelector<HTMLSelectElement>(".reference-picker-chapter")!;
    const candidatesEl = bg.querySelector<HTMLElement>(".reference-picker-candidates")!;
    const trayEl = bg.querySelector<HTMLOListElement>(".reference-picker-tray")!;
    const countEl = bg.querySelector<HTMLElement>(".reference-picker-count")!;

    let selected: ReferenceInfo[] = [];
    let browseDocId = opts.docId;
    let browseChapterId = opts.chapterId;
    let browseRegions: Region[] = [];
    let browseToken = 0;
    let docToken = 0;
    // Loaded document metas (with chapters) by id, for synchronous labels.
    const loadedDocs = new Map<string, DocMeta | null>();

    const isSelected = (ref: RegionReference) => selected.some((s) => refKey(s.ref) === refKey(ref));

    function close(result: RegionReference[] | null) {
      document.removeEventListener("keydown", onKey);
      bg.remove();
      resolve(result);
    }
    // No close-on-backdrop-click: a stray click would silently discard an
    // in-progress selection.
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close(null);
    }

    function renderTray() {
      countEl.textContent = selected.length ? `(${selected.length})` : "";
      trayEl.innerHTML = "";
      if (selected.length === 0) {
        const empty = document.createElement("li");
        empty.className = "reference-picker-empty";
        empty.textContent = "Nothing selected yet.";
        trayEl.appendChild(empty);
        return;
      }
      selected.forEach((info, i) => {
        // The flex row sits inside the <li> so the list keeps its numbering.
        const li = document.createElement("li");
        li.className = "reference-picker-item";
        const row = document.createElement("div");
        row.className = "reference-picker-item-row";
        row.appendChild(renderReferenceLabel(info, here));
        li.appendChild(row);
        const actions = document.createElement("span");
        actions.className = "reference-picker-item-actions";
        const mk = (text: string, title: string, disabled: boolean, fn: () => void) => {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "icon-btn";
          b.textContent = text;
          b.title = title;
          b.setAttribute("aria-label", title);
          b.disabled = disabled;
          b.addEventListener("click", fn);
          actions.appendChild(b);
        };
        mk("↑", "Move up", i === 0, () => {
          [selected[i - 1], selected[i]] = [selected[i], selected[i - 1]];
          renderAll();
        });
        mk("↓", "Move down", i === selected.length - 1, () => {
          [selected[i + 1], selected[i]] = [selected[i], selected[i + 1]];
          renderAll();
        });
        mk("✕", "Remove", false, () => {
          selected.splice(i, 1);
          renderAll();
        });
        row.appendChild(actions);
        trayEl.appendChild(li);
      });
    }

    function infoFor(region: Region): ReferenceInfo {
      const doc = loadedDocs.get(browseDocId) ?? null;
      const chapter = doc?.chapters?.find((c) => c.id === browseChapterId);
      return {
        ref: { doc_id: browseDocId, chapter_id: browseChapterId, region_id: region.id },
        region,
        docName: doc?.name ?? "",
        chapterTitle: chapter?.title ?? "",
      };
    }

    function renderCandidates() {
      candidatesEl.innerHTML = "";
      const readings = browseRegions.filter((r) => r.tag === "reading_passage").sort(readingOrder);
      if (readings.length === 0) {
        candidatesEl.innerHTML = `<p class="reference-picker-empty">No reading passage regions in this chapter.</p>`;
        return;
      }
      const pages = [...new Set(readings.map((r) => r.page))];
      for (const p of pages) {
        const onPage = readings.filter((r) => r.page === p);
        const group = document.createElement("div");
        group.className = "reference-picker-page";
        const header = document.createElement("div");
        header.className = "reference-picker-page-header";
        const title = document.createElement("span");
        title.textContent = `p.${p}`;
        header.appendChild(title);
        const unselected = onPage.filter((r) => !isSelected(infoFor(r).ref));
        if (onPage.length > 1) {
          const addAll = document.createElement("button");
          addAll.type = "button";
          addAll.className = "reference-picker-add-page";
          addAll.textContent = unselected.length ? `Add all ${onPage.length}` : "All added";
          addAll.disabled = unselected.length === 0;
          addAll.addEventListener("click", () => {
            selected.push(...unselected.map(infoFor));
            renderAll();
          });
          header.appendChild(addAll);
        }
        group.appendChild(header);
        for (const region of onPage) {
          const info = infoFor(region);
          const on = isSelected(info.ref);
          const row = document.createElement("button");
          row.type = "button";
          row.className = "reference-picker-candidate" + (on ? " is-selected" : "");
          row.setAttribute("aria-pressed", String(on));
          row.title = on ? "Remove from references" : "Add to references";
          const mark = document.createElement("span");
          mark.className = "reference-picker-mark";
          mark.textContent = on ? "✓" : "+";
          row.append(mark, renderReferenceLabel(info, { docId: browseDocId, chapterId: browseChapterId }));
          row.addEventListener("click", () => {
            if (on) selected = selected.filter((s) => refKey(s.ref) !== refKey(info.ref));
            else selected.push(info);
            renderAll();
          });
          group.appendChild(row);
        }
        candidatesEl.appendChild(group);
      }
    }

    function renderAll() {
      renderTray();
      renderCandidates();
    }

    async function loadChapter() {
      const token = ++browseToken;
      candidatesEl.innerHTML = `<p class="reference-picker-empty">Loading…</p>`;
      const regs = browseChapterId ? await resolver.getRegions(browseDocId, browseChapterId) : [];
      if (token !== browseToken) return;
      browseRegions = regs;
      renderCandidates();
    }

    // Token-guarded like loadChapter: switching documents while an earlier
    // load is in flight (e.g. the initial one) must not let the stale load
    // finish last and repopulate the chapter list for the wrong document.
    async function loadDoc(docId: string, preferChapterId?: string) {
      const token = ++docToken;
      const doc = await resolver.getDoc(docId);
      if (token !== docToken) return;
      loadedDocs.set(docId, doc);
      const chapters = sortedChapters(doc);
      chapterSelect.innerHTML = "";
      for (const c of chapters) {
        const opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = `${c.title} (pp.${c.page_start}–${c.page_end})`;
        chapterSelect.appendChild(opt);
      }
      browseChapterId = chapters.find((c) => c.id === preferChapterId)?.id ?? chapters[0]?.id ?? "";
      chapterSelect.value = browseChapterId;
      chapterSelect.disabled = chapters.length === 0;
      await loadChapter();
    }

    docSelect.addEventListener("change", () => {
      browseDocId = docSelect.value;
      void loadDoc(browseDocId);
    });
    chapterSelect.addEventListener("change", () => {
      browseChapterId = chapterSelect.value;
      void loadChapter();
    });
    bg.querySelector("#reference-cancel")!.addEventListener("click", () => close(null));
    // A reference whose target no longer resolves is dropped on save — the
    // backend rejects unknown targets, so keeping it would block every edit.
    bg.querySelector("#reference-save")!.addEventListener("click", () => {
      close(selected.filter((s) => s.region).map((s) => s.ref));
    });
    document.addEventListener("keydown", onKey);

    renderTray();
    void (async () => {
      const [docs, initialInfos] = await Promise.all([
        listDocuments().catch(() => [] as DocMeta[]),
        Promise.all(opts.initial.map((ref) => resolver.resolve(ref))),
      ]);
      selected = initialInfos;
      for (const d of docs) {
        const opt = document.createElement("option");
        opt.value = d.id;
        opt.textContent = d.name;
        docSelect.appendChild(opt);
      }
      docSelect.value = browseDocId;
      renderTray();
      await loadDoc(browseDocId, browseChapterId);
    })();
  });
}
