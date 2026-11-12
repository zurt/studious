import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { previewAnkiPush, sendAnkiPush, type AnkiPushPreview, type AnkiPushResult } from "../src/api";
import {
  clampCount,
  pushDialogLines,
  pushResultMessage,
  sendButtonLabel,
} from "../src/modules/anki-push-dialog";
import { sendToAnkiTitle } from "../src/pages/study-dashboard";

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
      headword_match: 0,
    },
    items: Array.from({ length: n }, (_, i) => ({
      id: `i${i}`, headword: `語${i}`, reading: "", fields: {}, tags: [], has_sentence: true, has_gloss: false,
      can_add: true, reason: "", headword_match: false,
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
      headword_match: 1,
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
