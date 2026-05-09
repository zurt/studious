import { describe, it, expect, vi, beforeEach } from "vitest";
import { attachPageInput } from "../src/modules/page-input";

function makeSpan(initialText = "Page 5 / 20"): HTMLElement {
  const span = document.createElement("span");
  span.textContent = initialText;
  document.body.appendChild(span);
  return span;
}

function pressKey(input: HTMLInputElement, key: string) {
  input.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
}

describe("page-input", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("click swaps span content for a number input with min/max/value", () => {
    const span = makeSpan();
    attachPageInput(span, {
      getMin: () => 1,
      getMax: () => 20,
      getCurrent: () => 5,
      onCommit: vi.fn(),
    });

    span.click();
    const input = span.querySelector<HTMLInputElement>("input")!;
    expect(input).not.toBeNull();
    expect(input.type).toBe("number");
    expect(input.min).toBe("1");
    expect(input.max).toBe("20");
    expect(input.value).toBe("5");
  });

  it("Enter commits the clamped value (above max)", () => {
    const span = makeSpan();
    const onCommit = vi.fn();
    attachPageInput(span, {
      getMin: () => 1,
      getMax: () => 20,
      getCurrent: () => 5,
      onCommit,
    });
    span.click();
    const input = span.querySelector<HTMLInputElement>("input")!;
    input.value = "999";
    pressKey(input, "Enter");
    expect(onCommit).toHaveBeenCalledWith(20);
    expect(span.textContent).toBe("Page 5 / 20");
  });

  it("Enter commits the clamped value (below min)", () => {
    const span = makeSpan();
    const onCommit = vi.fn();
    attachPageInput(span, {
      getMin: () => 3,
      getMax: () => 10,
      getCurrent: () => 5,
      onCommit,
    });
    span.click();
    const input = span.querySelector<HTMLInputElement>("input")!;
    input.value = "1";
    pressKey(input, "Enter");
    expect(onCommit).toHaveBeenCalledWith(3);
  });

  it("Enter on the same value does not call onCommit", () => {
    const span = makeSpan();
    const onCommit = vi.fn();
    attachPageInput(span, {
      getMin: () => 1,
      getMax: () => 20,
      getCurrent: () => 5,
      onCommit,
    });
    span.click();
    const input = span.querySelector<HTMLInputElement>("input")!;
    pressKey(input, "Enter");
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("Esc restores prior text and does not commit", () => {
    const span = makeSpan("Page 5 / 20");
    const onCommit = vi.fn();
    attachPageInput(span, {
      getMin: () => 1,
      getMax: () => 20,
      getCurrent: () => 5,
      onCommit,
    });
    span.click();
    const input = span.querySelector<HTMLInputElement>("input")!;
    input.value = "10";
    pressKey(input, "Escape");
    expect(onCommit).not.toHaveBeenCalled();
    expect(span.textContent).toBe("Page 5 / 20");
  });

  it("blur restores prior text and does not commit", () => {
    const span = makeSpan("Page 5 / 20");
    const onCommit = vi.fn();
    attachPageInput(span, {
      getMin: () => 1,
      getMax: () => 20,
      getCurrent: () => 5,
      onCommit,
    });
    span.click();
    const input = span.querySelector<HTMLInputElement>("input")!;
    input.dispatchEvent(new Event("blur"));
    expect(onCommit).not.toHaveBeenCalled();
    expect(span.textContent).toBe("Page 5 / 20");
  });

  it("Enter with non-finite input restores without committing", () => {
    const span = makeSpan("Page 5 / 20");
    const onCommit = vi.fn();
    attachPageInput(span, {
      getMin: () => 1,
      getMax: () => 20,
      getCurrent: () => 5,
      onCommit,
    });
    span.click();
    const input = span.querySelector<HTMLInputElement>("input")!;
    input.value = "";
    pressKey(input, "Enter");
    expect(onCommit).not.toHaveBeenCalled();
    expect(span.textContent).toBe("Page 5 / 20");
  });

  it("a second click while editing does not nest another input", () => {
    const span = makeSpan();
    attachPageInput(span, {
      getMin: () => 1,
      getMax: () => 20,
      getCurrent: () => 5,
      onCommit: vi.fn(),
    });
    span.click();
    span.click();
    expect(span.querySelectorAll("input").length).toBe(1);
  });
});
