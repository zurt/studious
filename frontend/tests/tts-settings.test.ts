import { describe, expect, it } from "vitest";
import { groupSpeakers, speakerOptionsHtml, ttsStatusLine } from "../src/modules/tts-settings";

const speakers = [
  { id: 2, character: "四国めたん", style: "ノーマル", label: "四国めたん — ノーマル" },
  { id: 0, character: "四国めたん", style: "あまあま", label: "四国めたん — あまあま" },
  { id: 3, character: "ずんだもん", style: "ノーマル", label: "ずんだもん — ノーマル" },
];

describe("tts settings helpers", () => {
  it("groups styles under their character in engine order", () => {
    const g = groupSpeakers(speakers);
    expect(g.map((x) => x.character)).toEqual(["四国めたん", "ずんだもん"]);
    expect(g[0].styles.map((s) => s.id)).toEqual([2, 0]);
  });

  it("renders grouped options with the chosen speaker selected", () => {
    const html = speakerOptionsHtml(speakers, 3);
    expect(html).toContain('<optgroup label="四国めたん">');
    expect(html).toContain('<option value="3" selected>ずんだもん — ノーマル</option>');
    expect(html).not.toContain('value="2" selected');
    expect(speakerOptionsHtml(speakers, null)).toContain('<option value="" selected>Choose a speaker…</option>');
  });

  it("escapes labels", () => {
    const html = speakerOptionsHtml([{ id: 1, character: "<b>", style: "x", label: "<b> — x" }], null);
    expect(html).not.toContain("<b>");
  });

  it("status line", () => {
    expect(ttsStatusLine({ available: true, engine: "say", voice: "Kyoko", reason: "" })).toBe("Ready: Kyoko.");
    expect(ttsStatusLine({ available: false, engine: "voicevox", voice: "", reason: "not reachable" })).toBe(
      "not reachable",
    );
    expect(ttsStatusLine({ available: false, engine: "say", voice: "", reason: "" })).toContain("say");
    expect(ttsStatusLine({ available: true, engine: "say", voice: "Kyoko", reason: "None installed; using auto." })).toBe(
      "Ready: Kyoko. None installed; using auto.",
    );
  });
});
