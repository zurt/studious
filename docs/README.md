# Docs index

## Current — keep these up to date

| Doc | What it is |
|---|---|
| [next-steps.md](next-steps.md) | Handoff: what is decided, what is open, where the next sessions start |
| [project-description.md](project-description.md) | What Studious is and the tech stack |
| [plan.md](plan.md) | Architecture and data model |
| [roadmap.md](roadmap.md) | Phase-by-phase status; what is shipped, beta, and open |
| [hosting.md](hosting.md) | The single-container image, how to build and run it, the settings, what is decided and what is not done |
| [troubleshooting.md](troubleshooting.md) | Failure modes by symptom, and where logs/state live |
| [supply-chain-plan.md](supply-chain-plan.md) | Dependency cooldown, audits, Dependabot policy |
| [study-shakedown.md](study-shakedown.md) | Walkthrough for exercising the study features with real use |

## `design/` — designs for shipped features

Still the reference for *why* each feature works the way it does, and
cited from code comments. Update one only when the design itself changes.

| Doc | Feature | Status |
|---|---|---|
| [sentence-breakdowns-plan.md](design/sentence-breakdowns-plan.md) | Sentence breakdowns (Phase 2) | Shipped |
| [breakdown-vocab-links-plan.md](design/breakdown-vocab-links-plan.md) | Inline vocab/grammar links (2.1) | Shipped |
| [exercise-references-plan.md](design/exercise-references-plan.md) | Exercises citing readings (2.5) | Beta |
| [vocab-store-plan.md](design/vocab-store-plan.md) | Central vocab/grammar store, enrichment, SRS (Phase 3) | Shipped |
| [bulk-operations-plan.md](design/bulk-operations-plan.md) | "Prepare chapter" | Beta |
| [cloudkit-sync-plan.md](design/cloudkit-sync-plan.md) | Store sync protocol for the Apple apps | Built, not run on a device |
| [ios-app-plan.md](design/ios-app-plan.md) | iOS/iPadOS companion | Built, not run on a device |
| [mac-app-plan.md](design/mac-app-plan.md) | Native Mac app | Built; unsigned SwiftPM executable |

## `archive/` — dated, completed work

Historical record. Not maintained.

| Doc | What it was |
|---|---|
| [audit-2026-07-mobile-spike.md](archive/audit-2026-07-mobile-spike.md) | July 2026 codebase audit. Fixes landed; its **"Deferred findings"** (auth, upload limits, SSE reconnect) are still open |
| [improvement-recommendations.md](archive/improvement-recommendations.md) | June 2026 code review |
| [logging-improvements.md](archive/logging-improvements.md) | Phase 1.6 logging plan |
| [test-coverage-plan.md](archive/test-coverage-plan.md) | Phase 1.7 test plan |
| [vocabulary-list-guide.md](archive/vocabulary-list-guide.md) | Vocab list styling notes |
