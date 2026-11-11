import { describe, expect, it } from "vitest";
import { escapeHtml } from "../src/modules/html";

describe("escapeHtml", () => {
  it("escapes all five HTML-significant characters", () => {
    expect(escapeHtml(`<img src=x onerror="a('b')">&`)).toBe(
      "&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;",
    );
  });

  it("renders null and undefined as an empty string", () => {
    expect(escapeHtml(null)).toBe("");
    expect(escapeHtml(undefined)).toBe("");
  });
});
