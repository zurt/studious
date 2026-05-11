import { describe, it, expect } from "vitest";
import { markdownToRichHtml } from "../src/modules/region-list";

describe("markdownToRichHtml", () => {
  it("inserts blank paragraphs between adjacent top-level blocks", async () => {
    const html = await markdownToRichHtml("para one\n\npara two");
    expect(html).toContain("</p><p><br></p><p>");
  });

  it("spaces between heading and paragraph", async () => {
    const html = await markdownToRichHtml("# Title\n\nbody text");
    expect(html).toMatch(/<\/h1>\s*<p><br><\/p><p>/);
  });

  it("spaces around lists", async () => {
    const html = await markdownToRichHtml("before\n\n- a\n- b\n\nafter");
    expect(html).toMatch(/<\/p><p><br><\/p><ul>/);
    expect(html).toMatch(/<\/ul><p><br><\/p><p>/);
  });

  it("renders the U+2500 sentence separator as literal text, not <hr>", async () => {
    const html = await markdownToRichHtml("one\n\n──────────\n\ntwo");
    expect(html).not.toContain("<hr");
    expect(html).toContain("──────────");
  });

  it("does not double-space when blocks are already separated", async () => {
    const html = await markdownToRichHtml("solo paragraph");
    expect(html).not.toContain("<p><br></p>");
  });
});
