# macOS App (Phase 5 — native Mac study + backend bridge)

**Status:** Planned 2026-07-05. Builds on the iOS companion
(`docs/ios-app-plan.md`); no new sync design — the Mac app sits directly
on the canonical store.

## Goal

A native macOS app with feature parity with the iOS companion — FSRS
study sessions, vocab/grammar browsing and curation, import/export —
that also acts as the bridge to the local FastAPI backend: it reads and
writes the backend's canonical JSONL store directly, so edits and
reviews made in the Mac app appear in the web app immediately (and vice
versa), with no sync layer, no HTTP, and no Apple developer account.

## Why this is cheap

The iOS spike deliberately put everything into the cross-platform
SwiftPM package:

- `StudiousUI` already declares `.macOS(.v14)` and compiles on macOS
  today (it's the package's compile check). `RootView`, `StudyView`,
  `ItemListView`, and `SettingsView` are plain SwiftUI with no
  UIKit-only API — `fileImporter`, `ShareLink`, `Form`, `TabView` all
  exist on macOS.
- `AppModel.init(directory:)` already takes an arbitrary store
  directory.
- `JSONLStore` already mirrors the backend's mtime+size cache
  invalidation (`reloadIfChanged()` runs on every read), so external
  appends by the backend or the sync CLI are picked up automatically.
  The backend's own caches work the same way in the other direction,
  and both sides write append+fsync — the file is the interface.

So the Mac app is: a new executable target that instantiates the
existing UI against the backend's data directory, plus a small amount
of macOS-specific glue.

## What ships

```
apple/StudiousKit/Sources/
  studious-mac/           new executable target (macOS-only product)
    StudiousMacApp.swift    @main SwiftUI App wrapping RootView
    DataDirectory.swift     data-dir resolution (arg/env/defaults)
  StudiousUI/             small cross-platform adjustments (see below)
  studious-tests/         new tests: data-dir resolution, external-
                          change detection
Makefile                  `make run-mac` target
```

Like `studious-sync`, the target needs no platform guards: iOS builds
of the package only pull the `StudiousUI` library product, so the
executable targets are never compiled for iOS.

## Data directory ("bridge" mode vs standalone)

Same semantics as the `studious-sync` CLI: the app takes a *data dir*
(e.g. `backend/data`) and appends `store/`. Resolution order:

1. `--data-dir PATH` process argument
2. `STUDIOUS_DATA_DIR` environment variable
3. `studious.dataDir` UserDefaults value (set from Settings)
4. Fallback: the app's own Application Support store (standalone mode,
   identical to iOS behavior)

`make run-mac` passes the repo's `backend/data`, so the default dev
experience is bridge mode against the real store. The executable is not
sandboxed, so a plain path in UserDefaults suffices (no security-scoped
bookmarks).

## External-change refresh

`JSONLStore.reloadIfChanged()` already handles correctness; what's
missing is a *trigger* — SwiftUI re-queries the stores only when
`AppModel.storeGeneration` bumps, which today happens only on the app's
own mutations. Add:

- `ItemStore`/`ReviewLog`: expose a cheap `hasExternalChanges` check
  (compare current file signature against the loaded one — the
  comparison `reloadIfChanged()` already performs, without the reload).
- `AppModel.refreshIfChangedOnDisk()`: if any of the three files moved,
  bump `storeGeneration`.
- `studious-mac` calls it from a ~2 s foreground timer. Polling matches
  the mtime+size approach used everywhere else in the project; no
  DispatchSource/FSEvents machinery unless the poll proves inadequate.

Deliberate consequence: a study session's queue is a snapshot (queue is
built when the session starts), but list views and stats stay live.

## macOS UI adjustments (all small, all in StudiousUI)

- **Window sizing:** minimum content size (~720×480) on the root view
  under `#if os(macOS)` so the tab layout doesn't collapse.
- **Activation:** a bare SwiftPM executable launches as an accessory
  process; `NSApplication.shared.setActivationPolicy(.regular)` +
  `activate()` at startup so it gets a real window, Cmd-Tab presence,
  and menu bar.
- **Hide iCloud sync on macOS:** add `AppModel.syncSupported`
  (`false` on macOS for now) and gate the Settings sync section on it.
  An unsigned process has no iCloud entitlement — `CKContainer` access
  would throw/crash if the user flipped the toggle. CloudKit on the Mac
  stays the `studious-sync` CLI's job (and in bridge mode the Mac app
  doesn't need sync at all: it *is* the canonical store).
- **Settings additions (macOS only):**
  - Data directory row: show the resolved path + how it was resolved;
    "Change…" via `fileImporter(allowedContentTypes: [.folder])`,
    persisted to UserDefaults (takes effect on relaunch — AppModel's
    stores are constructed once at init; a relaunch note is simpler and
    safer than teardown/rebuild of live stores and sync state).
  - Backend row: poll `GET /api/health` on `http://127.0.0.1:8000`
    (URL overridable via `studious.backendURL` default) and show
    running/not-running; "Open web app" link to the frontend. Purely
    informational — the app never needs the backend to function.
- **Import/export keeps working as-is** and replaces the CLI for the
  common round-trip: Settings → Import on the Mac app *is*
  `studious-sync merge` (same `AppModel.importJSONL` LWW/union code
  path), which means pulling an iOS export into the canonical store no
  longer requires the terminal.

## Testing (CLT-only, `swift run studious-tests`)

- Data-dir resolution: precedence of arg/env/defaults/fallback, and
  the `store/` suffix behavior (pure function over injected inputs).
- External-change detection: write store → external append via a second
  store instance → `hasExternalChanges` true → refresh bumps behavior
  observable via re-read.
- UI and NSApplication glue are not testable without XCTest/a display;
  keep that layer thin (the two files in `studious-mac/`).

Manual verification: `make run-mac` with the real backend running;
edit a status in the Mac app → confirm it in the web UI, run an
enrichment in the web UI → confirm the Mac app list updates within the
poll interval.

## Docs & build plumbing

- `Makefile`: `run-mac` (`STUDIOUS_DATA_DIR=$(CURDIR)/backend/data
  swift run studious-mac`); `test-apple` unchanged.
- `apple/README.md`: new "Studious for macOS" section (what it is, how
  to run, bridge vs standalone).
- Root `README.md`: mention the Mac app alongside the iOS companion.
- `docs/roadmap.md`: flesh out the Phase 5 "Native macOS app" item.
- `docs/plan.md`: update the Platform Strategy note.

## Explicitly out of scope (this iteration)

- **Harvest workflow** (documents, transcription, region editing) — the
  web app remains the harvest/curation surface; the Mac app is the
  study/browse/bridge surface. Revisit after the workflow stabilizes
  (per `docs/plan.md` platform strategy).
- **CloudKit from inside the Mac app** — needs a signed .app bundle;
  see below.
- **A proper .app bundle** — Dock icon, Info.plist, Sparkle-style
  updates. The plain executable is the CLT-compatible way to run it.

## Later, on a machine with Xcode + a developer team

- Add a macOS app target to `apple/project.yml` (XcodeGen) sharing the
  `Studious/` shell sources, producing a signed bundle with the iCloud
  entitlement.
- Flip `syncSupported` on when the entitlement is present, letting the
  Mac app replace the `studious-sync sync` CLI as the always-running
  CloudKit agent (solves the CLI-codesigning caveat documented in
  `apple/README.md`).
- Menu-bar extra for quick review counts / sync status.
