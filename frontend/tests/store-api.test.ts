import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  listStoreItems,
  createStoreItem,
  patchStoreItem,
  deleteStoreItem,
  getStoreStats,
  runStoreBackfill,
  getWanikaniStatus,
  syncWanikani,
  getVocabWanikani,
  runStoreEnrich,
} from "../src/api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("store api", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listStoreItems builds query params and skips empties", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    await listStoreItems("vocab", { status: "unreviewed", q: "", limit: 50 });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/api/vocab?");
    expect(url).toContain("status=unreviewed");
    expect(url).toContain("limit=50");
    expect(url).not.toContain("q=");
  });

  it("listStoreItems with no params hits bare endpoint", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    await listStoreItems("grammar");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/grammar");
  });

  it("createStoreItem posts JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "x" }, 201));
    await createStoreItem("vocab", { headword: "犬", reading: "いぬ" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/vocab");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ headword: "犬", reading: "いぬ" });
  });

  it("patchStoreItem sends PATCH with changes", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "abc", status: "known" }));
    const r = await patchStoreItem("vocab", "abc", { status: "known" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/vocab/abc");
    expect(init.method).toBe("PATCH");
    expect(r.status).toBe("known");
  });

  it("patchStoreItem throws on non-2xx", async () => {
    fetchMock.mockResolvedValue(new Response("nope", { status: 404 }));
    await expect(patchStoreItem("grammar", "missing", { status: "known" })).rejects.toThrow("404");
  });

  it("deleteStoreItem issues DELETE", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await deleteStoreItem("grammar", "g1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/grammar/g1");
    expect(init.method).toBe("DELETE");
  });

  it("wanikani + enrich endpoints hit the right URLs", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ configured: true, synced_at: null, counts: {} }));
    await getWanikaniStatus();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/refs/wanikani/status");
    fetchMock.mockResolvedValue(jsonResponse({ fetched: {} }));
    await syncWanikani(true);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/refs/wanikani/sync?full=true");
    expect(fetchMock.mock.calls[1][1].method).toBe("POST");
    fetchMock.mockResolvedValue(jsonResponse({ characters: "勉強", kanji: [] }));
    const d = await getVocabWanikani("abc");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/vocab/abc/wanikani");
    expect(d.characters).toBe("勉強");
    fetchMock.mockResolvedValue(jsonResponse({ attempted: 0 }));
    await runStoreEnrich(true);
    expect(fetchMock.mock.calls[3][0]).toBe("/api/store/enrich?force=true");
  });

  it("getStoreStats and runStoreBackfill hit /api/store", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ vocab: {}, grammar: {} }));
    await getStoreStats();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/store/stats");
    fetchMock.mockResolvedValue(jsonResponse({ vocab_created: 0 }));
    await runStoreBackfill();
    expect(fetchMock.mock.calls[1][0]).toBe("/api/store/backfill");
  });
});
