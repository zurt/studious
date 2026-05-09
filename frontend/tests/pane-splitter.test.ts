import { describe, it, expect, beforeEach } from "vitest";
import { attachPaneSplitter } from "../src/modules/pane-splitter";

const STORAGE_KEY = "studious.pane-split";
const COLLAPSED_KEY = "studious.pane-collapsed";

function makeRow(): HTMLElement {
  const row = document.createElement("div");
  row.className = "pane-row";
  const left = document.createElement("div");
  left.className = "pane left";
  const right = document.createElement("div");
  right.className = "pane right";
  row.appendChild(left);
  row.appendChild(right);
  document.body.appendChild(row);
  return row;
}

describe("pane-splitter", () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = "";
  });

  it("loads a stored valid ratio and applies it to CSS vars", () => {
    localStorage.setItem(STORAGE_KEY, "0.7");
    const row = makeRow();
    attachPaneSplitter(row);
    expect(row.style.getPropertyValue("--pane-left")).toBe("0.7fr");
    expect(row.style.getPropertyValue("--pane-right")).toBe(`${1 - 0.7}fr`);
    expect(row.dataset.collapsed).toBe("none");
  });

  it("falls back to 0.5 when stored ratio is out of bounds", () => {
    localStorage.setItem(STORAGE_KEY, "0.99");
    const row = makeRow();
    attachPaneSplitter(row);
    expect(row.style.getPropertyValue("--pane-left")).toBe("0.5fr");
  });

  it("falls back to 0.5 on garbage in localStorage", () => {
    localStorage.setItem(STORAGE_KEY, "not-a-number");
    const row = makeRow();
    attachPaneSplitter(row);
    expect(row.style.getPropertyValue("--pane-left")).toBe("0.5fr");
  });

  it("applies collapsed=left from localStorage", () => {
    localStorage.setItem(COLLAPSED_KEY, "left");
    const row = makeRow();
    attachPaneSplitter(row);
    expect(row.dataset.collapsed).toBe("left");
    expect(row.style.getPropertyValue("--pane-left")).toBe("0fr");
    expect(row.style.getPropertyValue("--pane-right")).toBe("1fr");
  });

  it("clicking collapse-left button toggles state and persists it", () => {
    const row = makeRow();
    attachPaneSplitter(row);
    expect(row.dataset.collapsed).toBe("none");

    const leftBtn = row.querySelector<HTMLButtonElement>(".pane-collapse-btn.left")!;
    leftBtn.click();
    expect(row.dataset.collapsed).toBe("left");
    expect(localStorage.getItem(COLLAPSED_KEY)).toBe("left");

    leftBtn.click();
    expect(row.dataset.collapsed).toBe("none");
    expect(localStorage.getItem(COLLAPSED_KEY)).toBe("none");
  });

  it("clicking collapse-right button toggles right collapse", () => {
    const row = makeRow();
    attachPaneSplitter(row);
    const rightBtn = row.querySelector<HTMLButtonElement>(".pane-collapse-btn.right")!;
    rightBtn.click();
    expect(row.dataset.collapsed).toBe("right");
    expect(row.style.getPropertyValue("--pane-left")).toBe("1fr");
    expect(row.style.getPropertyValue("--pane-right")).toBe("0fr");
  });

  it("dblclick on the handle resets ratio to 0.5 and clears collapse", () => {
    localStorage.setItem(STORAGE_KEY, "0.8");
    localStorage.setItem(COLLAPSED_KEY, "left");
    const row = makeRow();
    attachPaneSplitter(row);
    expect(row.dataset.collapsed).toBe("left");

    const handle = row.querySelector<HTMLElement>(".pane-splitter-handle")!;
    handle.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));

    expect(row.dataset.collapsed).toBe("none");
    expect(row.style.getPropertyValue("--pane-left")).toBe("0.5fr");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("0.5");
    expect(localStorage.getItem(COLLAPSED_KEY)).toBe("none");
  });

  it("returns silently when the row lacks the expected panes", () => {
    const row = document.createElement("div");
    document.body.appendChild(row);
    expect(() => attachPaneSplitter(row)).not.toThrow();
  });
});
