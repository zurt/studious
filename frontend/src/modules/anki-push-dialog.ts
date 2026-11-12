import type { AnkiPushPreview, AnkiPushResult, ExamplesResponse } from "../api";

/** Ids per generate request; the server batches at the same size. */
export const GENERATE_CHUNK = 20;

/** Lines of the confirmation dialog body, in order. Plain text. */
export function pushDialogLines(p: AnkiPushPreview): string[] {
  const n = p.counts.will_add;
  const lines = [
    `${n} ${n === 1 ? "word" : "words"} will be added to the "${p.deck}" deck (${p.note_type}).`,
  ];
  if (p.will_create_deck) lines.push(`This deck will be created.`);
  if (n > 0) {
    const first = p.items.filter((i) => i.can_add).slice(0, 10).map((i) => i.headword);
    lines.push(`First ${first.length}: ${first.join("、")}${n > first.length ? " …" : ""}`);
  }
  if (p.counts.skipped > 0) lines.push(`${p.counts.skipped} skipped, already in Anki.`);
  if (n > 0) {
    lines.push(
      `${p.counts.with_sentence} with an example sentence (${p.counts.with_gloss} with a translation), ${p.counts.without_sentence} without.`,
    );
  }
  if (p.counts.headword_match > 0) {
    lines.push(`${p.counts.headword_match} match an existing card by spelling only (different reading).`);
  }
  return lines;
}

/** Checkbox label for the audio option. */
export function audioLabel(voice: string, engine = "say"): string {
  return engine === "voicevox" ? `Add audio (${voice})` : `Add audio (Mac voice: ${voice})`;
}

/** Muted line shown instead of the checkbox when the voice cannot be used. */
export function audioUnavailableLine(voice: string, reason = ""): string {
  return reason ? `No audio: ${reason}` : `No audio: needs macOS with the "${voice}" voice installed (see STUDIOUS_TTS_VOICE).`;
}

export type SendChoice = { limit: number; audio: boolean };

export function sendButtonLabel(n: number): string {
  return `Send ${n} ${n === 1 ? "word" : "words"}`;
}

/** Toast text for a finished send. */
export function pushResultMessage(r: AnkiPushResult): string {
  let msg = `Sent ${r.created} ${r.created === 1 ? "word" : "words"} to Anki (${r.deck}).`;
  if (r.skipped.length) msg += ` ${r.skipped.length} skipped.`;
  if (r.failed.length) msg += ` ${r.failed.length} failed.`;
  if (r.audio?.enabled) {
    msg += ` ${r.audio.attached} audio ${r.audio.attached === 1 ? "clip" : "clips"} added`;
    msg += r.audio.failed ? `, ${r.audio.failed} failed.` : ".";
    if (r.audio.reading_corrected) {
      msg += ` ${r.audio.reading_corrected} ${r.audio.reading_corrected === 1 ? "reading" : "readings"} corrected.`;
    }
  }
  if (!r.sync_ok) msg += " The Anki sync afterwards failed; press Sync Anki.";
  return msg;
}

/** Clamp the count input to 1..max (max at least 1); NaN becomes max. */
export function clampCount(value: number, max: number): number {
  const hi = Math.max(1, max);
  if (!Number.isFinite(value)) return hi;
  return Math.min(hi, Math.max(1, Math.floor(value)));
}

export function chunkIds(ids: string[], size = GENERATE_CHUNK): string[][] {
  const out: string[][] = [];
  for (let i = 0; i < ids.length; i += size) out.push(ids.slice(i, i + size));
  return out;
}

/** "88 words need an example sentence." */
export function needsExampleLine(n: number): string {
  return `${n} ${n === 1 ? "word needs" : "words need"} an example sentence.`;
}

export function generateButtonLabel(): string {
  return "Generate";
}


export function progressText(done: number, total: number): string {
  return `Generating… ${done} of ${total}`;
}

export type GenerateTally = { generated: number; kept: number; failed: number };

export function tallyResults(res: ExamplesResponse): GenerateTally {
  const t: GenerateTally = { generated: 0, kept: 0, failed: 0 };
  for (const r of res.items) t[r.status] += 1;
  return t;
}

