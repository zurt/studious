import { describe, it, expect, afterEach } from "vitest";
import { isTypingTarget, pageShortcutsSuppressed } from "../src/modules/shortcuts-help";

function keyFrom(target: EventTarget): KeyboardEvent {
  const e = new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true });
  Object.defineProperty(e, "target", { value: target });
  return e;
}

describe("page shortcut suppression", () => {
  afterEach(() => { document.body.innerHTML = ""; });

  it("treats inputs, textareas, selects and contenteditable as typing targets", () => {
    for (const tag of ["input", "textarea", "select"]) {
      expect(isTypingTarget(document.createElement(tag))).toBe(true);
    }
    const editable = document.createElement("div");
    // jsdom doesn't implement isContentEditable; browsers do.
    Object.defineProperty(editable, "isContentEditable", { value: true });
    expect(isTypingTarget(editable)).toBe(true);
    expect(isTypingTarget(document.createElement("button"))).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });

  it("suppresses page shortcuts while typing in a field", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    expect(pageShortcutsSuppressed(keyFrom(input))).toBe(true);
    expect(pageShortcutsSuppressed(keyFrom(document.body))).toBe(false);
  });

  it("suppresses page shortcuts while any modal is open, even outside a field", () => {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    document.body.appendChild(bg);
    expect(pageShortcutsSuppressed(keyFrom(document.body))).toBe(true);
    bg.remove();
    expect(pageShortcutsSuppressed(keyFrom(document.body))).toBe(false);
  });
});
