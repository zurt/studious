import type { AnkiPushPreview, AnkiPushResult } from "../api";

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

export function sendButtonLabel(n: number): string {
  return `Send ${n} ${n === 1 ? "word" : "words"}`;
}

/** Toast text for a finished send. */
export function pushResultMessage(r: AnkiPushResult): string {
  let msg = `Sent ${r.created} ${r.created === 1 ? "word" : "words"} to Anki (${r.deck}).`;
  if (r.skipped.length) msg += ` ${r.skipped.length} skipped.`;
  if (r.failed.length) msg += ` ${r.failed.length} failed.`;
  if (!r.sync_ok) msg += " The Anki sync afterwards failed; press Sync Anki.";
  return msg;
}

/** Clamp the count input to 1..max (max at least 1); NaN becomes max. */
export function clampCount(value: number, max: number): number {
  const hi = Math.max(1, max);
  if (!Number.isFinite(value)) return hi;
  return Math.min(hi, Math.max(1, Math.floor(value)));
}

/**
 * Modal for "Send to Anki". `load(limit)` fetches a preview; it is called
 * once up front and again whenever the count changes. Resolves the count to
 * send, or null on cancel.
 */
export function ankiPushDialog(
  initial: AnkiPushPreview,
  candidates: number,
  initialLimit: number,
  load: (limit: number) => Promise<AnkiPushPreview>,
): Promise<number | null> {
  return new Promise((resolve) => {
    let preview = initial;
    let limit = initialLimit;
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `
      <div class="modal" style="width: min(460px, 90vw)">
        <h2>Send to Anki</h2>
        <div class="anki-push-body"></div>
        <label class="row anki-push-count">Words to send
          <input type="number" min="1" step="1" style="width: 6em" />
        </label>
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
      okBtn.textContent = sendButtonLabel(preview.counts.will_add);
      okBtn.disabled = preview.counts.will_add === 0;
    }
    render();
    (document.fullscreenElement ?? document.body).appendChild(bg);

    let seq = 0;
    input.addEventListener("change", async () => {
      limit = clampCount(Number(input.value), candidates);
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

    function close(result: number | null) {
      document.removeEventListener("keydown", onKey);
      bg.remove();
      resolve(result);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close(null);
    }
    bg.querySelector("#anki-push-cancel")!.addEventListener("click", () => close(null));
    okBtn.addEventListener("click", () => close(limit));
    bg.addEventListener("click", (e) => {
      if (e.target === bg) close(null);
    });
    document.addEventListener("keydown", onKey);
    setTimeout(() => input.focus(), 0);
  });
}