/** One line after a run. `remaining` is the preview's needs_example afterwards. */
export function generationSummary(
  t: GenerateTally,
  remaining: number,
  stopped: "cancelled" | "error" | null,
): string {
  let msg = `Generated ${t.generated} ${t.generated === 1 ? "sentence" : "sentences"}`;
  if (t.failed > 0) msg += `, ${t.failed} failed`;
  msg += ".";
  if (stopped === "cancelled") msg += " Stopped.";
  if (remaining > 0) msg += ` ${remaining} ${remaining === 1 ? "word stays" : "words stay"} without a sentence.`;
  return msg;
}

/** Whether the "N words have no example sentence" offer shows. */
export function offerVisible(needs: number, generating: boolean, runComplete: boolean): boolean {
  return needs > 0 && !generating && !runComplete;
}

/**
 * Modal for "Send to Anki". `load(limit)` fetches a preview; it is called
 * once up front and again whenever the count changes. `generate(ids)` stores
 * example sentences for words that have none (the dialog calls it in chunks,
 * then re-runs the preview). Resolves the count to send, or null on cancel.
 */
export function ankiPushDialog(
  initial: AnkiPushPreview,
  candidates: number,
  initialLimit: number,
  load: (limit: number) => Promise<AnkiPushPreview>,
  generate: (ids: string[]) => Promise<ExamplesResponse>,
): Promise<SendChoice | null> {
  return new Promise((resolve) => {
    let preview = initial;
    let limit = initialLimit;
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `
      <div class="modal" style="width: min(460px, 90vw)">
        <h2>Send to Anki</h2>
        <div class="anki-push-body"></div>
        <div class="anki-push-generate" hidden>
          <p class="confirm-message anki-push-needs"></p>
          <div class="row">
            <button class="primary" id="anki-push-generate"></button>
            <button id="anki-push-without">Send without</button>
          </div>
        </div>
        <div class="anki-push-progress" hidden>
          <p class="confirm-message anki-push-progress-text"></p>
          <button id="anki-push-stop">Cancel</button>
        </div>
        <p class="confirm-message anki-push-summary" hidden></p>
        <label class="row anki-push-count">Words to send
          <input type="number" min="1" step="1" style="width: 6em" />
        </label>
        <label class="anki-push-audio" hidden><input type="checkbox" checked /> <span></span></label>
        <p class="confirm-message anki-push-audio-note" hidden style="color: var(--muted)"></p>
        <p class="confirm-message anki-push-error" hidden></p>
        <div class="row">
          <div class="grow"></div>
          <button id="anki-push-cancel">Cancel</button>
          <button id="anki-push-ok"></button>
        </div>
      </div>
    `;
    const body = bg.querySelector<HTMLElement>(".anki-push-body")!;
    const input = bg.querySelector<HTMLInputElement>("input")!;
    const errorEl = bg.querySelector<HTMLElement>(".anki-push-error")!;
    const okBtn = bg.querySelector<HTMLButtonElement>("#anki-push-ok")!;
    const offerEl = bg.querySelector<HTMLElement>(".anki-push-generate")!;
    const needsEl = bg.querySelector<HTMLElement>(".anki-push-needs")!;
    const genBtn = bg.querySelector<HTMLButtonElement>("#anki-push-generate")!;
    const progressEl = bg.querySelector<HTMLElement>(".anki-push-progress")!;
    const progressTextEl = bg.querySelector<HTMLElement>(".anki-push-progress-text")!;
    const summaryEl = bg.querySelector<HTMLElement>(".anki-push-summary")!;
    const audioRow = bg.querySelector<HTMLElement>(".anki-push-audio")!;
    const audioBox = audioRow.querySelector<HTMLInputElement>("input")!;
    const audioNote = bg.querySelector<HTMLElement>(".anki-push-audio-note")!;
    const au = initial.audio;
    if (au?.enabled && au.available) {
      audioRow.hidden = false;
      audioRow.querySelector("span")!.textContent = audioLabel(au.voice, au.engine);
    } else if (au?.enabled) {
      audioNote.hidden = false;
      audioNote.textContent = audioUnavailableLine(au.voice, au.reason);
    }
    let generating = false;
    let runComplete = false; // a run finished: stop offering, even if some words failed
    let stopRequested = false;
    let closed = false;
    input.max = String(Math.max(1, candidates));
    input.value = String(limit);

    function render() {
      body.replaceChildren(
        ...pushDialogLines(preview).map((line) => {
          const p = document.createElement("p");
          p.className = "confirm-message";
          p.textContent = line;
          return p;
        }),
      );
      const needs = preview.counts.needs_example ?? 0;
      const offer = offerVisible(needs, generating, runComplete);
      offerEl.hidden = !offer;
      needsEl.textContent = needsExampleLine(needs);
      genBtn.textContent = generateButtonLabel();
      progressEl.hidden = !generating;
      okBtn.textContent = sendButtonLabel(preview.counts.will_add);
      okBtn.disabled = preview.counts.will_add === 0;
      okBtn.hidden = offer || generating;
      input.disabled = generating;
    }
    render();
    (document.fullscreenElement ?? document.body).appendChild(bg);

    let seq = 0;
    input.addEventListener("change", async () => {
      limit = clampCount(Number(input.value), candidates);
      runComplete = false;
      summaryEl.hidden = true;
      input.value = String(limit);
      const mine = ++seq;
      okBtn.disabled = true;
      errorEl.hidden = true;
      try {
        const next = await load(limit);
        if (mine !== seq) return;
        preview = next;
        render();
      } catch (e: any) {
        if (mine !== seq) return;
        errorEl.textContent = String(e?.message ?? e);
        errorEl.hidden = false;
      }
    });

    async function runGeneration() {
      const ids = [...(preview.counts.needs_example_ids ?? [])];
      const total = ids.length;
      const tally: GenerateTally = { generated: 0, kept: 0, failed: 0 };
      let stopped: "cancelled" | "error" | null = null;
      let done = 0;
      generating = true;
      stopRequested = false;
      errorEl.hidden = true;
      summaryEl.hidden = true;
      progressTextEl.textContent = progressText(0, total);
      render();
      for (const chunk of chunkIds(ids)) {
        if (stopRequested) {
          stopped = "cancelled";
          break;
        }
        try {
          const t = tallyResults(await generate(chunk));
          tally.generated += t.generated;
          tally.kept += t.kept;
          tally.failed += t.failed;
        } catch (e: any) {
          errorEl.textContent = String(e?.message ?? e);
          errorEl.hidden = false;
          stopped = "error";
          break;
        }
        done += chunk.length;
        progressTextEl.textContent = progressText(done, total);
      }
      if (!stopped && stopRequested && done < total) stopped = "cancelled";
      if (closed) return;
      try {
        preview = await load(limit);
      } catch (e: any) {
        errorEl.textContent = String(e?.message ?? e);
        errorEl.hidden = false;
      }
      generating = false;
      runComplete = stopped === null;
      summaryEl.textContent = generationSummary(tally, preview.counts.needs_example ?? 0, stopped);
      summaryEl.hidden = false;
      render();
    }

    function close(result: SendChoice | null) {
      closed = true;
      stopRequested = true;
      document.removeEventListener("keydown", onKey);
      bg.remove();
      resolve(result);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close(null);
    }
    bg.querySelector("#anki-push-cancel")!.addEventListener("click", () => close(null));
    const choice = (): SendChoice => ({ limit, audio: !audioRow.hidden && audioBox.checked });
    okBtn.addEventListener("click", () => close(choice()));
    genBtn.addEventListener("click", () => void runGeneration());
    bg.querySelector("#anki-push-without")!.addEventListener("click", () => close(choice()));
    bg.querySelector("#anki-push-stop")!.addEventListener("click", () => {
      stopRequested = true;
      progressTextEl.textContent += " (stopping after this batch)";
    });
    bg.addEventListener("click", (e) => {
      if (e.target === bg) close(null);
    });
    document.addEventListener("keydown", onKey);
    setTimeout(() => input.focus(), 0);
  });
}
