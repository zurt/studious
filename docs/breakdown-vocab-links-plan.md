# Sentence ↔ Vocab/Grammar Link Plan

Follow-on feature for Phase 2 sentence breakdowns. Goal: when a user reads
a sentence card, every vocab/grammar item from the card's lists should be
clickable inline in the sentence text, opening a floating panel with the
entry's reading + meaning (vocab) or pattern + explanation (grammar).

## Scope of this plan: vocab only

Grammar linking is **deferred**. Grammar patterns (`〜ます`, `〜ている`,
`Vば〜ほど`, …) are templates with placeholders and particles, not surface
strings — rule-based substring/stem matching either misses them or
mis-anchors (e.g., `〜ます` would match every polite verb in the sentence
indiscriminately). Shipping wrong grammar links next to correct vocab
links would erode trust in both.

Iter 1–2 below cover vocab only. Iter 3 picks up grammar via the
LLM-span path (see "LLM-span iteration" further down), which is the
only approach that can identify the right grammar span reliably. The
grammar table continues to render as today until that iteration lands.

## Scope

- Linking is **per sentence**, not across the whole breakdown — a vocab
  entry on sentence 2 does not light up occurrences in sentence 5.
- Links are computed once and persisted alongside the breakdown.
- Regenerating the breakdown invalidates and recomputes links.
- Opening a region whose breakdown predates this feature lazy-computes
  links on first render and writes them back to disk.

## Data model

Extend each sentence in the breakdown JSON with a `links` array:

```json
{
  "text": "わたしは毎朝コーヒーを飲みます。",
  "gloss": "I drink coffee every morning.",
  "vocab": [{ "word": "コーヒー", "reading": "", "meaning": "coffee" }],
  "grammar": [
    { "pattern": "〜ます", "explanation": "polite non-past", "surfaces": ["ます"] }
  ],
  "links": [
    { "start": 4, "end": 8, "kind": "vocab", "index": 0, "match": "exact" },
    { "start": 11, "end": 13, "kind": "grammar", "index": 0, "match": "llm" }
  ]
}
```

- `start`/`end` are character offsets into `text` (Unicode code points,
  not UTF-16 — JS string indexing is fine here because none of these
  characters are surrogate pairs in practice, but document the choice).
- `kind` + `index` point back into the sentence's `vocab` or `grammar`
  arrays — the same sentence holds the entry, so no cross-sentence refs.
- `match` records how the link was found (`exact` | `stem` | `reading`
  for vocab; `llm` for grammar). Useful for debugging and for the UI
  to optionally style low-confidence matches differently later.
- `extras` (optional): when a shorter overlapping link has been merged
  into this one, each entry is `{kind, index}` referring back into
  the sentence's vocab/grammar arrays. The popover renders the
  primary plus each extra in vocab-then-grammar order.

Backward compatibility: `links` is optional; absence means "not yet
computed" (the on-the-fly path will handle that).

## Linking algorithm

Pure-Python, runs in the breakdown job after the LLM call succeeds and
before `save_breakdown`. Implementation lives in
`backend/app/services/breakdown_links.py`. **Vocab only** — grammar
entries are skipped by the linker.

For each sentence, for each vocab entry:

1. **Exact match**: substring search of `entry.word` (vocab) or
   `entry.pattern` (grammar) in `sentence.text`. Take the first
   occurrence; record `match=exact`.
2. **Reading match** (vocab only): if 1 fails and `entry.reading` is
   present and non-empty, substring search the reading. Record
   `match=reading`.
3. **Stem match**: if 1 and 2 fail, drop trailing hiragana characters
   from the entry's surface form to obtain a "stem" (the leading kanji
   run, or — if the surface is all kana — the first ~⅔ of characters).
   Substring-search the stem in the sentence. Require the stem to be at
   least one character and, if it's pure hiragana, at least 2 characters
   to avoid runaway matches. Record `match=stem`.
4. If all three fail, drop the entry from `links` (no link emitted).

Overlap handling: if two entries claim overlapping spans, keep the
longer span; on tie, keep the one found via the higher-priority
strategy (`exact` > `reading` > `stem`).

## Naive stemming failure modes

The "drop trailing hiragana" stemmer is good enough for ~80% of vocab
cases (most verbs and i-adjectives) but has predictable failure modes:

- **Homograph collision.** `入る` (to enter) and `入れる` (to put in)
  both stem to `入`. A sentence containing one will incorrectly link to
  the other if both happen to be in the same vocab list.
