import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  listDocuments,
  getDocument,
  pageImageUrl,
  getTranscription,
  getBreakdown,
  createChapter,
  uploadDocument,
  deleteDocument,
  reuploadDocument,
  getProviders,
  getCostSummary,
  listChapters,
  getChapter,
  updateChapter,
  deleteChapter,
  createRegion,
  listRegions,
  updateRegion,
  deleteRegion,
  moveRegion,
  transcribeRegion,
  requestBreakdown,
  submitTranscription,
  openJobStream,
} from "../src/api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  describe("correlation header", () => {
    it("includes x-correlation-id on GET requests", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse([]));
      await listDocuments();
      const [, init] = fetchMock.mock.calls[0]!;
      const cid = (init.headers as Record<string, string>)["x-correlation-id"];
      expect(cid).toMatch(/^[0-9a-f]{16}$/);
    });

    it("includes x-correlation-id on POST requests", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ id: "c1" }));
      await createChapter("d1", { title: "Ch", page_start: 1, page_end: 3 });
      const [url, init] = fetchMock.mock.calls[0]!;
      expect(url).toBe("/api/documents/d1/chapters");
      expect(init.method).toBe("POST");
      const headers = init.headers as Record<string, string>;
      expect(headers["x-correlation-id"]).toMatch(/^[0-9a-f]{16}$/);
      expect(headers["Content-Type"]).toBe("application/json");
      expect(JSON.parse(init.body as string)).toEqual({
        title: "Ch",
        page_start: 1,
        page_end: 3,
      });
    });

    it("upload posts FormData with correlation header", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ id: "doc1" }));
      const file = new File(["x"], "x.pdf", { type: "application/pdf" });
      await uploadDocument(file);
      const [url, init] = fetchMock.mock.calls[0]!;
      expect(url).toBe("/api/documents");
      expect(init.method).toBe("POST");
      expect(init.body).toBeInstanceOf(FormData);
      const headers = init.headers as Record<string, string>;
      expect(headers["x-correlation-id"]).toMatch(/^[0-9a-f]{16}$/);
    });
  });

  describe("non-2xx handling", () => {
    it("getDocument throws on 500 with status in message", async () => {
      fetchMock.mockResolvedValueOnce(new Response("nope", { status: 500 }));
      await expect(getDocument("abc")).rejects.toThrow(/500/);
    });

    it("createChapter includes response body in error message", async () => {
      fetchMock.mockResolvedValueOnce(
        new Response("validation error", { status: 422 }),
      );
      await expect(
        createChapter("d", { title: "x", page_start: 1, page_end: 2 }),
      ).rejects.toThrow(/422.*validation error/);
    });

    it("deleteDocument throws on non-2xx", async () => {
      fetchMock.mockResolvedValueOnce(new Response("", { status: 404 }));
      await expect(deleteDocument("d")).rejects.toThrow(/404/);
    });
  });

  describe("getTranscription", () => {
    it("returns null on 404", async () => {
      fetchMock.mockResolvedValueOnce(new Response("", { status: 404 }));
      const result = await getTranscription("d", 5);
      expect(result).toBeNull();
    });

    it("returns parsed Transcription on 200", async () => {
      const tx = {
        page: 5,
        engine: "vlm",
        provider: "anthropic",
        markdown: "# hi",
        raw: "hi",
      };
      fetchMock.mockResolvedValueOnce(jsonResponse(tx));
      const result = await getTranscription("d", 5);
      expect(result).toEqual(tx);
    });

    it("throws on 500 (not the 404 special-case)", async () => {
      fetchMock.mockResolvedValueOnce(new Response("", { status: 500 }));
      await expect(getTranscription("d", 5)).rejects.toThrow(/500/);
    });
  });

  describe("getBreakdown", () => {
    it("returns null on 404", async () => {
      fetchMock.mockResolvedValueOnce(new Response("", { status: 404 }));
      const result = await getBreakdown("d", "c", "r");
      expect(result).toBeNull();
    });
  });

  describe("pageImageUrl", () => {
    it("builds the page image path", () => {
      expect(pageImageUrl("doc-1", 7)).toBe("/api/documents/doc-1/pages/7/image");
    });
  });

  describe("CRUD wrappers send the expected method/url/body", () => {
    it("listChapters / getChapter / listRegions GET", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse([]));
      await listChapters("d1");
      expect(fetchMock.mock.calls[0]![0]).toBe("/api/documents/d1/chapters");

      fetchMock.mockResolvedValueOnce(jsonResponse({}));
      await getChapter("d1", "c1");
      expect(fetchMock.mock.calls[1]![0]).toBe("/api/documents/d1/chapters/c1");

      fetchMock.mockResolvedValueOnce(jsonResponse([]));
      await listRegions("d1", "c1");
      expect(fetchMock.mock.calls[2]![0]).toBe(
        "/api/documents/d1/chapters/c1/regions",
      );
    });

    it("updateChapter PUTs the body", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ id: "c1" }));
      await updateChapter("d1", "c1", { title: "New" });
      const [url, init] = fetchMock.mock.calls[0]!;
      expect(url).toBe("/api/documents/d1/chapters/c1");
      expect(init.method).toBe("PUT");
      expect(JSON.parse(init.body as string)).toEqual({ title: "New" });
    });

    it("updateChapter throws with body on non-2xx", async () => {
      fetchMock.mockResolvedValueOnce(new Response("bad", { status: 400 }));
      await expect(updateChapter("d", "c", { title: "x" })).rejects.toThrow(
        /400.*bad/,
      );
    });

    it("deleteChapter DELETEs", async () => {
      fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
      await deleteChapter("d1", "c1");
      const [, init] = fetchMock.mock.calls[0]!;
      expect(init.method).toBe("DELETE");
    });

    it("createRegion / updateRegion / deleteRegion / moveRegion", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ id: "r1" }));
      await createRegion("d", "c", { page: 1, bbox: [0, 0, 1, 1], tag: "other" });
      expect(fetchMock.mock.calls[0]![0]).toBe(
        "/api/documents/d/chapters/c/regions",
      );

      fetchMock.mockResolvedValueOnce(jsonResponse({ id: "r1" }));
      await updateRegion("d", "c", "r1", { tag: "vocab_list" });
      expect(fetchMock.mock.calls[1]![1]!.method).toBe("PUT");

      fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
      await deleteRegion("d", "c", "r1");
      expect(fetchMock.mock.calls[2]![1]!.method).toBe("DELETE");

      fetchMock.mockResolvedValueOnce(jsonResponse({ id: "r1" }));
      await moveRegion("d", "c1", "r1", "c2");
      const [, moveInit] = fetchMock.mock.calls[3]!;
      expect(JSON.parse(moveInit.body as string)).toEqual({ dst_chapter_id: "c2" });
    });

    it("transcribeRegion / requestBreakdown / submitTranscription POST", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "j1" }));
      await transcribeRegion("d", "c", "r");
      expect(fetchMock.mock.calls[0]![0]).toBe(
        "/api/documents/d/chapters/c/regions/r/transcribe",
      );

      fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "j2" }));
      await requestBreakdown("d", "c", "r", { overwrite: true });
      const [, init] = fetchMock.mock.calls[1]!;
      expect(JSON.parse(init.body as string)).toEqual({ overwrite: true });

      fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "j3", pages: [1] }));
      await submitTranscription("d", {
        engine: "vlm",
        provider: "anthropic",
        pages: "1",
        config: {},
      });
      expect(fetchMock.mock.calls[2]![0]).toBe("/api/documents/d/transcribe");
    });

    it("requestBreakdown throws with body on non-2xx", async () => {
      fetchMock.mockResolvedValueOnce(new Response("nope", { status: 500 }));
      await expect(
        requestBreakdown("d", "c", "r"),
      ).rejects.toThrow(/500.*nope/);
    });

    it("getProviders / getCostSummary GET the right paths", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ ocr: [], vlm: [], defaults: {} }));
      await getProviders();
      expect(fetchMock.mock.calls[0]![0]).toBe("/api/providers");

      fetchMock.mockResolvedValueOnce(jsonResponse({}));
      await getCostSummary();
      expect(fetchMock.mock.calls[1]![0]).toBe("/api/costs/summary");
    });

    it("reuploadDocument PUTs FormData with correlation header", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ id: "d" }));
      const file = new File(["x"], "x.pdf", { type: "application/pdf" });
      await reuploadDocument("d", file);
      const [url, init] = fetchMock.mock.calls[0]!;
      expect(url).toBe("/api/documents/d/file");
      expect(init.method).toBe("PUT");
      expect(init.body).toBeInstanceOf(FormData);
    });

    it("reuploadDocument throws with body on non-2xx", async () => {
      fetchMock.mockResolvedValueOnce(new Response("too big", { status: 413 }));
      const file = new File(["x"], "x.pdf");
      await expect(reuploadDocument("d", file)).rejects.toThrow(/413.*too big/);
    });

    it("uploadDocument throws with body on non-2xx", async () => {
      fetchMock.mockResolvedValueOnce(new Response("bad pdf", { status: 422 }));
      const file = new File(["x"], "x.pdf");
      await expect(uploadDocument(file)).rejects.toThrow(/422.*bad pdf/);
    });
  });

  describe("openJobStream", () => {
    it("subscribes to all event types and returns a closer", () => {
      const handlers: Record<string, (ev: MessageEvent) => void> = {};
      const closeMock = vi.fn();
      const constructorSpy = vi.fn();
      class FakeES {
        onerror: unknown = null;
        constructor(url: string) {
          constructorSpy(url);
        }
        addEventListener(type: string, h: (ev: MessageEvent) => void) {
          handlers[type] = h;
        }
        close = closeMock;
      }
      vi.stubGlobal("EventSource", FakeES);

      const onEvent = vi.fn();
      const close = openJobStream("job-1", onEvent);
      expect(constructorSpy).toHaveBeenCalledWith("/api/jobs/job-1/events");
      // Fire a known event
      handlers["job-done"]!({ data: '{"ok": true}' } as MessageEvent);
      expect(onEvent).toHaveBeenCalledWith({ event: "job-done", data: { ok: true } });
      close();
      expect(closeMock).toHaveBeenCalled();
    });
  });
});
