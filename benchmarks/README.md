# Benchmarks

Two tools, two different questions. Both make real API calls and cost money.

| | Regression benchmark | Model comparison |
|---|---|---|
| Question | "Did my change make the shipping setup worse?" | "Which model should we ship?" |
| Run it | `make benchmark` | `python -m benchmarks.model_eval ...` |
| When | After changing prompts, the provider, image preparation or `backend/app/jobs/` | When new models appear, or before changing the default |
| Models | The app's default model only | Any set you name |
| Data | `fixtures/` + `ground-truth/`, committed | A frozen sample of your own store, **not** committed |
| Scoring | Judge vs. image + reviewed reference, plus CER | Blind judge ranks the candidates |
| Size / cost | 6 transcriptions + 1 breakdown; cents | 48 items x 5 models; roughly $10, capped with `--budget-usd` |
| Docs | this file, `fixtures/README.md` | `model_eval/README.md` |

Both use the same judge, rubric and price table (`model_eval/judging.py`,
`model_eval/pricing.py`, which reads `backend/app/config.py`'s
`MODEL_PRICING`), so a score means the same thing in either.

## Regression benchmark

```bash
make benchmark                                   # run, with the judge
uv run --project backend python -m benchmarks.run_benchmark --no-judge   # string metrics only
uv run --project backend python -m benchmarks.compare \
    benchmarks/results/<before>.json benchmarks/results/<after>.json
```

The workflow is before/after: run it on `main`, make your change, run it
again, then `compare`. `compare` exits 1 if any fixture regressed.

Each image fixture gets two scores:

- **Judge (0-10 per rubric dimension).** A stronger model grades the
  transcription against the image the transcriber saw and the reviewed
  reference in `ground-truth/`. This is the score to act on. A fixture
  regresses when `overall` drops by a point or more.
- **CER and line accuracy** against the reference. Free and deterministic,
  but a wrong furigana reading costs one character however much it matters
  to a learner, and a harmless markdown difference can cost dozens. It is
  the fallback when a judge score is missing, not a verdict.

The breakdown fixture is checked structurally (sentence count, vocab
recall); the judge does not score it.

Results land in `results/` (gitignored). Each file records the git sha, the
transcription model and the judge model. Judge scores from different judge
models are not comparable, and `compare` says so when they differ.

### Limits worth knowing

- **Six image fixtures, five of them vocab lists from one book.** A pass
  means "no obvious damage", not "quality held everywhere".
- **The judge is a model.** Scores wobble by about a point run to run, which
  is why the regression threshold is a full point.
- **It tests the app's configured default model**
  (`settings.default_vlm_model`), not whatever is selected in the settings
  UI on your machine.

## Model comparison

See `model_eval/README.md`. In short: `build-dataset` freezes a sample of
your store, `run` transcribes it with each model, `judge` ranks the results
blind, `analyze` writes the league table. Curated write-ups of past runs are
in `model_eval/reports/`.
