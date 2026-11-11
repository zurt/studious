import { describe, expect, it } from "vitest";
import type { Region } from "../src/api";
import {
  chainHeadOf, combinedTranscriptionMd, resolveChain,
} from "../src/modules/region-chain";

function region(id: string, page: number, continuesTo?: string, md = `text ${id}`): Region {
  return {
    id, page, bbox: [0, 0, 1, 1], tag: "reading_passage",
    continues_to: continuesTo ?? null, transcription_md: md,
  } as unknown as Region;
}

describe("region chains", () => {
  const regions = [region("a", 1, "b"), region("b", 2, "c"), region("c", 3), region("solo", 1)];

  it("resolves a chain in reading order from its head", () => {
    expect(resolveChain(regions, "a").map((r) => r.id)).toEqual(["a", "b", "c"]);
    expect(resolveChain(regions, "solo").map((r) => r.id)).toEqual(["solo"]);
  });

  it("stops at a missing link instead of throwing", () => {
    expect(resolveChain([region("a", 1, "gone")], "a").map((r) => r.id)).toEqual(["a"]);
    expect(resolveChain(regions, "nope")).toEqual([]);
  });

  it("finds the head from any member", () => {
    expect(chainHeadOf(regions, regions[2]).id).toBe("a");
    expect(chainHeadOf(regions, regions[0]).id).toBe("a");
    expect(chainHeadOf(regions, regions[3]).id).toBe("solo");
  });

  it("terminates on a cycle", () => {
    const loop = [region("x", 1, "y"), region("y", 2, "x")];
    expect(resolveChain(loop, "x").map((r) => r.id)).toEqual(["x", "y"]);
    expect(["x", "y"]).toContain(chainHeadOf(loop, loop[0]).id);
  });

  it("joins markdown with a page marker between pieces", () => {
    const md = combinedTranscriptionMd(resolveChain(regions, "a"));
    expect(md.startsWith("text a")).toBe(true);
    expect(md).toContain("_(continues on page 2)_\n\ntext b");
    expect(md).toContain("_(continues on page 3)_\n\ntext c");
  });
});
