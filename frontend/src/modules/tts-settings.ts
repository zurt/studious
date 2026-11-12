import { type Preferences, type TtsSpeaker, getTtsSpeakers, getTtsStatus, testTtsVoice, updatePreferences } from "../api";
import { error as logError } from "../logger";
import { escapeHtml } from "./html";

/** Speakers grouped by character, in the order the engine lists them. */
export function groupSpeakers(speakers: TtsSpeaker[]): { character: string; styles: TtsSpeaker[] }[] {
  const groups: { character: string; styles: TtsSpeaker[] }[] = [];
  for (const s of speakers) {
    const last = groups.find((g) => g.character === s.character);
    if (last) last.styles.push(s);
    else groups.push({ character: s.character, styles: [s] });
  }
  return groups;
}

/** <option>s for the speaker picker: grouped "Character — Style", the chosen one selected. */
export function speakerOptionsHtml(speakers: TtsSpeaker[], selected: number | null): string {
  const none = `<option value=""${selected === null ? " selected" : ""}>Choose a speaker…</option>`;
  return (
    none +
    groupSpeakers(speakers)
      .map(
        (g) =>
          `<optgroup label="${escapeHtml(g.character)}">` +
          g.styles
            .map(
              (s) =>
                `<option value="${s.id}"${s.id === selected ? " selected" : ""}>${escapeHtml(s.label)}</option>`,
            )
            .join("") +
          `</optgroup>`,
      )
      .join("")
  );
}

/** One-line status under the Speech settings. */
export function ttsStatusLine(s: { available: boolean; engine: string; voice: string; reason: string }): string {
  if (s.available) return `Ready: ${s.voice}.`;
  return s.reason || `The ${s.engine} voice is not available.`;
}

export function ttsSectionHtml(prefs: Preferences): string {
  const voicevox = prefs.tts_engine === "voicevox";
  return `
    <section class="settings-section">
      <h3>Speech</h3>
      <p class="muted small">Voice for the audio on Anki cards and the Play buttons. The Mac voice needs nothing installed. VOICEVOX or AivisSpeech must be running (on this Mac) when you send words to Anki or play a clip. Voices carry their own terms of use.</p>
      <dl class="settings-dl">
        <dt>Engine</dt><dd>
          <select id="settings-tts-engine" class="settings-select">
            <option value="say"${voicevox ? "" : " selected"}>Mac voice (say)</option>
            <option value="voicevox"${voicevox ? " selected" : ""}>VOICEVOX / AivisSpeech</option>
          </select>
        </dd>
        <div id="settings-tts-engine-fields" ${voicevox ? "" : "hidden"}>
          <dt>Engine URL</dt><dd>
            <input id="settings-tts-url" class="settings-input" type="text" maxlength="200"
              placeholder="${escapeHtml(prefs.tts_default_url)}" value="${escapeHtml(prefs.tts_url)}" />
            <span class="muted small">VOICEVOX: http://127.0.0.1:50021 · AivisSpeech: http://127.0.0.1:10101</span>
          </dd>
          <dt>Speaker</dt><dd>
            <select id="settings-tts-speaker" class="settings-select"><option value="">Loading…</option></select>
          </dd>
        </div>
        <dt>Test</dt><dd>
          <button id="settings-tts-test">Test voice</button>
          <span id="settings-tts-status" class="muted small" style="margin-left:0.5rem;"></span>
        </dd>
      </dl>
    </section>`;
}

export function wireTts(host: HTMLElement, prefs: Preferences): void {
  const status = host.querySelector<HTMLElement>("#settings-tts-status");
  const engine = host.querySelector<HTMLSelectElement>("#settings-tts-engine");
  const url = host.querySelector<HTMLInputElement>("#settings-tts-url");
  const speaker = host.querySelector<HTMLSelectElement>("#settings-tts-speaker");
  const fields = host.querySelector<HTMLElement>("#settings-tts-engine-fields");
  const test = host.querySelector<HTMLButtonElement>("#settings-tts-test");
  if (!engine || !status) return;
  let chosen: number | null = prefs.tts_speaker;

  const say = (msg: string) => {
    status.textContent = msg;
  };
  const save = async (patch: Parameters<typeof updatePreferences>[0]) => {
    say("Saving…");
    try {
      const next = await updatePreferences(patch);
      chosen = next.tts_speaker;
      say("Saved.");
      return true;
    } catch (e: any) {
      logError("SettingsModal", "tts_save_failed", { error: e?.message ?? String(e) });
      say(`Failed: ${e?.message ?? String(e)}`);
      return false;
    }
  };
  const loadSpeakers = async () => {
    if (!speaker || engine.value !== "voicevox") return;
    speaker.innerHTML = `<option value="">Loading…</option>`;
    try {
      const d = await getTtsSpeakers();
      speaker.innerHTML = speakerOptionsHtml(d.speakers, chosen);
    } catch (e: any) {
      speaker.innerHTML = `<option value="">No speakers listed</option>`;
      say(String(e?.message ?? e));
    }
  };

  engine.addEventListener("change", async () => {
    if (fields) fields.hidden = engine.value !== "voicevox";
    if (await save({ tts_engine: engine.value })) await loadSpeakers();
  });
  url?.addEventListener("change", async () => {
    if (await save({ tts_url: url.value })) await loadSpeakers();
  });
  speaker?.addEventListener("change", async () => {
    await save({ tts_speaker: speaker.value === "" ? "" : Number(speaker.value) });
  });
  test?.addEventListener("click", async () => {
    test.disabled = true;
    say("Playing…");
    try {
      const blob = await testTtsVoice();
      const objectUrl = URL.createObjectURL(blob);
      const audio = new Audio(objectUrl);
      audio.addEventListener("ended", () => URL.revokeObjectURL(objectUrl));
      await audio.play();
      say("");
    } catch (e: any) {
      say(String(e?.message ?? e));
      try {
        say(ttsStatusLine(await getTtsStatus()));
      } catch {
        // keep the error above
      }
    } finally {
      test.disabled = false;
    }
  });
  void loadSpeakers();
}
