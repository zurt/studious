import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Region } from "../src/api";
import { setRegionReferences } from "../src/api";
import {
  createReferenceResolver,
  openReferencePicker,
  regionSnippet,
  renderReferenceLabel,
  type ReferenceInfo,
} from "../src/modules/reference-picker";

function region(over: Partial<Region> = {}): Region {
  return {
    id: "r1",
    chapter_id: "c1",
    page: 81,
    bbox: [0, 0.1, 1, 0.3],
    tag: "reading_passage",
    label: "",
    transcription_md: "# 健康病が心身をむしばむ\n\n本文",
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const here = { docId: "d1", chapterId: "c1" };

function info(over: Partial<ReferenceInfo> = {}): ReferenceInfo {
  return {
    ref: { doc_id: "d1", chapter_id: "c1", region_id: "r1" },
    region: region(),
    docName: "生きた素材で学ぶ.pdf",
    chapterTitle: "第5課",
    ...over,
  };
}

describe("regionSnippet", () => {
  it("uses the first non-empty line without markdown markers", () => {
    expect(regionSnippet(region())).toBe("健康病が心身をむしばむ");
  });

  it("truncates long lines", () => {
    expect(regionSnippet(region({ transcription_md: "あ".repeat(50) }), 10)).toBe("あ".repeat(10) + "…");
  });

  it("is empty for an untranscribed region", () => {
    expect(regionSnippet(region({ transcription_md: null }))).toBe("");
  });
});

describe("renderReferenceLabel", () => {
  it("shows only the page for a same-chapter reference", () => {
    const el = renderReferenceLabel(info(), here);
    expect(el.querySelector(".reference-where")!.textContent).toBe("p.81");
    expect(el.querySelector(".reference-what")!.textContent).toBe("健康病が心身をむしばむ");
  });

  it("adds the chapter for another chapter, and the document for another document", () => {
    const otherChapter = renderReferenceLabel(
      info({ ref: { doc_id: "d1", chapter_id: "c2", region_id: "r1" } }),
      here,
    );
    expect(otherChapter.querySelector(".reference-where")!.textContent).toBe("第5課 › p.81");

    const otherDoc = renderReferenceLabel(
      info({ ref: { doc_id: "d2", chapter_id: "c9", region_id: "r1" } }),
      here,
    );
    expect(otherDoc.querySelector(".reference-where")!.textContent).toBe("生きた素材で学ぶ.pdf › 第5課 › p.81");
  });

  it("prefers the region label over the snippet", () => {
    const el = renderReferenceLabel(info({ region: region({ label: "本文" }) }), here);
    expect(el.querySelector(".reference-what")!.textContent).toBe("本文");
  });

  it("flags untranscribed and missing targets", () => {
    const untranscribed = renderReferenceLabel(info({ region: region({ transcription_md: null }) }), here);
    expect(untranscribed.querySelector(".reference-untranscribed")).not.toBeNull();

    const missing = renderReferenceLabel(info({ region: null }), here);
    expect(missing.classList.contains("is-missing")).toBe(true);
  });
});

describe("with fetch mocked", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("setRegionReferences PUTs the whole list", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "ex1", references: [] }));
    const refs = [{ doc_id: "d1", chapter_id: "c1", region_id: "r1" }];
    await setRegionReferences("d1", "c1", "ex1", refs);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/documents/d1/chapters/c1/regions/ex1/references");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ references: refs });
  });

  it("resolver marks a reference missing when its region is gone, and caches it", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/documents/d2") {
        return jsonResponse({ id: "d2", name: "other.pdf", chapters: [{ id: "c9", title: "Unit 3" }] });
      }
      if (url === "/api/documents/d2/chapters/c9/regions") return jsonResponse([region({ id: "keep" })]);
      return jsonResponse({ detail: "not found" }, 404);
    });
    const resolver = createReferenceResolver();
    const found = await resolver.resolve({ doc_id: "d2", chapter_id: "c9", region_id: "keep" });
    const gone = await resolver.resolve({ doc_id: "d2", chapter_id: "c9", region_id: "gone" });
    expect(found.region?.id).toBe("keep");
    expect(found.chapterTitle).toBe("Unit 3");
    expect(gone.region).toBeNull();
    expect(resolver.peek({ doc_id: "d2", chapter_id: "c9", region_id: "keep" })).toBe(found);
    // Document and region list were each fetched once.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("picker adds a whole page in reading order and drops missing entries on save", async () => {
    const top = region({ id: "top", bbox: [0, 0.1, 1, 0.3], transcription_md: "上の段落" });
    const bottom = region({ id: "bottom", bbox: [0, 0.5, 1, 0.7], transcription_md: "下の段落" });
    const exercise = region({ id: "ex", tag: "exercises", transcription_md: "(1) 質問" });
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/documents") return jsonResponse([{ id: "d1", name: "book.pdf" }]);
      if (url === "/api/documents/d1") {
        return jsonResponse({ id: "d1", name: "book.pdf", chapters: [{ id: "c1", title: "5", order: 0, page_start: 77, page_end: 94 }] });
      }
      // Listed out of reading order on purpose.
      if (url === "/api/documents/d1/chapters/c1/regions") return jsonResponse([bottom, exercise, top]);
      return jsonResponse({ detail: "not found" }, 404);
    });

    const result = openReferencePicker({
      docId: "d1",
      chapterId: "c1",
      initial: [{ doc_id: "d1", chapter_id: "c1", region_id: "deleted" }],
    });
    await vi.waitFor(() => {
      expect(document.querySelectorAll(".reference-picker-candidate")).toHaveLength(2);
    });
    // Exercises regions are not offered as candidates.
    expect(document.querySelector(".reference-picker-candidates")!.textContent).not.toContain("質問");
    expect(document.querySelector(".reference-picker-tray .is-missing")).not.toBeNull();

    document.querySelector<HTMLButtonElement>(".reference-picker-add-page")!.click();
    const tray = [...document.querySelectorAll(".reference-picker-tray .reference-what")].map((e) => e.textContent);
    expect(tray).toEqual(["上の段落", "下の段落"]);

    document.querySelector<HTMLButtonElement>("#reference-save")!.click();
    expect(await result).toEqual([
      { doc_id: "d1", chapter_id: "c1", region_id: "top" },
      { doc_id: "d1", chapter_id: "c1", region_id: "bottom" },
    ]);
  });

  it("picker shows the newly chosen document even if the initial load finishes later", async () => {
    let releaseInitialDoc!: () => void;
    const initialDocGate = new Promise<void>((r) => { releaseInitialDoc = r; });
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/documents") {
        return jsonResponse([{ id: "d1", name: "book.pdf" }, { id: "d2", name: "reader.pdf" }]);
      }
      if (url === "/api/documents/d1") {
        await initialDocGate; // the initial document load is slow
        return jsonResponse({ id: "d1", name: "book.pdf", chapters: [{ id: "c1", title: "5", order: 0, page_start: 1, page_end: 9 }] });
      }
      if (url === "/api/documents/d2") {
        return jsonResponse({ id: "d2", name: "reader.pdf", chapters: [{ id: "c9", title: "読み物の課", order: 0, page_start: 1, page_end: 1 }] });
      }
      if (url === "/api/documents/d1/chapters/c1/regions") return jsonResponse([region({ id: "old", transcription_md: "古い" })]);
      if (url === "/api/documents/d2/chapters/c9/regions") return jsonResponse([region({ id: "new", label: "読み物" })]);
      return jsonResponse({ detail: "not found" }, 404);
    });

    const result = openReferencePicker({ docId: "d1", chapterId: "c1", initial: [] });
    const docSelect = document.querySelector<HTMLSelectElement>(".reference-picker-doc")!;
    await vi.waitFor(() => expect(docSelect.options).toHaveLength(2));
    docSelect.value = "d2";
    docSelect.dispatchEvent(new Event("change"));
    await vi.waitFor(() => {
      expect(document.querySelector(".reference-picker-candidates")!.textContent).toContain("読み物");
    });
    releaseInitialDoc();
    await new Promise((r) => setTimeout(r, 20));
    expect(document.querySelector(".reference-picker-candidates")!.textContent).toContain("読み物");
    expect(document.querySelector<HTMLSelectElement>(".reference-picker-chapter")!.value).toBe("c9");

    document.querySelector<HTMLButtonElement>("#reference-cancel")!.click();
    expect(await result).toBeNull();
  });

  it("picker reorders and removes entries, and Escape cancels", async () => {
    const a = region({ id: "a", transcription_md: "A" });
    const b = region({ id: "b", page: 82, transcription_md: "B" });
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/documents") return jsonResponse([{ id: "d1", name: "book.pdf" }]);
      if (url === "/api/documents/d1") {
        return jsonResponse({ id: "d1", name: "book.pdf", chapters: [{ id: "c1", title: "5", order: 0, page_start: 77, page_end: 94 }] });
      }
      if (url === "/api/documents/d1/chapters/c1/regions") return jsonResponse([a, b]);
      return jsonResponse({ detail: "not found" }, 404);
    });
    const refA = { doc_id: "d1", chapter_id: "c1", region_id: "a" };
    const refB = { doc_id: "d1", chapter_id: "c1", region_id: "b" };

    const saved = openReferencePicker({ docId: "d1", chapterId: "c1", initial: [refA, refB] });
    await vi.waitFor(() => {
      expect(document.querySelectorAll(".reference-picker-candidate.is-selected")).toHaveLength(2);
    });
    document.querySelector<HTMLButtonElement>('.reference-picker-tray button[title="Move down"]')!.click();
    document.querySelector<HTMLButtonElement>("#reference-save")!.click();
    expect(await saved).toEqual([refB, refA]);

    const cancelled = openReferencePicker({ docId: "d1", chapterId: "c1", initial: [refA] });
    await vi.waitFor(() => {
      expect(document.querySelectorAll(".reference-picker-candidate")).toHaveLength(2);
    });
    document.querySelector<HTMLButtonElement>('.reference-picker-tray button[title="Remove"]')!.click();
    expect(document.querySelectorAll(".reference-picker-candidate.is-selected")).toHaveLength(0);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(await cancelled).toBeNull();
    expect(document.querySelector(".reference-picker")).toBeNull();
  });
});
