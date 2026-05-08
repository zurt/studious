/**
 * Map-like zoom/pan viewer for page images.
 *
 * - Pinch-to-zoom on trackpad
 * - Two-finger scroll to pan
 * - Cmd+/- to zoom, Cmd+0 for actual size
 * - Zoom-to-fit and fit-width buttons
 * - Min/max zoom limits
 */

const MIN_SCALE = 0.25;
const MAX_SCALE = 5.0;
const PAN_MARGIN = 40;

export type ZoomPanViewer = {
  container: HTMLElement;
  setImage: (src: string) => void;
  getImage: () => HTMLImageElement;
  zoomToFit: () => void;
  zoomToFitWidth: () => void;
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

  // Fit button group
  const fitGroup = document.createElement("div");
  fitGroup.className = "zp-fit-group";

  const fitBtn = document.createElement("button");
  fitBtn.className = "zp-fit-btn";
  fitBtn.title = "Zoom to fit";
  fitBtn.setAttribute("aria-label", "Zoom to fit");
  fitBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="1.5" y="1.5" width="13" height="13" rx="1.5"/><rect x="4.5" y="5.5" width="7" height="5" rx="0.5"/></svg>`;

  const fitWidthBtn = document.createElement("button");
  fitWidthBtn.className = "zp-fit-btn";
  fitWidthBtn.title = "Fit width";
  fitWidthBtn.setAttribute("aria-label", "Fit width");
  fitWidthBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 8h12M2 8l3-3M2 8l3 3M14 8l-3-3M14 8l-3 3"/></svg>`;

  fitGroup.appendChild(fitBtn);
  fitGroup.appendChild(fitWidthBtn);

  container.appendChild(viewport);
  container.appendChild(fitGroup);

  parent.appendChild(container);

  let scale = 1;
  let translateX = 0;
  let translateY = 0;

  function clampTranslation() {
    if (!img.naturalWidth) return;
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    const iw = img.naturalWidth * scale;
    const ih = img.naturalHeight * scale;
    const marginX = Math.min(PAN_MARGIN, iw, vw);
    const marginY = Math.min(PAN_MARGIN, ih, vh);
    const aX = marginX - iw;
    const bX = vw - marginX;
    const aY = marginY - ih;
    const bY = vh - marginY;
    const minX = Math.min(aX, bX);
    const maxX = Math.max(aX, bX);
    const minY = Math.min(aY, bY);
    const maxY = Math.max(aY, bY);
    translateX = Math.min(maxX, Math.max(minX, translateX));
    translateY = Math.min(maxY, Math.max(minY, translateY));
  }

  function applyTransform() {
    clampTranslation();
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

  function zoomToFitWidth() {
    if (!img.naturalWidth) return;
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;
    scale = clampScale(vw / iw);
    translateX = (vw - iw * scale) / 2;
    translateY = Math.max(0, (vh - ih * scale) / 2);
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
  fitWidthBtn.addEventListener("click", zoomToFitWidth);

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
    zoomToFitWidth,
    destroy() {
      viewport.removeEventListener("wheel", onWheel);
      document.removeEventListener("keydown", onKey);
      container.remove();
    },
  };
}
