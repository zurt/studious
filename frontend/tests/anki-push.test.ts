import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  deleteVocabExample,
  generateExamples,
  previewAnkiPush,
  sendAnkiPush,
  vocabAudioUrl,
  type AnkiPushPreview,
  type AnkiPushResult,
  type ExamplesResponse,
} from "../src/api";
import {
  GENERATE_CHUNK,
  audioLabel,
  betterVoicesHint,
  cachedAudioLabel,
  audioUnavailableLine,
  chunkIds,
  clampCount,
  generateButtonLabel,
  generationSummary,
  needsExampleLine,
  offerVisible,
  progressText,
  pushDialogLines,
  pushResultMessage,
  sendButtonLabel,
  tallyResults,
} from "../src/modules/anki-push-dialog";
import { ankiBadge, sendToAnkiTitle } from "../src/pages/study-dashboard";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function preview(over: Partial<AnkiPushPreview> = {}, n = 12): AnkiPushPreview {
  return {
    deck: "Studious",
    deck_exists: true,
    will_create_deck: false,
    note_type: "Kaishi 1.5k",
    counts: {
      candidates: n, will_add: n, skipped: 0, without_sentence: 0, with_sentence: n, with_gloss: 0,
      headword_match: 0, needs_example: 0, needs_example_ids: [],
    },
    items: Array.from({ length: n }, (_, i) => ({
      id: `i${i}`, headword: `語${i}`, reading: "", fields: {}, tags: [], has_sentence: true, has_gloss: false,
      can_add: true, reason: "", headword_match: false, sentence_source: "generated",
    })),
    ...over,
  };
}

describe("anki push requests", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("preview posts doc, chapter and limit without confirm", async () => {
    fetchMock.mockResolvedValue(jsonResponse(preview()));
    await previewAnkiPush("d1", "c1", 125);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/anki/push/preview");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ doc_id: "d1", chapter_id: "c1", limit: 125 });
  });

  it("preview and send carry source when set and omit it otherwise", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(preview()));
    await previewAnkiPush("d1", "c1", 125, "vocab_list");
    await sendAnkiPush("d1", "c1", 40, true, "vocab_list");
    await sendAnkiPush("d1", "c1", 40, undefined, undefined);
    const body = (i: number) => JSON.parse(fetchMock.mock.calls[i][1].body);
    expect(body(0)).toEqual({ doc_id: "d1", chapter_id: "c1", limit: 125, source: "vocab_list" });
    expect(body(1)).toEqual({
      doc_id: "d1", chapter_id: "c1", limit: 40, source: "vocab_list", confirm: true, audio: true,
    });
    expect("source" in body(2)).toBe(false);
  });

  it("send posts confirm: true", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ created: 1 }));
    await sendAnkiPush("d1", "c1", 40);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/anki/push");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      doc_id: "d1", chapter_id: "c1", limit: 40, confirm: true,
    });
  });
});

describe("push dialog text", () => {
  it("states count, deck and the first ten headwords", () => {
    const lines = pushDialogLines(preview());
    expect(lines[0]).toBe('12 words will be added to the "Studious" deck (Kaishi 1.5k).');
    expect(lines.some((l) => l.includes("語0、語1") && l.includes("語9") && !l.includes("語10"))).toBe(true);
    expect(lines.join("\n")).not.toContain("will be created");
  });

  it("mentions deck creation, skips, missing sentences and spelling matches", () => {
    const p = preview({ will_create_deck: true, deck_exists: false }, 3);
    p.counts = {
      candidates: 5, will_add: 3, skipped: 2, without_sentence: 1, with_sentence: 2, with_gloss: 1,
      headword_match: 1, needs_example: 1, needs_example_ids: ["x"],
    };
    const text = pushDialogLines(p).join("\n");
    expect(text).toContain("This deck will be created.");
    expect(text).toContain("2 skipped, already in Anki.");
    expect(text).toContain("2 with an example sentence (1 with a translation), 1 without.");
    expect(text).toContain("1 match an existing card by spelling only");
  });

  it("singular and empty cases", () => {
    expect(pushDialogLines(preview({}, 1))[0]).toContain("1 word will");
    expect(pushDialogLines(preview({}, 0))).toHaveLength(1);
    expect(sendButtonLabel(1)).toBe("Send 1 word");
    expect(sendButtonLabel(125)).toBe("Send 125 words");
  });

  it("clampCount keeps the count within 1..max", () => {
    expect(clampCount(0, 50)).toBe(1);
    expect(clampCount(99, 50)).toBe(50);
    expect(clampCount(7.9, 50)).toBe(7);
    expect(clampCount(Number.NaN, 50)).toBe(50);
    expect(clampCount(5, 0)).toBe(1);
  });

  it("result message reports skips, failures and a failed sync", () => {
    const r: AnkiPushResult = {
      created: 3, skipped: [{ id: "a", headword: "x", reason: "" }], failed: [], deck: "Studious",
      deck_created: false, sync_ok: false, sync_error: "gone",
    };
    const msg = pushResultMessage(r);
    expect(msg).toContain("Sent 3 words to Anki (Studious).");
    expect(msg).toContain("1 skipped.");
    expect(msg).toContain("sync afterwards failed");
  });
});

