import { describe, it, expect } from "vitest";
import { renderMarkdown } from "../src/modules/markdown";

describe("renderMarkdown", () => {
  it("renders headings, emphasis, and lists", () => {
    const html = renderMarkdown("# Title\n\n**bold** text\n\n- a\n- b");
    expect(html).toContain("<h1>Title</h1>");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<li>a</li>");
  });

  it("renders GFM tables", () => {
    const html = renderMarkdown("| 辞書形 | ます形 |\n| --- | --- |\n| 食べる | 食べます |");
    expect(html).toContain("<table>");
    expect(html).toContain("食べます");
  });

  it("preserves Japanese text with inline furigana parens", () => {
    const html = renderMarkdown("食(た)べる — to eat");
    expect(html).toContain("食(た)べる");
  });

  it("strips script tags", () => {
    const html = renderMarkdown('before\n\n<script>document.title = "owned"</script>\n\nafter');
    expect(html).not.toContain("<script");
    expect(html).toContain("before");
    expect(html).toContain("after");
  });

  it("strips event-handler attributes", () => {
    const html = renderMarkdown('<img src="x" onerror="alert(1)">');
    expect(html).not.toContain("onerror");
  });

  it("strips javascript: URLs from links", () => {
    const html = renderMarkdown("[click](javascript:alert(1))");
    expect(html).not.toContain("javascript:");
  });

  it("strips iframes", () => {
    const html = renderMarkdown('<iframe src="https://example.com"></iframe>');
    expect(html).not.toContain("<iframe");
  });
});
