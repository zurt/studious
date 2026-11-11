# Transcription model comparison — Sonnet 5.5, Opus 5.5, Haiku 5.5 vs Sonnet 5 and Opus 4.8

**Date:** 2026-11-11 · **Run:** `20261111-eval-v2` · **Dataset:** `v2` (seed 20261111, 47 items) · **Judge:** `claude-fable-5-2` (blind; judged all 47 itself, no fallback used) · **API spend:** $8.71 ($4.09 transcription + $4.62 judging)

## Verdict

**Opus 5.5 is the best transcriber by a clear margin, and the current default, Sonnet 5.5,
is the weakest of the five.** Opus 5.5 never scored below 8 on any item. Sonnet 5.5's
problem is specific: it invents furigana the page does not print, most of all on
workbook pages.

**Recommendation: switch the default VLM to `claude-opus-5-5`.** It costs about 2.6×
Sonnet 5.5 per item ($0.031 vs $0.012), which for one user is cents per chapter.

## League table (47 items)

| Model | Mean overall | Mean rank | #1 count | Items ≤ 6 | char acc | complete | format | halluc ctrl | Avg latency | Cost/item |
|---|---|---|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | **9.02** | 2.04 | 23/47 | 0 | 9.96 | 9.68 | 8.23 | 9.85 | 7.5 s | $0.031 |
| claude-sonnet-5 | **8.15** | 3.15 | 7/47 | 4 | 9.26 | 9.26 | 7.83 | 9.00 | 4.5 s | $0.012 |
| claude-haiku-5-5 | **8.11** | 3.34 | 4/47 | 6 | 9.34 | 9.32 | 7.60 | 9.13 | 7.3 s | $0.0012 |
| claude-opus-4-8 | **7.87** | 2.98 | 7/47 | 9 | 9.00 | 9.40 | 7.83 | 8.36 | 10.6 s | $0.031 |
| claude-sonnet-5-5 | **7.70** | 3.49 | 6/47 | 11 | 9.09 | 9.57 | 7.26 | 7.91 | 3.6 s | $0.012 |

Head-to-head (exact binomial sign test on ranking preference, n=47):

| Pair | Wins | p-value | Read |
|---|---|---|---|
| Opus 5.5 vs Sonnet 5.5 | 36–11 | 0.0003 | decisive |
| Opus 5.5 vs Haiku 5.5 | 36–11 | 0.0003 | decisive |
| Opus 5.5 vs Sonnet 5 | 34–13 | 0.003 | decisive |
| Opus 5.5 vs Opus 4.8 | 33–14 | 0.008 | strong |
| Sonnet 5 vs Sonnet 5.5 | 28–19 | 0.24 | not significant |
| Opus 4.8 vs Sonnet 5.5 | 28–19 | 0.24 | not significant |
| Haiku 5.5 vs Sonnet 5.5 | 25–22 | 0.77 | tie |
| Haiku 5.5 vs Sonnet 5 | 24–23 | 1.00 | tie |
| Opus 4.8 vs Sonnet 5 | 24–23 | 1.00 | tie |
| Opus 4.8 vs Haiku 5.5 | 29–18 | 0.14 | not significant |

Ten pairs were tested, so a single p below 0.05 is weak evidence. Opus 5.5's wins over
Sonnet 5.5, Haiku 5.5 and Sonnet 5 survive a Bonferroni correction (threshold 0.005);
its win over Opus 4.8 is just outside it. Nothing separates the other four from each
other.

## Where each model wins (mean overall by segment)

| Segment | n | Opus 5.5 | Sonnet 5 | Haiku 5.5 | Opus 4.8 | Sonnet 5.5 |
|---|---|---|---|---|---|---|
| Textbook regions | 23 | **8.96** | 8.74 | 8.30 | 8.61 | 8.35 |
| Textbook full pages | 8 | **8.88** | 7.50 | 7.75 | 8.25 | 7.50 |
| Workbook regions | 10 | **9.00** | 7.90 | 8.20 | 7.10 | 7.40 |
| Workbook full pages | 6 | **9.50** | 7.17 | 7.67 | 5.83 | 6.00 |
| Exercises | 16 | **9.00** | 8.31 | 8.56 | 7.94 | 7.81 |
| Grammar points | 6 | **8.83** | 7.83 | 7.33 | 8.33 | 8.00 |
| Reading passages | 5 | **9.20** | **9.20** | 8.40 | 7.80 | 7.80 |
| Vocab lists | 5 | 9.00 | 8.80 | 8.20 | 8.80 | **9.20** |
| Instructions | 1 | 8.00 | **10.00** | 9.00 | 9.00 | 8.00 |

