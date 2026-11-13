import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { initMockIndicator, isMockBackend } from "../src/modules/mock-indicator";
import type { ProvidersResponse } from "../src/api";

function providers(vlm: ProvidersResponse["vlm"]): ProvidersResponse {
  return { ocr: [], vlm, defaults: { ocr: "tesseract", vlm: "anthropic", vlm_model: "m", vlm_prompt: "" } };
}

function stubFetch(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok, status: ok ? 200 : 500, json: async () => body, text: async () => "" }) as Response),
  );
}

describe("mock indicator", () => {
  let pill: HTMLElement;

  beforeEach(() => {
    document.body.innerHTML = '<span id="p" hidden>Mock VLM · seed data</span>';
    pill = document.getElementById("p")!;
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("detects the mock provider from /api/providers", () => {
    expect(isMockBackend(providers([{ name: "anthropic", kind: "vlm", mock: true }]))).toBe(true);
    expect(isMockBackend(providers([{ name: "anthropic", kind: "vlm" }]))).toBe(false);
    expect(isMockBackend(providers([]))).toBe(false);
  });

  it("reveals the pill when the backend runs the mock", async () => {
    stubFetch(providers([{ name: "anthropic", kind: "vlm", mock: true }]));
    await initMockIndicator(pill);
    expect(pill.hidden).toBe(false);
  });

  it("keeps the pill hidden for the real provider", async () => {
    stubFetch(providers([{ name: "anthropic", kind: "vlm" }]));
    await initMockIndicator(pill);
    expect(pill.hidden).toBe(true);
  });

  it("keeps the pill hidden when the lookup fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    await initMockIndicator(pill);
    expect(pill.hidden).toBe(true);
  });
});
