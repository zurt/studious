import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Preferences, TtsStatus } from "../src/api";
import { catchUpSpeech } from "../src/api";
import {
  canHaveClips,
  groupSpeakers,
  pendingLine,
  playFailure,
  speakerOptionsHtml,
  ttsSectionHtml,
  ttsStatusLine,
  wireTts,
} from "../src/modules/tts-settings";

const speakers = [
  { id: 2, character: "四国めたん", style: "ノーマル", label: "四国めたん — ノーマル" },
  { id: 0, character: "四国めたん", style: "あまあま", label: "四国めたん — あまあま" },
  { id: 3, character: "ずんだもん", style: "ノーマル", label: "ずんだもん — ノーマル" },
];

describe("tts settings helpers", () => {
  it("groups styles under their character in engine order", () => {
    const g = groupSpeakers(speakers);
    expect(g.map((x) => x.character)).toEqual(["四国めたん", "ずんだもん"]);
    expect(g[0].styles.map((s) => s.id)).toEqual([2, 0]);
  });

  it("renders grouped options with the chosen speaker selected", () => {
    const html = speakerOptionsHtml(speakers, 3);
    expect(html).toContain('<optgroup label="四国めたん">');
    expect(html).toContain('<option value="3" selected>ずんだもん — ノーマル</option>');
    expect(html).not.toContain('value="2" selected');
    expect(speakerOptionsHtml(speakers, null)).toContain('<option value="" selected>Choose a speaker…</option>');
  });

  it("escapes labels", () => {
    const html = speakerOptionsHtml([{ id: 1, character: "<b>", style: "x", label: "<b> — x" }], null);
    expect(html).not.toContain("<b>");
  });

  it("status line", () => {
    expect(ttsStatusLine({ available: true, engine: "say", voice: "Kyoko", reason: "" })).toBe("Ready: Kyoko.");
    expect(ttsStatusLine({ available: false, engine: "voicevox", voice: "", reason: "not reachable" })).toBe(
      "not reachable",
    );
    expect(ttsStatusLine({ available: false, engine: "say", voice: "", reason: "" })).toContain("say");
    expect(ttsStatusLine({ available: true, engine: "say", voice: "Kyoko", reason: "None installed; using auto." })).toBe(
      "Ready: Kyoko. None installed; using auto.",
    );
  });

  it("pending line", () => {
    expect(pendingLine(0)).toBe("");
    expect(pendingLine(1)).toBe("1 word waiting for audio");
    expect(pendingLine(12)).toBe("12 words waiting for audio");
  });

  it("Play buttons show whenever the engine could have clips", () => {
    expect(canHaveClips({ available: true, engine: "say" })).toBe(true);
    expect(canHaveClips({ available: false, engine: "say_remote" })).toBe(true);
    expect(canHaveClips({ available: false, engine: "voicevox" })).toBe(true);
    expect(canHaveClips({ available: false, engine: "say" })).toBe(false);
    expect(canHaveClips({ available: false, engine: "" })).toBe(false);
  });

  it("a 503 from Play is shown inline, other failures as a toast", () => {
    expect(playFailure(503, "The Mac speech helper is not reachable")).toEqual({
      inline: true,
      message: "The Mac speech helper is not reachable",
    });
    expect(playFailure(404, "no sentence").inline).toBe(false);
    expect(playFailure(0, "network").inline).toBe(false);
  });
});

const prefs = (engine: Preferences["tts_engine"]): Preferences =>
  ({
    tts_engine: engine,
    tts_voice: "auto",
    tts_url: "http://127.0.0.1:50021",
    tts_default_url: "http://127.0.0.1:50021",
    tts_speaker: null,
    tts_engine_override: null,
  }) as unknown as Preferences;

const status = (over: Partial<TtsStatus> = {}): TtsStatus => ({
  available: false,
  engine: "say_remote",
  voice: "",
  url: "",
  speaker: null,
  reason: "The Mac speech helper is not reachable at http://mac:8766.",
  voices: ["Kyoko (Enhanced)"],
  setting: "auto",
  installed: [],
  pending: 3,
  helper_url: "http://mac:8766",
  ...over,
});

