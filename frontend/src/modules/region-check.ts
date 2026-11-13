// Gating logic for the post-transcription region check (see
// backend/app/services/region_check.py). Pure: it decides what the UI may
// show from a region's stored `check`, which goes stale when the region is
// re-transcribed or relabelled.

import type { Region } from "../api";

export type ReferenceNeed = "needed" | "not_needed" | "unchecked";

type Checkable = Pick<Region, "tag" | "transcribed_at" | "check" | "references">;

/** The check was made against the region's current transcription. */
export function isCheckFresh(region: Checkable): boolean {
  const check = region.check;
  if (!check) return false;
  return check.transcribed_at === (region.transcribed_at ?? null);
}

/**
 * A better tag, only when the model is highly confident, the label has not
 * been changed since the check, and the suggestion was not dismissed.
 * Nothing is returned when the label is fine.
 */
export function labelSuggestion(region: Checkable): { tag: string; reason: string } | null {
  const check = region.check;
  if (!check || !isCheckFresh(region)) return null;
  if (check.tag !== region.tag) return null;
  if (check.suggested_tag === region.tag) return null;
  if (check.tag_confidence !== "high") return null;
  if (check.label_dismissed) return null;
  return { tag: check.suggested_tag, reason: check.tag_reason };
}

export function referenceNeed(region: Checkable): ReferenceNeed {
  if (!region.check || !isCheckFresh(region)) return "unchecked";
  return region.check.needs_reference ? "needed" : "not_needed";
}

/** An exercise region the check says needs a reading reference, with none set. */
export function missingReference(region: Checkable): boolean {
  return referenceNeed(region) === "needed" && (region.references ?? []).length === 0;
}

/**
 * Relabelling to or from vocab_list changes which transcription prompt
 * applies (the vocab-list prompt vs. the general region prompt), so the
 * existing transcription is shaped wrongly. Every other change keeps it.
 */
export function relabelNeedsRetranscribe(oldTag: string, newTag: string): boolean {
  return (oldTag === "vocab_list") !== (newTag === "vocab_list");
}