describe("send button title", () => {
  it("explains why it is disabled", () => {
    expect(sendToAnkiTitle("", "", 5)).toContain("Pick a textbook");
    expect(sendToAnkiTitle("d", "", 5)).toContain("Pick a textbook");
    expect(sendToAnkiTitle("d", "c", 0)).toBe("No candidates to send");
    expect(sendToAnkiTitle("d", "c", 5)).toContain("Studious");
  });
});

describe("example generation requests", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("posts ids and force", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ items: [], usage: {} }));
    await generateExamples(["a", "b"]);
    await generateExamples(["a"], true);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/vocab/examples");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ item_ids: ["a", "b"], force: false });
    await generateExamples(["a"], true);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ item_ids: ["a"], force: true });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ item_ids: ["a"], force: true });
  });

  it("deletes the stored example", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await deleteVocabExample("v1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/vocab/v1/example");
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
  });
});

describe("example generation text and chunking", () => {
  it("chunks ids by 20, keeping order", () => {
    const ids = Array.from({ length: 45 }, (_, i) => `i${i}`);
    const chunks = chunkIds(ids);
    expect(GENERATE_CHUNK).toBe(20);
    expect(chunks.map((c) => c.length)).toEqual([20, 20, 5]);
    expect(chunks.flat()).toEqual(ids);
    expect(chunkIds([])).toEqual([]);
    expect(chunkIds(["a", "b", "c"], 2)).toEqual([["a", "b"], ["c"]]);
  });

  it("offer line and button label", () => {
    expect(needsExampleLine(103)).toBe("103 words need an example sentence.");
    expect(needsExampleLine(1)).toBe("1 word needs an example sentence.");
    expect(generateButtonLabel()).toBe("Generate");
  });

  it("progress text", () => {
    expect(progressText(40, 103)).toBe("Generating\u2026 40 of 103");
  });

  it("tallies results and summarizes", () => {
    const res: ExamplesResponse = {
      items: [
        { id: "a", status: "generated" },
        { id: "b", status: "generated" },
        { id: "c", status: "failed", reason: "x" },
        { id: "d", status: "kept" },
      ],
      usage: { calls: 1, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0 },
    };
    const t = tallyResults(res);
    expect(t).toEqual({ generated: 2, kept: 1, failed: 1 });
    expect(generationSummary(t, 1, null)).toBe(
      "Generated 2 sentences, 1 failed. 1 word stays without a sentence.",
    );
    expect(generationSummary({ generated: 1, kept: 0, failed: 0 }, 0, null)).toBe("Generated 1 sentence.");
    expect(generationSummary(t, 40, "cancelled")).toContain("Stopped.");
  });

  it("offer shows only when words need sentences and no run has completed", () => {
    expect(offerVisible(5, false, false)).toBe(true);
    expect(offerVisible(0, false, false)).toBe(false);
    expect(offerVisible(5, true, false)).toBe(false);
    expect(offerVisible(5, false, true)).toBe(false);
  });
});

