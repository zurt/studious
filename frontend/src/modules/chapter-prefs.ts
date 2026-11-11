// Per-browser preferences for the chapter view (localStorage), plus the
// default-region pick. No DOM, no network.
import type { Region } from "../api";

export const VALID_TAGS = ["reading_passage", "vocab_list", "grammar_points", "exercises", "instructions", "other"];

const LAST_TAG_KEY = "studious.region.lastTag";
export function getLastTag(): string {
  const v = localStorage.getItem(LAST_TAG_KEY);
  return v && VALID_TAGS.includes(v) ? v : VALID_TAGS[0];
}
export function setLastTag(tag: string) {
  localStorage.setItem(LAST_TAG_KEY, tag);
}

export type TextSize = 1 | 2 | 3;
const TEXT_SIZE_KEY = "studious.transcription.textSize";
export function getTranscriptionTextSize(): TextSize {
  const v = Number(localStorage.getItem(TEXT_SIZE_KEY));
  return v === 2 || v === 3 ? v : 1;
}
export function setTranscriptionTextSize(size: TextSize) {
  localStorage.setItem(TEXT_SIZE_KEY, String(size));
}

const LAST_REGION_KEY = "studious.lastRegion";
function lastRegionMap(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(LAST_REGION_KEY) || "{}");
  } catch {
    return {};
  }
}
export function getRememberedRegion(chapterId: string, page: number): string | null {
  return lastRegionMap()[`${chapterId}:${page}`] || null;
}
export function rememberRegion(chapterId: string, page: number, regionId: string | null) {
  const map = lastRegionMap();
  const key = `${chapterId}:${page}`;
  if (regionId) map[key] = regionId;
  else delete map[key];
  localStorage.setItem(LAST_REGION_KEY, JSON.stringify(map));
}

export function pickFirstRegion(regs: Region[]): Region | null {
  if (regs.length === 0) return null;
  return [...regs].sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0])[0];
}
