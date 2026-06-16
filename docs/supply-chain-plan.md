# Supply Chain Security Plan

The project already enforces a 7-day package cooldown (`backend/uv.toml`,
`frontend/.npmrc`). This plan layers additional hardening on top.

## Priority 1 (ship now)

### 1. Frozen installs in CI

- Backend: install with `uv sync --frozen` so `uv.lock` is the source of truth.
- Frontend: install with `npm ci` so `package-lock.json` is the source of truth.
- Both lockfiles are already tracked in git.
- **Why:** prevents version drift between local dev and CI, and stops a
  compromised registry from silently substituting a different resolution.

### 2. Automated audits on every PR

- Run `make audit` (= `npm audit` + `pip-audit`) in CI on every push and PR.
- Fail the build on **high** or **critical** advisories. Lower severities
  surface in the log but don't block.
- Add `pip-audit` to backend dev dependencies so `uv run pip-audit` works
  without an extra install step.
- **Why:** the existing `make audit` target is opt-in. Wiring it into CI
  makes vulnerability detection automatic.

### 3. Dependabot with cooldown

- Add `.github/dependabot.yml` covering `pip`, `npm`, and `github-actions`
  ecosystems.
- Use Dependabot's [`cooldown`](https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file#cooldown)
  setting to mirror the 7-day floor enforced by uv/npm.
- Group non-security minor + patch updates to keep PR noise low.
- **Why:** automated PRs for known-vulnerable deps, while respecting the
  same 7-day cooldown that protects local installs.

## Priority 2 (second pass)

Bundled for a follow-up phase:

- **Pin GitHub Actions by SHA.** Tags are mutable; SHAs are not. Apply
  to every third-party action used in CI workflows. ✅ Done 2026-06-12 —
  all uses in `ci.yml` are pinned to full commit SHAs with version
  comments; Dependabot's `github-actions` ecosystem keeps the pins
  updated.
- **Secret scanning + push protection.** Enable in GitHub repo settings
  (no code change required, but worth documenting).
- **Prune unused dependencies.** Run `depcheck` (npm) and `deptry`
  (Python) periodically; remove anything unused.
- **SBOM generation.** `npm sbom` and `uv export --format requirements-txt`
  on release tags, attached as build artifacts.
- **API key hygiene.** Confirm `.env` stays gitignored, document key
  rotation cadence, and scope the Anthropic key to the minimum needed.
- **Sandbox PDF rendering.** PDFs are untrusted input. Confirm PyMuPDF
  runs without network access in production and consider resource
  limits (memory/time) on the rendering job.

## Out of scope

- Code signing / artifact provenance (sigstore, SLSA) — overkill for a
  personal project.
- Runtime SCA (Snyk, Socket) — `pip-audit` + `npm audit` cover the same
  ground for free.
