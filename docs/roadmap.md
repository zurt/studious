# Studious - Roadmap

## Phase 1: Chapters + Regions + Targeted Transcription (Current)

- [x] PDF and image upload with page rendering
- [x] Anthropic Claude VLM integration with custom prompt
- [x] Side-by-side page image + transcription viewer
- [x] Async job queue with SSE progress streaming
- [x] Structured logging with correlation IDs
- [x] Supply chain security (package manager cooldown)
- [x] Chapter management (create, list, update, delete)
- [x] Region drawing on page images (canvas overlay with bbox)
- [x] Region tagging (reading_passage, vocab_list, grammar_points, exercises, etc.)
- [x] Region-level VLM transcription (crop to bbox, send to Claude)
- [x] Vanilla TypeScript frontend (no framework)
- [x] Map-like zoom/pan page viewer (pinch zoom, two-finger scroll, Cmd+/-, Cmd+0, fit button)
- [x] Full screen mode
- [x] Chapter popover panel (closed by default) with drag-to-reorder
- [x] Current chapter indicator banner in document view
- [x] Region transcription tracker widget in chapter view (pending count, batch transcribe)

## Phase 1.5: UX Safety + LLM Observability

- [ ] Confirmation dialogs for delete operations (regions, chapters, documents)
- [ ] LLM audit log (append-only JSONL with provider, model, tokens, duration, context)
- [ ] Cost tracking estimation (per-model token pricing, cost-per-request, summary API)

## Phase 2: Sentence Breakdowns

- [ ] Sentence-by-sentence breakdown (vocab, grammar, gloss) per region
- [ ] Text-only VLM calls for analysis (no image tokens, cheaper)
- [ ] Breakdown storage per-region
- [ ] Breakdown display UI (cards/accordions)

## Phase 3: Central Vocab/Grammar Store

- [ ] Global vocab store (JSONL-based, across all textbooks)
- [ ] Global grammar store (same pattern)
- [ ] Status tracking (new → reviewing → known)
- [ ] Vocab dashboard with filtering and search
- [ ] Auto-populate store from breakdowns (dedup by headword+reading)

## Phase 4: Export + Exercises

- [ ] Anki TSV export for vocab/grammar items
- [ ] Exercise-specific prompts and walkthrough UI
- [ ] Grammar dashboard

## Phase 5: Polish + Native

- [ ] Bulk operations (transcribe/breakdown all regions in a chapter)
- [ ] Region editing (resize, move, reorder)
- [ ] Native macOS/iOS/iPad apps (SwiftUI, same backend API)
- [ ] Mobile-responsive web layout
