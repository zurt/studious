# Benchmark Fixtures

Place test documents here for quality benchmarking.

## Structure

Each fixture is a directory named with a short identifier:

```
fixtures/
  sample-01/
    input.png          # or input.pdf (single-page PDF or image)
  sample-02/
    input.pdf
```

For each fixture, create a corresponding ground-truth file in `../ground-truth/`:

```
ground-truth/
  sample-01.md         # expected markdown transcription
  sample-02.md
```

## Adding a Fixture

1. Create a directory under `fixtures/` with a descriptive name
2. Place the source document as `input.png`, `input.jpg`, or `input.pdf`
3. Create the expected transcription in `ground-truth/<name>.md`
4. (Optional) Add `meta.json` to override the prompt for non-page fixtures
5. Run `make benchmark` to verify

### Selecting a prompt (`meta.json`)

By default fixtures run against the page-level VLM prompt. To benchmark a
region or vocab-list fixture, drop a `meta.json` in the fixture dir:

```json
{ "prompt_kind": "vocab_list" }
```

Valid `prompt_kind` values: `page` (default), `region`, `vocab_list`.

### Breakdown fixtures (`kind: "breakdown"`)

Breakdown fixtures evaluate the sentence-breakdown tool-use path. The input
is a transcription text file (`input.md` or `input.txt`), not an image, and
ground truth lives in `meta.json` rather than a separate file:

```
fixtures/
  breakdown-simple-passage/
    input.md
    meta.json
```

```json
{
  "kind": "breakdown",
  "expected_sentence_count": 3,
  "expected_vocab": ["コーヒー", "犬", "公園"]
}
```

The runner reports actual vs expected sentence count and vocab recall (a
term counts as found if it appears in any sentence's text, gloss, or vocab
entries).
