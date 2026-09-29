# Exercise Reading References

**Status:** Planned 2026-09-15; built 2026-09-29 as **beta** (see
"As built" at the end for where the implementation departs from this
plan). Implements the Phase 2.5 roadmap item: let an `exercises` region
cite the reading passage(s) it depends on, so exercise-completion
generation has the context it needs even when that reading lives on
other pages or in another textbook entirely.

## Goal

Some exercises can't be completed from the exercise region alone — they
ask questions about a reading passage's content, characters, or events.
Today the only cross-region context mechanism is `continues_to`
(Phase 2.4), which is the wrong shape for this: it's a single forward
pointer, same document, same chapter, meant for one physically-continuous
block of text split across pages. This need is different — **many**
ordered citations, **cross-document**, and semantically a reference to
separate background material rather than the same text continued.

## Data model

New field on regions, populated only when `tag == "exercises"`:

```json
"references": [
  {"doc_id": "...", "chapter_id": "...", "region_id": "..."},
  ...
]
```

Array order is presentation/concatenation order. `storage.create_region`
gains `"references": []` as a default, parallel to `continues_to`.
Reference targets must be `reading_passage`-tagged regions (matches the
stated use case; keeps the picker simple). No reusable/named reference
set — each exercises region stores its own plain ordered list. Since
entries are pointers, not copied content, editing the underlying reading
region doesn't require touching every exercises region that cites it.

`backend/app/services/region_reference.py` (parallel to
`region_chain.py`):
- `resolve_references(doc_id, chapter_id, region_id)` — loads each
  entry, possibly across other documents; **skips** (does not error on)
  any target that no longer exists, so a stale reference degrades
  gracefully instead of breaking completion generation. Untranscribed
  targets are also skipped (with a warning log) rather than blocking —
  references are supplementary context, not the primary content being
  completed, so a partial or missing reference shouldn't stop exercise
  completion the way a missing `continues_to` tail blocks a breakdown.
- `combined_reference_text(resolved)` — concatenates each referenced
  region's `transcription_md`, each block labeled with a source
  breadcrumb (e.g. `[Source: 生きた素材で学ぶ — 第5課, p.120]`). Unlike
  `continues_to`'s deliberately unlabeled concatenation (one continuous
  text), these are discrete cited passages — a label per block helps
  both the model and the reader place where each piece came from,
  especially when it's from a different textbook.

## API

One endpoint, replace-whole-list semantics — the picker builds the
desired list locally and saves once:

`PUT /api/documents/{doc_id}/chapters/{chapter_id}/regions/{region_id}/references`
```json
{"references": [{"doc_id": "...", "chapter_id": "...", "region_id": "..."}, ...]}
```
- 400 if the *source* region's tag isn't `exercises`.
- 400 if any target region's tag isn't `reading_passage`.
- 404 if any target doc/chapter/region doesn't exist.

No new GET endpoint — the frontend already has `listDocuments` /
`listChapters` / `listRegions` / `getDocument` / `getChapter` to resolve
human-readable labels for the picker and the reference chips.

## Job / prompt changes

`_run_exercise_completion_job` (`jobs.py`) gains a second optional
context block, resolved the same way `region_transcription` already is
via the `continues_to` chain:

```python
references = region.get("references") or []
reference_text = (
    region_reference.combined_reference_text(
        region_reference.resolve_references(doc_id, chapter_id, region_id)
    )
    if references
    else ""
)
```

New `<reading_reference>` block in the prompt, inserted after
`<region_transcription>` and before `<target_sentence>`.
`EXERCISE_COMPLETION_PROMPT` gains a bullet describing the new input and
a task-instruction line to use it as background context when present.
Audited under the existing `exercise_completion` job type — no new audit
category.

## Frontend

- New `modules/reference-picker.ts`: a modal with a browse pane
  (Document → Chapter → Region, client-filtered to `reading_passage`)
  and a persistent ordered "selected" tray (chips, ✕ to remove, ↑/↓ to
  reorder) so multiple documents/chapters can be picked from in one
  session before saving. Reuses `listDocuments` / `listChapters` /
  `listRegions` — no new backend listing surface.
