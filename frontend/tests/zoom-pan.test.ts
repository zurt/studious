import { describe, it, expect, beforeEach } from "vitest";
import { createZoomPanViewer } from "../src/modules/zoom-pan";

function setSize(el: HTMLElement, w: number, h: number) {
  Object.defineProperty(el, "clientWidth", { value: w, configurable: true });
  Object.defineProperty(el, "clientHeight", { value: h, configurable: true });
}

function setNaturalSize(img: HTMLImageElement, w: number, h: number) {
  Object.defineProperty(img, "naturalWidth", { value: w, configurable: true });
  Object.defineProperty(img, "naturalHeight", { value: h, configurable: true });
}

function parseTransform(content: HTMLElement) {
  const m = content.style.transform.match(
    /translate\(([-\d.]+)px,\s*([-\d.]+)px\)\s*scale\(([-\d.]+)\)/,
  );
  if (!m) throw new Error(`unparseable transform: "${content.style.transform}"`);
  return { tx: parseFloat(m[1]), ty: parseFloat(m[2]), s: parseFloat(m[3]) };
}

describe("zoom-pan", () => {
  let parent: HTMLElement;

  beforeEach(() => {
    document.body.innerHTML = "";
    parent = document.createElement("div");
    document.body.appendChild(parent);
  });

  it("zoomToFit picks the smaller of vw/iw and vh/ih and centers the image", () => {
    const viewer = createZoomPanViewer(parent);
    const viewport = viewer.container.querySelector<HTMLElement>(".zp-viewport")!;
    const content = viewer.container.querySelector<HTMLElement>(".zp-content")!;
    const img = viewer.getImage();
    setSize(viewport, 800, 600);
    setNaturalSize(img, 1000, 1000);

    viewer.zoomToFit();
    const { tx, ty, s } = parseTransform(content);
    expect(s).toBeCloseTo(0.6, 5);
    expect(tx).toBeCloseTo((800 - 1000 * 0.6) / 2, 5);
    expect(ty).toBeCloseTo((600 - 1000 * 0.6) / 2, 5);
  });

  it("zoomToFitWidth scales to viewport width", () => {
    const viewer = createZoomPanViewer(parent);
    const viewport = viewer.container.querySelector<HTMLElement>(".zp-viewport")!;
    const content = viewer.container.querySelector<HTMLElement>(".zp-content")!;
    const img = viewer.getImage();
    setSize(viewport, 800, 600);
    setNaturalSize(img, 400, 1600);

    viewer.zoomToFitWidth();
    const { s } = parseTransform(content);
    expect(s).toBeCloseTo(2, 5);
  });

  it("zoomToFit clamps to the minimum scale on a tiny viewport", () => {
    const viewer = createZoomPanViewer(parent);
    const viewport = viewer.container.querySelector<HTMLElement>(".zp-viewport")!;
    const content = viewer.container.querySelector<HTMLElement>(".zp-content")!;
    const img = viewer.getImage();
    setSize(viewport, 50, 50);
    setNaturalSize(img, 10000, 10000);

    viewer.zoomToFit();
    const { s } = parseTransform(content);
    expect(s).toBeCloseTo(0.25, 5);
  });

  it("ctrl+wheel zooms about the cursor (transform math invariant)", () => {
    const viewer = createZoomPanViewer(parent);
    const viewport = viewer.container.querySelector<HTMLElement>(".zp-viewport")!;
    const content = viewer.container.querySelector<HTMLElement>(".zp-content")!;
    const img = viewer.getImage();
    setSize(viewport, 800, 600);
    setNaturalSize(img, 1000, 1000);
    viewer.zoomToFit();

    const before = parseTransform(content);
    const cx = 400;
    const cy = 300;
    // Image-space point under (cx, cy) before zoom
    const imgX = (cx - before.tx) / before.s;
    const imgY = (cy - before.ty) / before.s;

    viewport.dispatchEvent(
      new WheelEvent("wheel", { deltaY: -50, ctrlKey: true, clientX: cx, clientY: cy }),
    );

    const after = parseTransform(content);
    expect(after.s).toBeGreaterThan(before.s);
    // The image-space point under the cursor is unchanged after zoom.
    expect(after.tx + imgX * after.s).toBeCloseTo(cx, 3);
    expect(after.ty + imgY * after.s).toBeCloseTo(cy, 3);
  });

  it("plain wheel pans by -deltaX/-deltaY (subject to clamping)", () => {
    const viewer = createZoomPanViewer(parent);
    const viewport = viewer.container.querySelector<HTMLElement>(".zp-viewport")!;
    const content = viewer.container.querySelector<HTMLElement>(".zp-content")!;
    const img = viewer.getImage();
    setSize(viewport, 800, 600);
    setNaturalSize(img, 1000, 1000);
    viewer.zoomToFit();

    const before = parseTransform(content);
    viewport.dispatchEvent(new WheelEvent("wheel", { deltaX: 30, deltaY: 20 }));
    const after = parseTransform(content);
    // Small pan inside the clamping window — should move by exactly -deltaX/-deltaY.
    expect(after.tx).toBeCloseTo(before.tx - 30, 5);
    expect(after.ty).toBeCloseTo(before.ty - 20, 5);
  });

  it("pan clamps so the image cannot leave the viewport entirely", () => {
    const viewer = createZoomPanViewer(parent);
    const viewport = viewer.container.querySelector<HTMLElement>(".zp-viewport")!;
    const content = viewer.container.querySelector<HTMLElement>(".zp-content")!;
    const img = viewer.getImage();
    setSize(viewport, 800, 600);
    setNaturalSize(img, 1000, 1000);
    viewer.zoomToFit();

    // Try to pan way off to the right with a huge wheel delta.
    viewport.dispatchEvent(new WheelEvent("wheel", { deltaX: -100000, deltaY: 0 }));
    const t = parseTransform(content);
    // Image right edge is tx + iw*s; this must remain >= a positive PAN_MARGIN
    // after clamping (image cannot disappear past the left edge).
    expect(t.tx + 1000 * t.s).toBeGreaterThan(0);
    // And tx must not exceed the viewport's right side either.
    expect(t.tx).toBeLessThan(800);
  });

  it("destroy removes the viewer from the DOM", () => {
    const viewer = createZoomPanViewer(parent);
    expect(parent.querySelector(".zp-container")).not.toBeNull();
    viewer.destroy();
    expect(parent.querySelector(".zp-container")).toBeNull();
  });
});