function jsonResponse(body: unknown, statusCode = 200): Response {
  return new Response(JSON.stringify(body), { status: statusCode, headers: { "Content-Type": "application/json" } });
}

describe("speech section", () => {
  it("offers the helper engine and shows the same voice fields for it as for say", () => {
    const html = ttsSectionHtml(prefs("say_remote"));
    expect(html).toContain('<option value="say_remote" selected>Mac voice through the helper');
    expect(html).not.toContain("<option value=\"say\" selected>");
    expect(html).toContain('id="settings-tts-say-fields" >');
    expect(html).toContain('id="settings-tts-engine-fields" hidden>');
    expect(html).toContain('id="settings-tts-helper-fields" >');
    expect(html).toContain("STUDIOUS_SAY_HELPER_URL");
    expect(html).not.toContain("only this Mac");
  });

  it("hides the helper and voicevox fields for the plain Mac voice", () => {
    const html = ttsSectionHtml(prefs("say"));
    expect(html).toContain('id="settings-tts-helper-fields" hidden>');
    expect(html).toContain('id="settings-tts-engine-fields" hidden>');
  });

  it("hides the say fields for VOICEVOX", () => {
    expect(ttsSectionHtml(prefs("voicevox"))).toContain('id="settings-tts-say-fields" hidden>');
  });
});

describe("speech section wiring", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const mount = (engine: Preferences["tts_engine"]) => {
    const host = document.createElement("div");
    host.innerHTML = ttsSectionHtml(prefs(engine));
    document.body.append(host);
    return host;
  };
  const tick = () => new Promise((r) => setTimeout(r, 0));

  it("shows the waiting clips and the helper URL, and Generate now calls catch-up", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/tts/status") return jsonResponse(status());
      if (url === "/api/tts/catch-up") return jsonResponse({ pending: 3, available: false, reason: "not reachable" });
      return jsonResponse({}, 404);
    });
    const host = mount("say_remote");
    wireTts(host, prefs("say_remote"));
    await tick();
    expect(host.querySelector("#settings-tts-pending")!.textContent).toBe("3 words waiting for audio");
    expect(host.querySelector<HTMLElement>("#settings-tts-pending-row")!.hidden).toBe(false);
    expect(host.querySelector("#settings-tts-helper-url")!.textContent).toBe("http://mac:8766");

    host.querySelector<HTMLButtonElement>("#settings-tts-catch-up")!.click();
    await tick();
    const call = fetchMock.mock.calls.find((c) => c[0] === "/api/tts/catch-up")!;
    expect(JSON.parse(call[1].body)).toEqual({ all: false });
    expect(host.querySelector("#settings-tts-status")!.textContent).toBe("not reachable");
  });

  it("hides the waiting row when nothing waits", async () => {
    fetchMock.mockResolvedValue(jsonResponse(status({ pending: 0, available: true, reason: "" })));
    const host = mount("say_remote");
    wireTts(host, prefs("say_remote"));
    await tick();
    expect(host.querySelector<HTMLElement>("#settings-tts-pending-row")!.hidden).toBe(true);
  });

  it("changing the engine toggles the field groups", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/preferences") return jsonResponse(prefs("say_remote"));
      return jsonResponse(status());
    });
    const host = mount("say");
    wireTts(host, prefs("say"));
    const sel = host.querySelector<HTMLSelectElement>("#settings-tts-engine")!;
    sel.value = "say_remote";
    sel.dispatchEvent(new Event("change"));
    expect(host.querySelector<HTMLElement>("#settings-tts-helper-fields")!.hidden).toBe(false);
    expect(host.querySelector<HTMLElement>("#settings-tts-say-fields")!.hidden).toBe(false);
    expect(host.querySelector<HTMLElement>("#settings-tts-engine-fields")!.hidden).toBe(true);
  });
});

describe("catchUpSpeech", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts the all flag", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ pending: 5, available: true, reason: "" }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await catchUpSpeech(true)).toEqual({ pending: 5, available: true, reason: "" });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/tts/catch-up");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ all: true });
  });

  it("throws the server's message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "nope" }, 500)));
    await expect(catchUpSpeech()).rejects.toThrow("nope");
  });
});