describe("audio option", () => {
  it("labels", () => {
    expect(audioLabel("Kyoko")).toBe("Add audio (Mac voice: Kyoko)");
    expect(audioUnavailableLine("Kyoko")).toContain("Kyoko");
    expect(audioLabel("ずんだもん — ノーマル", "voicevox")).toBe("Add audio (ずんだもん — ノーマル)");
    expect(audioLabel("Kyoko, O-Ren, Otoya (Enhanced)", "say", ["a", "b", "c"])).toBe(
      "Add audio (Mac voices: Kyoko, O-Ren, Otoya \u2014 Enhanced)",
    );
    expect(audioLabel("Kyoko", "say", ["Kyoko"])).toBe("Add audio (Mac voice: Kyoko)");
    expect(betterVoicesHint("say", ["Kyoko"])).toContain("Spoken Content");
    expect(betterVoicesHint("say", ["Kyoko (Enhanced)"])).toBe("");
    expect(betterVoicesHint("say", ["a (Enhanced)", "b (Enhanced)"])).toBe("");
    expect(betterVoicesHint("voicevox", ["Kyoko"])).toBe("");
    expect(audioUnavailableLine("", "The speech engine is not reachable.")).toBe(
      "No new audio: The speech engine is not reachable. Clips already made are still attached.",
    );
    expect(audioUnavailableLine("Kyoko")).not.toMatch(/macOS/);
    expect(audioUnavailableLine("")).toBe(
      "No new audio: the Mac voice is not reachable. Clips already made are still attached.",
    );
    expect(cachedAudioLabel()).toBe("Add audio (clips already made only)");
    expect(audioLabel("Kyoko, O-Ren (Enhanced)", "say_remote", ["a", "b"])).toBe(
      "Add audio (Mac voices: Kyoko, O-Ren \u2014 Enhanced)",
    );
    expect(betterVoicesHint("say_remote", ["Kyoko"])).toContain("Spoken Content");
  });

  it("result message reports clips and failures", () => {
    const base: AnkiPushResult = {
      created: 2, skipped: [], failed: [], deck: "Studious", deck_created: false, sync_ok: true, sync_error: null,
    };
    expect(pushResultMessage(base)).not.toContain("audio");
    expect(pushResultMessage({ ...base, audio: { enabled: false, attached: 0, failed: 0 } })).not.toContain("audio");
    expect(pushResultMessage({ ...base, audio: { enabled: true, attached: 3, failed: 0 } })).toContain("3 audio clips added.");
    expect(pushResultMessage({ ...base, audio: { enabled: true, attached: 3, failed: 0, reading_corrected: 2 } })).toContain(
      "2 readings corrected.",
    );
    expect(pushResultMessage({ ...base, audio: { enabled: true, attached: 1, failed: 2 } })).toContain(
      "1 audio clip added, 2 failed.",
    );
    const down = pushResultMessage({ ...base, audio: { enabled: true, unavailable: true, attached: 1, failed: 0, missing: 3 } });
    expect(down).toContain("1 audio clip added.");
    expect(down).toContain("3 clips were left off because the Mac was not reachable");
    expect(down).toContain("not added to the cards later");
    expect(
      pushResultMessage({ ...base, audio: { enabled: true, unavailable: true, attached: 0, failed: 0, missing: 1 } }),
    ).toContain("1 clip was left off");
    expect(pushResultMessage({ ...base, audio: { enabled: true, attached: 2, failed: 0, missing: 0 } })).not.toContain("left off");
  });

  it("send body carries audio only when given", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ created: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    await sendAnkiPush("d", "c", 5);
    await sendAnkiPush("d", "c", 5, false);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).not.toHaveProperty("audio");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).audio).toBe(false);
    vi.unstubAllGlobals();
  });

  it("clip url", () => {
    expect(vocabAudioUrl("v1", "sentence")).toBe("/api/vocab/v1/audio?part=sentence");
  });
});

describe("anki badge for a stem match", () => {
  it("explains the する/な match", () => {
    const html = ankiBadge({ anki: { state: "new", deck: "D", interval: 0, match: "stem" } } as any);
    expect(html).toContain("matched the same word with or without する/な");
    expect(html).toContain("Anki · new~");
  });
});
