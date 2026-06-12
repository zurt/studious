import { describe, it, expect } from "vitest";
import { completionToMarkdown } from "../src/modules/breakdown-pane";
import type { ExerciseCompletionEntry } from "../src/api";

const entry: ExerciseCompletionEntry = {
  answer: "本を読みます",
  answer_english: "I read a book",
  explanation: "Use を to mark the direct object.",
  examples: [
    { japanese: "新聞を読みます", reading: "しんぶんをよみます", english: "I read the newspaper", explanation: "Same pattern, different object." },
    { japanese: "手紙を書きます", reading: "てがみをかきます", english: "I write a letter", explanation: "Another transitive verb." },
  ],
};

describe("completionToMarkdown", () => {
  it("renders answer, english gloss, explanation, and examples", () => {
    const md = completionToMarkdown(entry, "＿＿を読みます");
    expect(md).toContain("＿＿を読みます");
    expect(md).toContain("**Answer:** 本を読みます (I read a book)");
    expect(md).toContain("Use を to mark the direct object.");
    expect(md).toContain("**Examples**");
    expect(md).toContain("- 新聞を読みます（しんぶんをよみます） — I read the newspaper");
    expect(md).toContain("  Same pattern, different object.");
  });

  it("omits the english gloss when absent", () => {
    const md = completionToMarkdown({ answer: "はい", examples: [] });
    expect(md).toContain("**Answer:** はい");
    expect(md).not.toContain("(");
    expect(md).not.toContain("**Examples**");
  });

  it("skips the sentence header when not provided", () => {
    const md = completionToMarkdown({ answer: "はい", examples: [] });
    expect(md.startsWith("**Answer:**")).toBe(true);
  });
});