- **Common single-kanji stems.** `行く` stems to `行`, which appears
  inside `銀行`, `行う`, `旅行` etc. We mitigate by requiring stem
  length ≥ 1 *and* the matched span not being a substring of a longer
  kanji run — i.e., reject matches where the character immediately
  before or after the span is also kanji. This catches the `銀行`
  case cheaply.
- **Suru-verbs.** `勉強する` stems to `勉強`, which is correct, but
  `勉強します` in the sentence won't be exact-matched. Stem path
  handles this fine.
- **Pure-kana inflections.** `おいしい` → `おいしかった` will not
  link (stem of `おいしい` is `おい`, too short; we'd reject). Accepted
  loss; mark `match=null` and emit nothing.
- **Compound vocab the model split.** Sentence has `自己評価`, vocab
  list has separate entries `自己` and `評価`. Both will link to
  adjacent spans; overlap rule keeps both since they don't overlap.
  This is correct.

For vocab, ship the stemmer first; the failure modes above are
acceptable losses at the rate they occur. The LLM-span path (next
section) can upgrade vocab accuracy later if real usage shows the
stemmer is the bottleneck — but its primary motivation is grammar,
which the stemmer cannot handle at all.

## Where the linker runs

1. **After generation (primary path).** In `jobs.py`'s
   `_run_breakdown_region`, after the tool response validates and
   before `storage.save_breakdown`, call
   `breakdown_links.annotate(breakdown_data)` to populate `links` on
   each sentence. Cost: negligible (pure string ops).
2. **After regeneration.** Same path — regen calls the same job
   handler; nothing extra to do.
3. **Lazy on read (compatibility).** In the `GET .../breakdown`
   endpoint, if any sentence is missing `links`, run `annotate(...)`,
   write it back to disk via `save_breakdown`, and return the
   annotated payload. This handles breakdowns generated before this
   feature shipped without forcing a manual recompute. Idempotent —
   a second GET sees `links` already present and skips the write.

The frontend never computes links. If the API returns a breakdown
without `links`, render the sentence un-linked rather than trying
client-side.

## Frontend

`frontend/src/modules/breakdown-pane.ts`:

- When rendering a sentence, splice the `text` into segments using
  `links` (sorted by `start`). Each linked span becomes a
  `<button class="bd-link" data-kind="vocab" data-idx="N">…</button>`
  inside the sentence container; unlinked text stays as plain text
  nodes.
- Style: `.bd-link` gets a `text-decoration: underline dashed
  var(--accent-soft)` (a new CSS variable, light/muted); no
  background, no color change — keeps the sentence readable.
- Click handler on the sentence container (delegated): on a `.bd-link`
  click, look up the entry in the sentence's `vocab` or `grammar`
  array by index and open a floating panel anchored just below the
  clicked span.
- Floating panel: small DOM element (`.bd-link-popover`) appended
  to the sentence container. Position: `position: absolute`, top
  computed from the link's `getBoundingClientRect()` relative to the
  card. Closes on outside click, on Escape, or on clicking another
  link (which opens its own panel). Reuse the popover element
  across clicks rather than creating one per click.
- Content: for vocab — word (large), reading (muted), meaning. For
  grammar — pattern (large, monospace if possible), explanation.

Accessibility:
- The link buttons are real `<button>` elements (focusable, keyboard
  activatable).
- Popover gets `role="dialog"` + `aria-label` describing the entry.
- Closing returns focus to the originating button.

## Iterations

### Iter 1 — Backend vocab linker + storage + lazy migration

- New `services/breakdown_links.py` with `annotate(breakdown)` →
  mutates each sentence to add `links` for vocab entries only. Pure
  function, easy to test.
- Wire into `jobs.py` post-tool-response path.
- Wire into `api/regions.py` `GET .../breakdown` lazy-fill path.
- Tests:
  - Exact match for kana vocab (e.g., `コーヒー`)
  - Stem match for verb (`飲む` ↔ `飲みます`)
  - Reading-fallback for vocab whose `word` isn't in sentence but
    `reading` is
  - Homograph guard: `行` inside `銀行` is not linked when vocab is
    `行く`
  - Overlap resolution: longer span wins
  - Lazy-fill: GET on a breakdown without `links` writes them back

**Done when:** every region in `make benchmark`'s breakdown fixture
gets at least one vocab link per sentence and the file on disk has
`links` populated.

### Iter 2 — Frontend rendering (vocab)

- `breakdown-pane.ts` splices linked spans into the sentence text.
- Dashed-underline style; new `--accent-soft` CSS variable.
- Click → floating panel; outside-click + Escape close.
- Keyboard: Tab to a link, Enter/Space opens panel, Escape closes.
- Grammar table renders unchanged (no inline links yet).

**Done when:** clicking a vocab term in the sentence shows the same
content the user already sees in the vocab table just below.

### Iter 3 — Grammar links via LLM spans

Rule-based matching cannot reliably identify grammar spans, so this
iteration moves the source of truth to the LLM.

- Extend `BREAKDOWN_TOOL_SCHEMA` so each grammar entry includes a
  required `surfaces: string[]` — literal substrings of `text` that
  anchor the pattern. We tried character offsets first; the model
  cannot count CJK code-points reliably across long sentences and
  produced spans off by 5+ chars. Surfaces sidestep counting: the
  model copies short substrings (which it does well) and the
  linker locates them via `text.find`.
- Update the breakdown prompt to instruct the model to emit
  `surfaces` for each grammar entry — single-anchor patterns
  produce one surface (`〜ます` → `["ます"]`), range/pair patterns
  produce one per anchor (`〜から〜まで` → `["から", "まで"]`).
- Linker emits one `kind="grammar"` link per surface with
  `match="llm"`. Repeated identical surfaces in the sentence are
  disambiguated by skipping occurrences already claimed at the
  exact same span by earlier grammar links — different surfaces
  (e.g., `的` inside `社会文化的な`) are allowed to overlap.
- Overlap merging: when two links cover overlapping ranges, the
  longer/higher-priority one renders the underline; the loser is
  attached as `extras: [{kind, index}]` on the primary link so the
  popover can show both. Extras are sorted vocab-before-grammar so
  the popover always opens with the vocab section.
- Frontend reuses the popover; grammar content shows pattern +
  explanation as already specified.
- Run `make benchmark` — this touches the prompt, so the benchmark
  is required.

**Done when:** real reading material shows grammar terms underlined
inline in the sentence and clicking them opens the explanation.

### Iter 4 — Polish

- Always render every vocab/grammar entry (linked or not), but
  hide the answer content behind a per-card show/hide toggle that
  defaults to **hidden**. Goal: the reader should try the sentence
  first using the inline links, not pre-read the table. The
  popover remains the primary lookup affordance; the table is the
  reveal-everything view.
- Hiding must not collapse layout — that would shift the page when
  toggled and make the toggle itself move under the cursor. Keep
  the rows in the DOM at full height and mask their content
  instead (e.g. `visibility: hidden` on the reading/meaning cells,
  or a same-height blurred/blanked overlay). The row's word/pattern
  column stays visible so the table still reads as a list of items
  to look up.
- Telemetry/log at `INFO` level: count of links per sentence broken
  down by kind and match strategy (`exact`/`reading`/`stem`/`llm`).
  Helps decide whether to extend LLM spans to vocab.
- Update `troubleshooting.md` with entries for "vocab term doesn't
  link in the sentence" (stemmer limits) and "grammar term doesn't
  link" (model omitted a span / span out of range).

**Done when:** docs updated; one passage of real reading material
verified end-to-end.

## Critical files

| File | Change |
|------|--------|
| `backend/app/services/breakdown_links.py` | new — vocab linker (Iter 1); grammar span pass-through (Iter 3) |
| `backend/app/jobs.py` | call linker post-tool-response |
| `backend/app/api/regions.py` | lazy-fill on GET |
| `backend/app/services/breakdown_schema.py` (or wherever `BREAKDOWN_TOOL_SCHEMA` lives) | add grammar `span` field (Iter 3) |
| breakdown prompt | instruct model to emit grammar spans (Iter 3) |
| `backend/tests/test_breakdown_links.py` | new — unit tests |
| `frontend/src/modules/breakdown-pane.ts` | render linked spans + popover |
| `frontend/src/styles.css` | dashed underline + popover styles |

## Out of scope (for now)

- Cross-sentence links (vocab from sentence 2 highlighting in sentence 5)
- Linking into the gloss text
- Linking to the global vocab store (Phase 3)
- Morphological analysis (kuromoji/MeCab) — revisit only if stemmer
  accuracy is shown insufficient on real content
