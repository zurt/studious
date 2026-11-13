import { describe, expect, it } from "vitest";
import type { Region, RegionCheck } from "../src/api";
import {
  isCheckFresh, labelSuggestion, missingReference, referenceNeed, relabelNeedsRetranscribe,
} from "../src/modules/region-check";

function check(over: Partial<RegionCheck> = {}): RegionCheck {
  return {
    checked_at: "2026-01-02T00:00:00Z",
    model: "claude-haiku-5-5",
    transcribed_at: "T1",
    tag: "reading_passage",
    suggested_tag: "vocab_list",
    tag_confidence: "high",
    tag_reason: "A word list.",
    needs_reference: false,
    reference_reason: "",
    label_dismissed: false,
    ...over,
  };
}

function region(over: Partial<Region> = {}, c: Partial<RegionCheck> | null = {}): Region {
  return {
    id: "r", tag: "reading_passage", transcribed_at: "T1",
    ...(c ? { check: check(c) } : {}),
    ...over,
  } as unknown as Region;
}

describe("isCheckFresh", () => {
  it("needs a check made against the current transcription", () => {
    expect(isCheckFresh(region())).toBe(true);
    expect(isCheckFresh(region({}, null))).toBe(false);
    expect(isCheckFresh(region({ transcribed_at: "T2" }))).toBe(false);
  });
});

describe("labelSuggestion", () => {
  it("suggests only a confident, fresh, undismissed, still-applicable different tag", () => {
    expect(labelSuggestion(region())).toEqual({ tag: "vocab_list", reason: "A word list." });
    expect(labelSuggestion(region({}, { tag_confidence: "medium" }))).toBeNull();
    expect(labelSuggestion(region({}, { tag_confidence: "low" }))).toBeNull();
    expect(labelSuggestion(region({}, { label_dismissed: true }))).toBeNull();
    expect(labelSuggestion(region({ transcribed_at: "T2" }))).toBeNull();
    expect(labelSuggestion(region({}, null))).toBeNull();
  });

  it("is silent when the label is fine or was changed since the check", () => {
    expect(labelSuggestion(region({}, { suggested_tag: "reading_passage" }))).toBeNull();
    expect(labelSuggestion(region({ tag: "vocab_list" }))).toBeNull();
  });
});

describe("referenceNeed", () => {
  it("reports needed, not needed, or unchecked", () => {
    expect(referenceNeed(region({}, { needs_reference: true }))).toBe("needed");
    expect(referenceNeed(region({}, { needs_reference: false }))).toBe("not_needed");
    expect(referenceNeed(region({}, null))).toBe("unchecked");
    expect(referenceNeed(region({ transcribed_at: "T2" }, { needs_reference: true }))).toBe("unchecked");
  });
});

describe("missingReference", () => {
  it("is true only when needed and no references are set", () => {
    const needed = { needs_reference: true };
    expect(missingReference(region({}, needed))).toBe(true);
    expect(missingReference(region({ references: [] }, needed))).toBe(true);
    expect(missingReference(region({ references: [{ doc_id: "d", chapter_id: "c", region_id: "x" }] }, needed))).toBe(false);
    expect(missingReference(region({}, { needs_reference: false }))).toBe(false);
    expect(missingReference(region({}, null))).toBe(false);
  });
});

describe("relabelNeedsRetranscribe", () => {
  it("is true only when exactly one side is vocab_list", () => {
    expect(relabelNeedsRetranscribe("reading_passage", "vocab_list")).toBe(true);
    expect(relabelNeedsRetranscribe("vocab_list", "exercises")).toBe(true);
    expect(relabelNeedsRetranscribe("reading_passage", "exercises")).toBe(false);
    expect(relabelNeedsRetranscribe("vocab_list", "vocab_list")).toBe(false);
  });
});