- Region-detail panel: new "References" section, visible only when
  `tag === "exercises"`, showing ordered chips like `① 第5課 本文
  (p.45) — 生きた素材で学ぶ` with an "Edit references" button that opens
  the picker pre-seeded with the current list.
- `region-drawer.ts` is untouched — this is a modal/list interaction,
  not a canvas click-to-link like `continues_to`'s link mode, since
  targets can be off-page or in a different document entirely.

## Testing

- Backend: storage round-trip (defaults to `[]`, add/replace/remove);
  API validation (400 on non-`exercises` source, 400 on non-
  `reading_passage` target, 404 on missing doc/chapter/region);
  `region_reference.resolve_references` (order preserved, cross-document
  resolution, missing-target skip, untranscribed-target skip); a job
  test with a mock provider asserting `<reading_reference>` appears in
  the prompt only when references are set.
- E2E: extend `smoke.spec.ts` — upload a second document, tag a
  `reading_passage` region in it, reference it from an `exercises`
  region in the first document's chapter, verify the reference chip
  renders and the mock-provider completion reflects the referenced
  context.

## Rollout

Ship as **beta**, matching the bulk-operations precedent
(`docs/bulk-operations-plan.md`) — real cross-document reference
behavior with real VLM prompts should get a first live run before
promoting out of beta.

## Out of scope (deferred)

- Reusable/named reference sets shared across multiple exercises
  regions — revisit if per-region duplication proves painful in
  practice.
- Search-by-title picker — browse-tree only for v1; a search endpoint
  doesn't exist today and isn't worth building until the library is
  large enough to need it.
- Cross-document dangling-reference cleanup on delete — resolved
  lazily; the UI should show a "missing" badge for an unresolvable
  entry rather than the backend scanning every document to clear
  backlinks on every delete.
- Per-item (rather than per-region) references — if a single exercises
  region turns out to need different reading references per numbered
  item, that's a bigger schema change deferred until proven necessary.
- Including the chapter's grammar guide as completion context (tracked
  separately under Phase 2.3's deferred list) — related but distinct
  from citing a reading passage.

## As built (2026-09-29)

Differences from the plan above, and decisions it left open:

- **One label per passage, not per region.** `combined_reference_text`
  groups *consecutive* references from the same chapter with the same
  region label under a single `[Source: <doc> — chapter "<title>",
  pp.A–B]` line, joining their text with a blank line like
  `region_chain.combined_transcription`. The motivating case (第5課 of
  生きた素材で学ぶ) is one reading split into six regions over pp.81–82,
  broken mid-sentence at the page turn; a label per region would have
  landed inside that sentence — the same leak that got `continues_to`'s
  inline page markers removed. A chapter or label change starts a new
  labeled block, so distinct cited passages stay separable.
- **References live on the exercises chain head.** Completions run from
  the head of a `continues_to` chain, so the endpoint 409s on a
  continuation region (matching the breakdown/completion endpoints).
  The chapter view shows the head's references for any region of the
  chain and edits the head's list.
- **No chain expansion.** A reference is exactly the region it names;
  referencing a `reading_passage` chain head does not pull in its
  `continues_to` tail. The picker's per-page "Add all" keeps picking
  every region of a multi-region reading cheap.
- **Duplicates are dropped** by the endpoint (first position wins), and
  **missing targets are dropped on save** by the picker (the endpoint
  404s on unknown targets, so a stale entry would otherwise block every
  edit). Until then a stale entry renders as "Missing" and is skipped at
  completion time.
- **New `question` exercise shape.** The completion prompt only knew
  fill-in (`open`) and closed-set (`constrained`) items; the
  comprehension questions this feature exists for (「〜とは何ですか。」,
  「筆者は〜と述べていますか。」) fit neither and risked `no_exercise`.
  `question` returns a model answer (not repeating the question), an
  English translation, an explanation quoting the deciding phrase from
  the reading, empty `filled_text`, and `examples: []` (accepted without
  the malformed-response retry). If the reading wasn't provided, the
  explanation says so ("The reading was not provided…"), which doubles
  as a hint to add references. `constrained` also gained a
  multiple-choice case (`answer` = the chosen option as printed).
- **Frontend**: the References section is its own block between the
  region cards and the transcription (`#region-references`), not part of
  the transcription pane; picker candidates are sorted in reading order
  (page, then top edge) and grouped by page.
