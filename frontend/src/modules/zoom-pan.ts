/**
 * Map-like zoom/pan viewer for page images.
 *
 * - Pinch-to-zoom on trackpad
 * - Two-finger scroll to pan
 * - Cmd+/- to zoom, Cmd+0 for actual size
 * - Zoom-to-fit button
 * - Min/max zoom limits
 */

const MIN_SCALE = 0.25;
const MAX_SCALE = 5.0;

export type ZoomPanViewer = {
  container: HTMLElement;
  setImage: (src: string) => void;
  getImage: () => HTMLImageElement;
  zoomToFit: () => void;
  destroy: () => void;
};

export function createZoomPanViewer(parent: HTMLElement): ZoomPanViewer {
  const container = document.createElement("div");
  container.className = "zp-container";

  const viewport = document.createElement("div");
  viewport.className = "zp-viewport";

  const content = document.createElement("div");
  content.className = "zp-content";

  const img = document.createElement("img");
  img.className = "zp-img";
  img.alt = "Page";

  content.appendChild(img);
  viewport.appendChild(content);

  // Fit button
  const fitBtn = document.createElement("button");
  fitBtn.className = "zp-fit-btn";
  fitBtn.title = "Zoom to fit";
  fitBtn.textContent = "Fit";
  container.appendChild(viewport);
  container.appendChild(fitBtn);

  parent.appendChild(container);

  let scale = 1;
  let translateX = 0;
  let translateY = 0;

  function applyTransform() {
    content.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
  }

  function clampScale(s: number): number {
    return Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));
  }

  function zoomToFit() {
    if (!img.naturalWidth) return;
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;
    scale = clampScale(Math.min(vw / iw, vh / ih));
    translateX = (vw - iw * scale) / 2;
    translateY = (vh - ih * scale) / 2;
    applyTransform();
  }

  function zoomActualSize() {
    if (!img.naturalWidth) return;
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    scale = 1;
    translateX = (vw - img.naturalWidth) / 2;
    translateY = (vh - img.naturalHeight) / 2;
    applyTransform();
  }

  function zoomBy(factor: number, cx: number, cy: number) {
    const newScale = clampScale(scale * factor);
    if (newScale === scale) return;
    // Zoom centered on (cx, cy) in viewport coords
    const ratio = newScale / scale;
    translateX = cx - (cx - translateX) * ratio;
    translateY = cy - (cy - translateY) * ratio;
    scale = newScale;
    applyTransform();
  }

  // Wheel: pinch-to-zoom (ctrlKey set by trackpad pinch) or two-finger scroll
  function onWheel(e: WheelEvent) {
    e.preventDefault();
    if (e.ctrlKey) {
      // Pinch zoom
      const rect = viewport.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const factor = Math.pow(0.99, e.deltaY);
      zoomBy(factor, cx, cy);
    } else {
      // Pan
      translateX -= e.deltaX;
      translateY -= e.deltaY;
      applyTransform();
    }
  }

  // Keyboard: Cmd+/-, Cmd+0
  function onKey(e: KeyboardEvent) {
    if (!e.metaKey && !e.ctrlKey) return;
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    const cx = vw / 2;
    const cy = vh / 2;
    if (e.key === "=" || e.key === "+") {
      e.preventDefault();
      zoomBy(1.25, cx, cy);
    } else if (e.key === "-") {
      e.preventDefault();
      zoomBy(0.8, cx, cy);
    } else if (e.key === "0") {
      e.preventDefault();
      zoomActualSize();
    }
  }

  viewport.addEventListener("wheel", onWheel, { passive: false });
  document.addEventListener("keydown", onKey);
  fitBtn.addEventListener("click", zoomToFit);

  img.addEventListener("load", () => {
    zoomToFit();
  });

  return {
    container,
    setImage(src: string) {
      img.src = src;
    },
    getImage() {
      return img;
    },
    zoomToFit,
    destroy() {
      viewport.removeEventListener("wheel", onWheel);
      document.removeEventListener("keydown", onKey);
      container.remove();
    },
  };
}
