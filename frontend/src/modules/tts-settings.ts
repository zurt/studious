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
  if (s.available) return s.reason ? `Ready: ${s.voice}. ${s.reason}` : `Ready: ${s.voice}.`;
  return s.reason || `The ${s.engine} voice is not available.`;
}

export function ttsSectionHtml(prefs: Preferences): string {
  const voicevox = prefs.tts_engine === "voicevox";
  return `
    <section class="settings-section">
      <h3>Speech</h3>
      <p class="muted small">Voice for the audio on Anki cards and the Play buttons. The Mac voice needs nothing installed. The Mac voices rotate per card. VOICEVOX or AivisSpeech is an option that has not yet been tested against a real engine; it must be running (on this Mac) when you send words to Anki or play a clip, and its voices carry their own terms of use.</p>
      <dl class="settings-dl">
        <dt>Engine</dt><dd>
          <select id="settings-tts-engine" class="settings-select">
            <option value="say"${voicevox ? "" : " selected"}>Mac voice (say)</option>
            <option value="voicevox"${voicevox ? " selected" : ""}>VOICEVOX / AivisSpeech (not yet tested against a real engine)</option>
          </select>
        </dd>
        <div id="settings-tts-say-fields" ${voicevox ? "hidden" : ""}>
          <dt>Voices in use</dt><dd>
            <span id="settings-tts-voices" class="muted small">…</span>
          </dd>
          <dt>Voice list</dt><dd>
            <input id="settings-tts-voice" class="settings-input" type="text" maxlength="200"
              placeholder="auto" value="${escapeHtml(prefs.tts_voice === "auto" ? "" : prefs.tts_voice)}" />
            <span class="muted small">auto = every installed Enhanced or Premium Japanese voice (else Kyoko). Or a comma-separated list of voice names.</span>
          </dd>
        </div>
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
  const sayFields = host.querySelector<HTMLElement>("#settings-tts-say-fields");
  const voiceInput = host.querySelector<HTMLInputElement>("#settings-tts-voice");
  const voicesEl = host.querySelector<HTMLElement>("#settings-tts-voices");
  let pool: string[] = [];
  let nextVoice = 0;
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

  const loadVoices = async () => {
    try {
      const st = await getTtsStatus();
      pool = st.engine === "say" ? st.voices : [];
      nextVoice = 0;
      if (voicesEl) voicesEl.textContent = st.engine === "say" ? ttsStatusLine(st) : "";
    } catch {
      if (voicesEl) voicesEl.textContent = "";
    }
  };
  voiceInput?.addEventListener("change", async () => {
    if (await save({ tts_voice: voiceInput.value })) await loadVoices();
  });

  engine.addEventListener("change", async () => {
    if (fields) fields.hidden = engine.value !== "voicevox";
    if (sayFields) sayFields.hidden = engine.value === "voicevox";
    if (await save({ tts_engine: engine.value })) {
      await loadSpeakers();
      await loadVoices();
    }
  });
  url?.addEventListener("change", async () => {
    if (await save({ tts_url: url.value })) await loadSpeakers();
  });
  speaker?.addEventListener("change", async () => {
    await save({ tts_speaker: speaker.value === "" ? "" : Number(speaker.value) });
  });
  test?.addEventListener("click", async () => {
    test.disabled = true;
    // The Mac engine: each press plays the next voice in the pool.
    const voice = engine.value === "say" && pool.length ? pool[nextVoice % pool.length] : undefined;
    if (voice) nextVoice += 1;
    say(voice ? `Playing ${voice}…` : "Playing…");
    try {
      const blob = await testTtsVoice(voice);
      const objectUrl = URL.createObjectURL(blob);
      const audio = new Audio(objectUrl);
      audio.addEventListener("ended", () => URL.revokeObjectURL(objectUrl));
      await audio.play();
      say(voice ? `Played ${voice}.` : "");
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
  void loadVoices();
}
