import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { showToast, toastError, toastInfo } from "../src/modules/toast";

describe("toast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = "";
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the message as text in a container on body", () => {
    showToast("Upload failed: 500");
    const container = document.querySelector(".toast-container")!;
    expect(container).not.toBeNull();
    expect(container.parentElement).toBe(document.body);
    expect(container.querySelector(".toast")!.textContent).toBe("Upload failed: 500");
  });

  it("escapes markup by using textContent", () => {
    showToast("<img src=x onerror=alert(1)>");
    const toast = document.querySelector(".toast")!;
    expect(toast.querySelector("img")).toBeNull();
    expect(toast.textContent).toBe("<img src=x onerror=alert(1)>");
  });

  it("toastError sets error class and alert role", () => {
    const el = toastError("boom");
    expect(el.classList.contains("toast-error")).toBe(true);
    expect(el.getAttribute("role")).toBe("alert");
  });

  it("toastInfo sets info class and status role", () => {
    const el = toastInfo("heads up");
    expect(el.classList.contains("toast-info")).toBe(true);
    expect(el.getAttribute("role")).toBe("status");
  });

  it("stacks multiple toasts in one container", () => {
    showToast("one");
    showToast("two");
    expect(document.querySelectorAll(".toast-container").length).toBe(1);
    expect(document.querySelectorAll(".toast").length).toBe(2);
  });

  it("auto-dismisses after the duration and removes the empty container", () => {
    showToast("bye", "error", 1000);
    vi.advanceTimersByTime(999);
    expect(document.querySelector(".toast")).not.toBeNull();
    vi.advanceTimersByTime(1 + 300); // duration + leave animation fallback
    expect(document.querySelector(".toast")).toBeNull();
    expect(document.querySelector(".toast-container")).toBeNull();
  });

  it("dismisses on click", () => {
    const el = showToast("click me");
    el.click();
    expect(el.classList.contains("toast-leaving")).toBe(true);
    vi.advanceTimersByTime(300);
    expect(document.querySelector(".toast")).toBeNull();
  });

  it("a second dismiss (click after timeout) is a no-op", () => {
    const el = showToast("once", "info", 1000);
    vi.advanceTimersByTime(1000 + 300);
    expect(() => el.click()).not.toThrow();
    expect(document.querySelector(".toast")).toBeNull();
  });

  it("keeps the container while other toasts are still visible", () => {
    showToast("short", "error", 1000);
    showToast("long", "error", 10000);
    vi.advanceTimersByTime(1000 + 300);
    expect(document.querySelectorAll(".toast").length).toBe(1);
    expect(document.querySelector(".toast-container")).not.toBeNull();
  });
});
