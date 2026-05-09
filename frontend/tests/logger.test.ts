import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  generateCorrelationId,
  info,
  warn,
  error,
  startTimer,
} from "../src/logger";

describe("generateCorrelationId", () => {
  it("returns a 16-char hex string with no dashes", () => {
    const cid = generateCorrelationId();
    expect(cid).toMatch(/^[0-9a-f]{16}$/);
  });

  it("returns a fresh id each call", () => {
    const a = generateCorrelationId();
    const b = generateCorrelationId();
    expect(a).not.toBe(b);
  });
});

describe("info / warn / error", () => {
  let logSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;
  let errSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    logSpy.mockRestore();
    warnSpy.mockRestore();
    errSpy.mockRestore();
  });

  function parseEntry(spy: ReturnType<typeof vi.spyOn>) {
    const args = spy.mock.calls[0]!;
    expect(args[0]).toBe("[studious]");
    return JSON.parse(args[1] as string);
  }

  it("info routes to console.log with valid JSON and correlation id", () => {
    info("api", "hello", { correlation_id: "abc123", status: 200 });
    const entry = parseEntry(logSpy);
    expect(entry.level).toBe("info");
    expect(entry.component).toBe("api");
    expect(entry.msg).toBe("hello");
    expect(entry.correlation_id).toBe("abc123");
    expect(entry.status).toBe(200);
    expect(typeof entry.ts).toBe("string");
  });

  it("warn routes to console.warn", () => {
    warn("router", "weird");
    const entry = parseEntry(warnSpy);
    expect(entry.level).toBe("warn");
    expect(entry.correlation_id).toBeNull();
  });

  it("error routes to console.error", () => {
    error("api", "boom", { correlation_id: "x" });
    const entry = parseEntry(errSpy);
    expect(entry.level).toBe("error");
    expect(entry.correlation_id).toBe("x");
  });

  it("non-string correlation_id becomes null", () => {
    info("api", "m", { correlation_id: 42 as unknown as string });
    const entry = parseEntry(logSpy);
    expect(entry.correlation_id).toBeNull();
  });
});

describe("startTimer", () => {
  let logSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    logSpy.mockRestore();
  });

  it("records monotonic duration_ms", () => {
    const nowSpy = vi.spyOn(performance, "now");
    nowSpy.mockReturnValueOnce(1000);
    nowSpy.mockReturnValueOnce(1042.7);

    const done = startTimer("api", "GET /x", { correlation_id: "c1" });
    done({ status: 200 });

    const args = logSpy.mock.calls[0]!;
    const entry = JSON.parse(args[1] as string);
    expect(entry.duration_ms).toBe(43);
    expect(entry.correlation_id).toBe("c1");
    expect(entry.status).toBe(200);
    nowSpy.mockRestore();
  });
});
