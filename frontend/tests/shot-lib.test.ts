import { describe, expect, it } from "vitest";
// @ts-expect-error plain .mjs, shared with the Node script that runs it
import { VIEWS, fillPath, parseArgs, parseViewport, slugify } from "../scripts/shot-lib.mjs";

const context = {
  doc: "d1",
  chapters: ["c1", "c2"],
  regions: [
    { id: "r-vocab", tag: "vocab_list", page: 1, chapter: 1 },
    { id: "r-read", tag: "reading_passage", page: 2, chapter: 1 },
    { id: "r-vocab-2", tag: "vocab_list", page: 4, chapter: 2 },
  ],
};

describe("fillPath", () => {
  it("fills document, chapter, region and page placeholders", () => {
    expect(fillPath("/doc/{doc}/chapter/{chapter2}", context)).toBe("/doc/d1/chapter/c2");
    expect(fillPath("?page={page:reading_passage}&region={region:reading_passage}", context)).toBe(
      "?page=2&region=r-read",
    );
  });

  it("looks in chapter 1 unless told otherwise", () => {
    expect(fillPath("{region:vocab_list}", context)).toBe("r-vocab");
    expect(fillPath("{region:vocab_list:2}/{page:vocab_list:2}", context)).toBe("r-vocab-2/4");
  });

  it("leaves a path without placeholders alone", () => {
    expect(fillPath("/vocab?status=learning", context)).toBe("/vocab?status=learning");
  });

  it("names what is missing", () => {
    expect(() => fillPath("/doc/{doc}", { doc: null, chapters: [], regions: [] })).toThrow(/no document/);
    expect(() => fillPath("{chapter3}", context)).toThrow(/2 chapter/);
    expect(() => fillPath("{region:exercises}", context)).toThrow(/no exercises region in chapter 1/);
    expect(() => fillPath("{nonsense}", context)).toThrow(/unknown placeholder/);
  });

  it("can fill every named view from a seeded stack's shape", () => {
    const seeded = {
      ...context,
      regions: [...context.regions, { id: "r-ex", tag: "exercises", page: 3, chapter: 1 }],
    };
    for (const [name, view] of Object.entries(VIEWS) as [string, { path: string }][]) {
      expect(fillPath(view.path, seeded), name).not.toMatch(/[{}]/);
    }
  });
});

describe("parseArgs", () => {
  it("defaults to every view on a desktop viewport", () => {
    const opts = parseArgs([]);
    expect(opts.targets).toEqual([]);
    expect(opts.viewport).toEqual({ width: 1440, height: 900 });
    expect(opts.out).toBe("screenshots");
    expect(opts.baseUrl).toBeNull();
  });

  it("takes views, paths, flags and steps in order", () => {
    const opts = parseArgs([
      "reading",
      "/vocab?q=a",
      "--dark",
      "--mobile",
      "--click",
      "#a",
      "--fill",
      "#q=散歩=x",
      "--press",
      "Escape",
      "--base-url",
      "http://localhost:5173/",
    ]);
    expect(opts.targets).toEqual(["reading", "/vocab?q=a"]);
    expect(opts.dark).toBe(true);
    expect(opts.viewport).toEqual({ width: 390, height: 844 });
    expect(opts.steps).toEqual([
      { kind: "click", value: "#a" },
      { kind: "fill", value: "#q=散歩=x" },
      { kind: "press", value: "Escape" },
    ]);
    expect(opts.baseUrl).toBe("http://localhost:5173");
  });

  it("rejects what it does not know", () => {
    expect(() => parseArgs(["nope"])).toThrow(/unknown view/);
    expect(() => parseArgs(["--nope"])).toThrow(/unknown option/);
    expect(() => parseArgs(["--click"])).toThrow(/needs a value/);
    expect(() => parseArgs(["--fill", "#q"])).toThrow(/SELECTOR=TEXT/);
    expect(() => parseArgs(["--scale", "0"])).toThrow(/positive/);
    expect(() => parseArgs(["--name", "x"])).toThrow(/exactly one/);
    expect(() => parseArgs(["library", "vocab", "--name", "x"])).toThrow(/exactly one/);
  });
});

describe("parseViewport", () => {
  it("parses WIDTHxHEIGHT only", () => {
    expect(parseViewport("800x600")).toEqual({ width: 800, height: 600 });
    expect(() => parseViewport("800")).toThrow(/WIDTHxHEIGHT/);
  });
});

describe("slugify", () => {
  it("turns a path into a file name", () => {
    expect(slugify("/vocab?status=learning")).toBe("vocab-status-learning");
    expect(slugify("/")).toBe("root");
  });
});
