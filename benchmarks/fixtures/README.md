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
4. Run `make benchmark` to verify
