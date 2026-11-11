import { describe, it, expect, vi } from "vitest";
import { on, emit, STORE_STATUS_CHANGED, type StoreStatusChange } from "../src/modules/events";

describe("event bus", () => {
  it("delivers payloads to subscribers", () => {
    const seen: StoreStatusChange[] = [];
    const off = on<StoreStatusChange>(STORE_STATUS_CHANGED, (p) => seen.push(p));
    emit<StoreStatusChange>(STORE_STATUS_CHANGED, { kind: "vocab", id: "a", status: "known" });
    expect(seen).toEqual([{ kind: "vocab", id: "a", status: "known" }]);
    off();
  });

  it("unsubscribe stops delivery", () => {
    const fn = vi.fn();
    const off = on("test-evt", fn);
    off();
    emit("test-evt", 1);
    expect(fn).not.toHaveBeenCalled();
  });

  it("a handler unsubscribing mid-emit does not skip other handlers", () => {
    const calls: string[] = [];
    const offA = on("evt", () => {
      calls.push("a");
      offA();
    });
    on("evt", () => calls.push("b"));
    emit("evt", null);
    expect(calls).toEqual(["a", "b"]);
  });

  it("events without subscribers are a no-op", () => {
    expect(() => emit("nobody-listens", { x: 1 })).not.toThrow();
  });
});
