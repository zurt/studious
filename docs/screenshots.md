# Screenshots (`make shot`)

For a session that cannot open a browser window (a cloud session, an agent
in a terminal): take a PNG of any page of the app in a known state and look
at it.

```bash
make shot                                   # every named view
make shot SHOT="reading vocab"              # some of them
make shot SHOT="reading --dark"             # dark colour scheme
make shot SHOT="--list"                     # the named views
make shot SHOT="'/vocab?status=learning'"   # any path
make shot SHOT="chapter2 --click '#tracker-btn' --name tracker-open"
```

PNGs land in `frontend/screenshots/` (gitignored), named after the view,
with `-dark` / `-mobile` appended when those flags are set. All views take
about 16 seconds; one takes about 6, nearly all of it starting the stack.

## What it runs against

Each run starts its own stack and stops it afterwards:

- the backend on port 8776 with the mock VLM, no key, no WaniKani token,
  Anki pointed at a closed port and background speech off: the same
  isolation as `make dev-backend`;
- a **fresh** seed of the sample textbook (`backend/seed/`) in
  `backend/.shot-data`, wiped at the start of every run, so a view looks the
  same whatever an earlier run clicked;
- vite on port 5274.

The ports differ from the dev stack (8000/5173) and the E2E suite
(8775/5273), so a shot can be taken while either runs.

To shoot a stack that is already running, with whatever data it holds, pass
`--base-url`: `make shot SHOT="library --base-url http://localhost:5173"`.
Nothing is started, seeded or wiped then.

## Views, paths and placeholders

`make shot SHOT="--list"` prints the named views (`frontend/scripts/shot-lib.mjs`
holds them; add one there when a state is worth revisiting). Anything that
starts with `/` is taken as a path. Ids are generated at seed time, so paths
use placeholders:

| Placeholder | Stands for |
|---|---|
| `{doc}` | the document |
| `{chapter1}`, `{chapter2}` | a chapter, by position |
| `{region:<tag>}` | the first region with that tag in chapter 1 |
| `{page:<tag>}` | that region's page |
| `{region:<tag>:2}`, `{page:<tag>:2}` | the same, in chapter 2 |

```bash
make shot SHOT="'/doc/{doc}/chapter/{chapter2}?page={page:exercises:2}&region={region:exercises:2}' --name ch2-exercises"
```

## Getting the page into a state

Steps run in the order given, after the view's own steps and before the shot;
the helper waits for the network, fonts and images to settle after each.

| Option | Does |
|---|---|
| `--click SEL` | click the first match |
| `--hover SEL` | hover it |
| `--press KEY` | a key, in Playwright's names (`Escape`, `ArrowRight`, `?`) |
| `--fill SEL=TEXT` | type into a field |
| `--wait SEL` | wait until it is visible |

Framing: `--viewport WxH` (default 1440x900), `--mobile` (390x844),
`--full-page`, `--selector SEL` (one element), `--scale 2` (for a shot a
person will read), `--out DIR`, `--name NAME` (single target).

## What it prints

One line per PNG, then anything the page complained about while loading:
uncaught errors, `console.error` lines and HTTP responses of 400 and above.
A document page with no page-level transcription always shows one
`HTTP 404 …/pages/1/transcription`; that is how the app asks whether one
exists.

The exit code is 1 when a view could not be shot (a selector that never
appeared, a placeholder with nothing behind it), 2 for a bad argument.

## Limits

- It shows the mock stack: canned model output and the invented sample
  textbook, not real pages. `--base-url` is the way to look at real data, on
  the machine that has it.
- No comparison against earlier shots. Fonts differ between machines (a
  cloud session has no Hiragino or Yu Gothic), so pixel comparison would
  need pinned fonts first.
- `--mobile` only sets the viewport. The app has no narrow layout yet; the
  chapter view overflows sideways at 390 px.

## Chromium

The helper uses the Chromium that `npx playwright install chromium` fetched.
Where that is missing it falls back to `/opt/pw-browsers/chromium` (cloud
sessions ship one there). `STUDIOUS_CHROMIUM_PATH=/path/to/chrome` overrides
both, and `make test-e2e` honours the same variable.
