// Cross-page region chains: a region may continue onto another via
// `continues_to`. Pure helpers over a chapter's region list; both walks
// are cycle-safe.
import type { Region } from "../api";
import { renderMarkdown } from "./markdown";

/** The chain starting at `headId`, in reading order. */
export function resolveChain(regions: Region[], headId: string): Region[] {
  const out: Region[] = [];
  const seen = new Set<string>();
  let curId: string | null = headId;
  while (curId && !seen.has(curId)) {
    const r = regions.find((x) => x.id === curId);
    if (!r) break;
    seen.add(curId);
    out.push(r);
    curId = r.continues_to || null;
  }
  return out;
}

/** The first region of the chain that `region` belongs to. */
export function chainHeadOf(regions: Region[], region: Region): Region {
  let cur = region;
  const seen = new Set([region.id]);
  for (;;) {
    const prev = regions.find((r) => r.continues_to === cur.id);
    if (!prev || seen.has(prev.id)) return cur;
    seen.add(prev.id);
    cur = prev;
  }
}

export function combinedTranscriptionHtml(chain: Region[]): string {
  return chain
    .map((r, idx) => {
      const md = r.transcription_md || "";
      const body = renderMarkdown(md);
      if (idx === 0) return body;
      return `<div class="region-chain-separator" style="margin: 12px 0; padding: 6px 10px; border-top: 1px dashed rgba(16,185,129,0.5); color: rgb(16,185,129); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">↓ continues on page ${r.page}</div>${body}`;
    })
    .join("");
}

export function combinedTranscriptionMd(chain: Region[]): string {
  return chain
    .map((r, idx) => {
      const md = r.transcription_md || "";
      if (idx === 0) return md;
      return `\n\n---\n_(continues on page ${r.page})_\n\n${md}`;
    })
    .join("");
}
