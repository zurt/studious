import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  createRegionDrawer,
  type DrawableRegion,
} from "../src/modules/region-drawer";

class FakeResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}

function makeImage(width = 1000, height = 1000): HTMLImageElement {
  const img = document.createElement("img");
  Object.defineProperty(img, "clientWidth", { value: width, configurable: true });
  Object.defineProperty(img, "clientHeight", { value: height, configurable: true });
  Object.defineProperty(img, "complete", { value: true, configurable: true });
  document.body.appendChild(img);
  return img;
}

function fireMouse(canvas: HTMLCanvasElement, type: string, x: number, y: number) {
  canvas.dispatchEvent(
    new MouseEvent(type, { clientX: x, clientY: y, bubbles: true }),
  );
}

describe("region-drawer", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    document.body.innerHTML = "";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("a drag above the threshold fires onDraw with normalized bbox", () => {
    const img = makeImage(1000, 1000);
    const onDraw = vi.fn();
    createRegionDrawer(img, { onDraw });
    const canvas = document.querySelector("canvas")!;

    fireMouse(canvas, "mousedown", 100, 200);
    fireMouse(canvas, "mousemove", 300, 600);
    fireMouse(canvas, "mouseup", 300, 600);

    expect(onDraw).toHaveBeenCalledTimes(1);
    const bbox = onDraw.mock.calls[0]![0] as [number, number, number, number];
    const [x1, y1, x2, y2] = bbox;
    expect(x1).toBeLessThan(x2);
    expect(y1).toBeLessThan(y2);
    for (const v of bbox) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
    }
    expect(x1).toBeCloseTo(0.1, 3);
    expect(y1).toBeCloseTo(0.2, 3);
    expect(x2).toBeCloseTo(0.3, 3);
    expect(y2).toBeCloseTo(0.6, 3);
  });

  it("normalizes bbox even when the drag goes up-and-left", () => {
    const img = makeImage(1000, 1000);
    const onDraw = vi.fn();
    createRegionDrawer(img, { onDraw });
    const canvas = document.querySelector("canvas")!;

    fireMouse(canvas, "mousedown", 800, 800);
    fireMouse(canvas, "mousemove", 200, 100);
    fireMouse(canvas, "mouseup", 200, 100);

    const [x1, y1, x2, y2] = onDraw.mock.calls[0]![0];
    expect(x1).toBeLessThan(x2);
    expect(y1).toBeLessThan(y2);
  });

  it("ignores tiny drags below the click threshold", () => {
    const img = makeImage(1000, 1000);
    const onDraw = vi.fn();
    createRegionDrawer(img, { onDraw });
    const canvas = document.querySelector("canvas")!;

    fireMouse(canvas, "mousedown", 500, 500);
    fireMouse(canvas, "mousemove", 505, 505);
    fireMouse(canvas, "mouseup", 505, 505);

    expect(onDraw).not.toHaveBeenCalled();
  });

  it("clicking inside an existing region calls onSelect, not onDraw", () => {
    const img = makeImage(1000, 1000);
    const regions: DrawableRegion[] = [
      { id: "r1", bbox: [0.1, 0.1, 0.4, 0.4], tag: "reading_passage", label: "" },
    ];
    const onDraw = vi.fn();
    const onSelect = vi.fn();
    createRegionDrawer(img, { regions, onDraw, onSelect });
    const canvas = document.querySelector("canvas")!;

    fireMouse(canvas, "mousedown", 250, 250);
    fireMouse(canvas, "mouseup", 250, 250);

    expect(onSelect).toHaveBeenCalledWith("r1");
    expect(onDraw).not.toHaveBeenCalled();
  });

  it("setRegions replaces the region list and re-renders without throwing", () => {
    const img = makeImage(1000, 1000);
    const drawer = createRegionDrawer(img, { regions: [] });
    expect(() =>
      drawer.setRegions([
        { id: "a", bbox: [0, 0, 0.5, 0.5], tag: "vocab_list", label: "A" },
        { id: "b", bbox: [0.5, 0.5, 1, 1], tag: "exercises", label: "B" },
      ]),
    ).not.toThrow();
  });

  it("destroy unwraps img and removes the canvas", () => {
    const img = makeImage(1000, 1000);
    const drawer = createRegionDrawer(img, {});
    expect(document.querySelector("canvas")).not.toBeNull();
    drawer.destroy();
    expect(document.querySelector("canvas")).toBeNull();
    expect(img.parentElement).toBe(document.body);
  });
});
