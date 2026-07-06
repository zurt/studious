# Transcription model comparison — Haiku 4.5 vs Sonnet 5 vs Opus 4.8

**Date:** 2026-07-06 · **Runs:** `20260706-eval-v1` (full) + `20260706-eval-v1-judge2` (vocab re-judge) · **Dataset:** `v1` (seed 20260706, 31 items) · **Judge:** `claude-fable-5` (blind) · **Total API spend:** ~$5.60

## Verdict

**Sonnet 5 is statistically tied with Opus 4.8 on transcription quality at ~2.3× lower
cost, and wins on the low-quality workbook scans. Haiku 4.5 is not viable for this
task.** The default VLM was switched to `claude-sonnet-5` on the strength of this run;
Opus 4.8 remains selectable and leads on full pages and grammar tables.

## League table (corrected judgments, 31 items)

| Model | Mean overall | Mean rank | #1 count | char acc | complete | format | halluc ctrl | Median latency | Cost/item |
|---|---|---|---|---|---|---|---|---|---|
| claude-opus-4-8 | **8.81** | 1.39 | 19/31 | 9.48 | 9.48 | 8.29 | 9.19 | 10.5 s | $0.026 |
| claude-sonnet-5 | **8.71** | 1.61 | 12/31 | 9.32 | 9.26 | 8.00 | 9.58 | 8.1 s | $0.011 |
| claude-haiku-4-5 | **5.81** | 3.00 | 0/31 | 6.65 | 8.10 | 6.10 | 6.81 | 5.8 s | $0.004 |

Head-to-head (exact binomial sign test on ranking preference):

| Pair | Wins | p-value | Read |
|---|---|---|---|
| Opus 4.8 vs Sonnet 5 | 19–12 | 0.28 | statistical tie at n=31 |
| Opus 4.8 vs Haiku 4.5 | 31–0 | <0.0001 | decisive |
| Sonnet 5 vs Haiku 4.5 | 31–0 | <0.0001 | decisive |

## Where each model wins (mean overall by segment)

| Segment | n | Opus 4.8 | Sonnet 5 | Haiku 4.5 | Leader |
|---|---|---|---|---|---|
| Textbook (clean print) | 22 | **9.05** | 8.68 | 5.91 | Opus |
| Workbook (rough scans) | 9 | 8.22 | **8.78** | 5.56 | Sonnet |
| Full pages | 6 | **9.00** | 8.67 | 4.83 | Opus |
| Exercises | 12 | 8.42 | **8.67** | 5.75 | Sonnet |
| Grammar points | 5 | **9.20** | 8.60 | 6.80 | Opus |
| Vocab lists (re-judged) | 4 | **9.25** | **9.25** | 6.50 | tie |
| Reading passages | 3 | **8.67** | **8.67** | 5.33 | tie |
| Instructions | 1 | **9.00** | 8.00 | 6.00 | Opus |

Haiku's failures are study-breaking character misreads, not formatting slips:
ニンジャライス for ニンジンライス (then glossed "ninja rice"), 魅める（なぐめる）for
慰める（なぐさめる）, レジピ for レシピ, wrong furigana (せっている for せってい),
invented furigana not in the image. A learner would memorize wrong words.

## Correction: the vocab "hallucinated glosses" were intended behavior

The first judging pass penalized all three models heavily on vocab lists for
"inventing" English glosses (hallucination-control scores of 3.0–3.8). Investigation
showed `VOCAB_LIST_TRANSCRIBE_PROMPT` **explicitly instructs** the transcriber to
supply a short dictionary-style gloss when the printed list has none — a deliberate
study feature, not a model failure. The judge prompt now explains this policy for
`vocab_list` items and scores gloss *accuracy* instead of gloss *presence*
(`judge_cmd.build_judge_content`).

Re-judging the 4 vocab items against the same frozen transcriptions
(`20260706-eval-v1-judge2`):

| Model | Overall before → after | Halluc-ctrl before → after | Read |
|---|---|---|---|
| claude-opus-4-8 | 6.50 → **9.25** | 3.50 → **10.00** | penalty was judge artifact |
| claude-sonnet-5 | 6.75 → **9.25** | 3.75 → **10.00** | penalty was judge artifact |
| claude-haiku-4-5 | 4.75 → **6.50** | 3.00 → 7.50 | still low — its glosses are *wrong* |

## Method

- **Dataset** (`dataset/v1`, gitignored images, rebuilds byte-identically from the
  manifest seed): stratified sample of 17 textbook regions across all five tags,
  7 workbook exercise regions, 6 full pages. Items are the exact bytes the production
  pipeline sends (same crop/resize/prompts).
- **Transcription:** 93 calls through the production `anthropic` provider. 93/93 ok.
- **Judging:** one Fable call per item — source image + all candidates, anonymized and
  order-shuffled per item; 4-dimension rubric (0–10) + strict ranking, structured
  outputs. 35/35 ok, zero refusals.
- **Latency note:** medians reported. The Opus *mean* (30.8 s) is skewed by one 622 s
  call that the SDK retried through successfully.

## Caveats

- n=31, single LLM judge, no human ground truth. Small per-tag cells (reading n=3,
  instructions n=1) are directional only.
- Judge and candidates are from the same model family and may share blind spots.
- Sonnet 5 cost uses launch pricing ($2/$10 per MTok) in effect through 2026-08-31;
  at sticker ($3/$15) the cost advantage over Opus narrows from ~2.3× to ~1.6×.

## On expanding the dataset

Deciding Opus-vs-Sonnet at this margin (19–12) would need roughly 150–200 items for
adequate statistical power — ~$25–35 per full run and several hours of marked-region
curation for little decision value, because a gap this small doesn't change the
choice: at similar quality, cost/latency decide, and Sonnet 5 wins those. **Keep the
31-item set as a fixed regression benchmark instead**, re-running it (~$4.50) when a
new model tier ships, when transcription prompts change, or when image preprocessing
changes. Expand only if a future decision hinges on a near-tie in a specific segment
(add items to that stratum, not everywhere), or if workbook coverage grows beyond
`exercises` once more workbook regions are marked.
