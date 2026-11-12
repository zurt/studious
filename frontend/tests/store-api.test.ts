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
  getAnkiStatus,
  syncAnki,
  runStoreEnrich,
  mergeStoreItems,
  lookupVocab,
  getStoreCoverage,
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

  it("anki endpoints and list filter hit the right URLs", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ has_snapshot: false, total_cards: 0 }));
    await getAnkiStatus();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/refs/anki/status");
    fetchMock.mockResolvedValue(jsonResponse({ total_cards: 3, matched: 2 }));
    const r = await syncAnki();
    expect(fetchMock.mock.calls[1][0]).toBe("/api/refs/anki/sync");
    expect(fetchMock.mock.calls[1][1].method).toBe("POST");
    expect(r.matched).toBe(2);
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    await listStoreItems("vocab", { anki: "mature" });
    expect(fetchMock.mock.calls[2][0]).toBe("/api/vocab?anki=mature");
  });

  it("ankiBadge renders only for matched items; ankiErrorDetail unwraps 503 detail", async () => {
    const { ankiBadge, ankiErrorDetail } = await import("../src/pages/study-dashboard");
    expect(ankiBadge({ anki: null } as any)).toBe("");
    expect(ankiBadge({ anki: { state: "mature", deck: "K", interval: 30, match: "exact" } } as any)).toContain(
      "Anki · mature",
    );
    expect(ankiErrorDetail('/api/refs/anki/sync: 503 {"detail":"Anki is not reachable"}')).toBe(
      "Anki is not reachable",
    );
    expect(ankiErrorDetail("network down")).toBe("network down");
  });

  it("listStoreItems sends chapter_id and the frequency sort", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ items: [], total: 0 }));
    await listStoreItems("grammar", { doc_id: "d1", chapter_id: "c9" });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/grammar?doc_id=d1&chapter_id=c9");
    await listStoreItems("vocab", { sort: "frequency", anki: "none" });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/vocab?sort=frequency&anki=none");
  });

  it("dashboard helpers: count text, chapter options, frequency badge, match hints", async () => {
    const { countLabel, chapterOptions, formatFreqRank, freqBadge, ankiBadge } = await import(
      "../src/pages/study-dashboard"
    );
    expect(countLabel(0)).toBe("0 items");
    expect(countLabel(1)).toBe("1 item");
    expect(countLabel(3204)).toBe("3204 items");

    const opts = chapterOptions([
      { id: "b", title: "第2課", order: 1 },
      { id: "a", title: "第1課 <x>", order: 0 },
    ] as any);
    expect(opts.indexOf("All chapters")).toBeLessThan(opts.indexOf("第1課"));
    expect(opts.indexOf("第1課")).toBeLessThan(opts.indexOf("第2課"));
    expect(opts).toContain("第1課 &lt;x&gt;");

    expect([1, 999, 1000, 1234, 9999, 25000].map(formatFreqRank)).toEqual([
      "#1", "#999", "#1k", "#1.2k", "#10k", "#25k",
    ]);
    expect(freqBadge({ classifications: {} } as any)).toBe("");
    expect(freqBadge({ classifications: { freq_rank: 1234 } } as any)).toContain("#1.2k");

    const card = (match: string) => ({ anki: { state: "new", deck: "K", interval: 0, match } }) as any;
    expect(ankiBadge(card("exact"))).not.toContain("~");
    expect(ankiBadge(card("entry"))).toContain("Anki · new~");
    expect(ankiBadge(card("entry"))).toContain("matched by dictionary entry");
    expect(ankiBadge(card("headword"))).toContain("matched on spelling only, reading differs");
  });

  it("mergeStoreItems posts the source id to the merge route", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "keep" }));
    await mergeStoreItems("vocab", "keep", "dup");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/vocab/keep/merge");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ source_id: "dup" });
  });

  it("lookupVocab posts entries and unwraps matches", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ matches: [{ id: "a", status: "known" }, null] }),
    );
    const matches = await lookupVocab([
      { headword: "犬", reading: "いぬ" },
      { headword: "謎" },
    ]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/vocab/lookup");
    expect(JSON.parse(init.body).entries).toHaveLength(2);
    expect(matches[0]).toEqual({ id: "a", status: "known" });
    expect(matches[1]).toBeNull();
  });

  it("getStoreCoverage queries by chapter id", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ vocab: { total: 3, known: 1 }, grammar: { total: 0 } }),
    );
    const cov = await getStoreCoverage("ch1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/store/coverage?chapter_id=ch1");
    expect(cov.vocab.known).toBe(1);
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