Opus 5.5 leads or ties every segment with more than one item except vocab lists, where
Sonnet 5.5 edges it by 0.2 on five items. The gap is widest exactly where the other
models are weakest: workbook full pages.

## The failure that separates them: invented furigana

The transcription prompts say to transcribe furigana only where it is printed. The
judge's notes flag added, unprinted furigana on:

| Model | Items flagged (of 47) | Hallucination control, workbook pages |
|---|---|---|
| claude-opus-5-5 | 3 | 9.83 |
| claude-sonnet-5 | 7 | 7.83 |
| claude-haiku-5-5 | 7 | 7.67 |
| claude-opus-4-8 | 10 | 5.67 |
| claude-sonnet-5-5 | 17 | **4.00** |

Sonnet 5.5 typically gets the base text right and then annotates nearly every kanji
with a reading (`日本(にほん)`, `人(ひと)`, `多(おお)` …) on pages that gloss only a
handful of words. On two items it also wrote its own second thoughts into the
transcription ("Wait — furigana is not printed…", "※ Furigana is only transcribed where
it is printed.") and then restarted. For a learner this is not cosmetic: invented
readings are indistinguishable from the book's own, and they remove the reading
practice the page intends.

Opus 4.8 shows the same habit on workbook pages (it scored 6 or below on four of the six),
which matches July, when it also lost the workbook segment.

Haiku 5.5's weak items are different in kind: actual misreads (`量(ふ)` for りょう,
ませ for ます in a grammar formula, 3.3 for 4.3 in a chart) and dropped page furniture.
At a tenth of Sonnet's cost it ties both Sonnets overall, but a misread grammar formula
is the worst kind of error for this tool.

## How this relates to July

The July run (`v1`, 31 items, judged by `claude-fable-5`) found Opus 4.8 and Sonnet 5
tied, 8.81 vs 8.71. Here the same two are still tied head-to-head (24–23) at 7.87 vs
8.15. The tie reproduces; the absolute scores do not carry over, because the judge,
the dataset and the share of full pages and workbook items all changed. `v1` no longer
exists, so no item-level comparison is possible.

The September switch of the default from Sonnet 5 to Sonnet 5.5 rested on `make
benchmark` CER figures. This run does not support it: Sonnet 5 is preferred 28–19
(not significant) and has a markedly better hallucination-control score (9.00 vs 7.91).

## Method

- **Dataset** (`dataset/v2`, gitignored, built from the local store): 23 textbook
  regions across five tags, 10 workbook exercise regions, 8 textbook and 6 workbook
  full pages. One stratum fell short (only one `instructions` region exists). Items
  are the exact bytes the production pipeline sends.
- **Transcription:** 235 calls through the production `anthropic` provider, all at
  effort `high` with adaptive thinking. 235/235 ok.
- **Judging:** one Fable 5.2 call per item — source image plus all five candidates,
  anonymized and order-shuffled per item; four rubric dimensions plus overall (0–10)
  and a strict ranking, structured outputs. 47/47 ok, zero refusals, every item
  answered by Fable 5.2 itself.
- The transcriptions themselves are not committed (the repository is public and they
  reproduce textbook content); judgments, analysis and run metadata are.

## Caveats

- n=47, a single LLM judge, no human ground truth. Per-tag cells are small (reading
  n=5, vocab n=5, instructions n=1) and directional only.
- Judge and candidates are from the same model family and may share blind spots. The
  furigana finding is the least exposed to this: it is a checkable claim about what is
  printed, and the judge's notes list the specific invented readings.
- Opus 5.5 costs the same per item as Opus 4.8 despite a 20% lower token price, so it
  is using more tokens, presumably thinking. Its cost advantage over Opus 4.8 is zero
  in practice.
- The app's model setting applies to every job type. This run measures transcription
  only; it says nothing about breakdowns, exercise completions or grammar guides.

## Open questions

- **Is Sonnet 5.5's furigana habit prompt-fixable?** If a prompt change stopped it,
  Sonnet 5.5 would be a far cheaper, faster default. Testing that costs about $1.10
  (re-run one model on `v2`, re-judge).
- **Is Haiku 5.5 good enough for bulk work?** At $0.0012 an item it could cover
  low-stakes passes, but its errors are misreads, which matter most here.
