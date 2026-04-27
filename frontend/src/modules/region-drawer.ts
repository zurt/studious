/**
 * Canvas overlay for drawing and displaying bounding box regions on a page image.
 *
 * Usage:
 *   const drawer = createRegionDrawer(imgElement, {
 *     regions: existingRegions,
 *     onDraw: (bbox) => { ... },
 *   });
 *   // Later: drawer.setRegions(updatedRegions)
 *   // Cleanup: drawer.destroy()
 */

export type DrawableRegion = {
  id: string;
  bbox: [number, number, number, number]; // normalized [x1, y1, x2, y2]
  tag: string;
  label: string;
  selected?: boolean;
};

export type RegionDrawerOptions = {
  regions?: DrawableRegion[];
  onDraw?: (bbox: [number, number, number, number]) => void;
  onSelect?: (regionId: string) => void;
};

const TAG_COLORS: Record<string, string> = {
  reading_passage: "rgba(37, 99, 235, 0.25)",
  vocab_list: "rgba(22, 163, 74, 0.25)",
  grammar_points: "rgba(168, 85, 247, 0.25)",
  exercises: "rgba(234, 88, 12, 0.25)",
  instructions: "rgba(107, 114, 128, 0.25)",
  other: "rgba(107, 114, 128, 0.15)",
};

const TAG_BORDERS: Record<string, string> = {
  reading_passage: "rgba(37, 99, 235, 0.7)",
  vocab_list: "rgba(22, 163, 74, 0.7)",
  grammar_points: "rgba(168, 85, 247, 0.7)",
  exercises: "rgba(234, 88, 12, 0.7)",
  instructions: "rgba(107, 114, 128, 0.7)",
  other: "rgba(107, 114, 128, 0.5)",
};

export function createRegionDrawer(img: HTMLImageElement, opts: RegionDrawerOptions) {
  const canvas = document.createElement("canvas");
  canvas.style.position = "absolute";
  canvas.style.top = "0";
  canvas.style.left = "0";
  canvas.style.cursor = "crosshair";
  canvas.style.pointerEvents = "auto";

  // Wrap img in a relative container if not already
  const wrapper = document.createElement("div");
  wrapper.style.position = "relative";
  wrapper.style.display = "inline-block";
  img.parentElement?.insertBefore(wrapper, img);
  wrapper.appendChild(img);
  wrapper.appendChild(canvas);

  let regions = opts.regions || [];
  let drawing = false;
  let startX = 0;
  let startY = 0;
  let currentX = 0;
  let currentY = 0;

  function syncSize() {
    const w = img.clientWidth;
    const h = img.clientHeight;
    canvas.width = w;
    canvas.height = h;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    redraw();
  }

  function redraw() {
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Draw existing regions
    for (const r of regions) {
      const [x1, y1, x2, y2] = r.bbox;
      const rx = x1 * w;
      const ry = y1 * h;
      const rw = (x2 - x1) * w;
      const rh = (y2 - y1) * h;

      ctx.fillStyle = TAG_COLORS[r.tag] || TAG_COLORS.other;
      ctx.fillRect(rx, ry, rw, rh);

      ctx.strokeStyle = r.selected
        ? "rgba(255, 200, 0, 0.9)"
        : TAG_BORDERS[r.tag] || TAG_BORDERS.other;
      ctx.lineWidth = r.selected ? 2 : 1;
      ctx.strokeRect(rx, ry, rw, rh);

      // Label
      if (r.label) {
        ctx.font = "11px system-ui, sans-serif";
        ctx.fillStyle = TAG_BORDERS[r.tag] || TAG_BORDERS.other;
        ctx.fillText(r.label, rx + 3, ry + 13);
      }
    }

    // Draw in-progress selection
    if (drawing) {
      const rx = Math.min(startX, currentX);
      const ry = Math.min(startY, currentY);
      const rw = Math.abs(currentX - startX);
      const rh = Math.abs(currentY - startY);
      ctx.strokeStyle = "rgba(255, 200, 0, 0.9)";
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.strokeRect(rx, ry, rw, rh);
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(255, 200, 0, 0.1)";
      ctx.fillRect(rx, ry, rw, rh);
    }
  }

  function getPos(e: MouseEvent): [number, number] {
    const rect = canvas.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  }

  function onMouseDown(e: MouseEvent) {
    // Check if clicking on an existing region
    const [mx, my] = getPos(e);
    const w = canvas.width;
    const h = canvas.height;
    const nx = mx / w;
    const ny = my / h;

    for (const r of regions) {
      const [x1, y1, x2, y2] = r.bbox;
      if (nx >= x1 && nx <= x2 && ny >= y1 && ny <= y2) {
        opts.onSelect?.(r.id);
        return;
      }
    }

    drawing = true;
    [startX, startY] = [mx, my];
    [currentX, currentY] = [mx, my];
  }

  function onMouseMove(e: MouseEvent) {
    if (!drawing) return;
    [currentX, currentY] = getPos(e);
    redraw();
  }

  function onMouseUp(_e: MouseEvent) {
    if (!drawing) return;
    drawing = false;

    const w = canvas.width;
    const h = canvas.height;
    const x1 = Math.min(startX, currentX) / w;
    const y1 = Math.min(startY, currentY) / h;
    const x2 = Math.max(startX, currentX) / w;
    const y2 = Math.max(startY, currentY) / h;

    // Ignore tiny drags (accidental clicks)
    if ((x2 - x1) < 0.02 || (y2 - y1) < 0.02) {
      redraw();
      return;
    }

    const bbox: [number, number, number, number] = [
      Math.round(x1 * 1000) / 1000,
      Math.round(y1 * 1000) / 1000,
      Math.round(x2 * 1000) / 1000,
      Math.round(y2 * 1000) / 1000,
    ];
    opts.onDraw?.(bbox);
    redraw();
  }

  canvas.addEventListener("mousedown", onMouseDown);
  canvas.addEventListener("mousemove", onMouseMove);
  canvas.addEventListener("mouseup", onMouseUp);

  // Sync on load and resize
  if (img.complete) syncSize();
  img.addEventListener("load", syncSize);
  const resizeObserver = new ResizeObserver(syncSize);
  resizeObserver.observe(img);

  return {
    setRegions(newRegions: DrawableRegion[]) {
      regions = newRegions;
      redraw();
    },
    destroy() {
      canvas.removeEventListener("mousedown", onMouseDown);
      canvas.removeEventListener("mousemove", onMouseMove);
      canvas.removeEventListener("mouseup", onMouseUp);
      img.removeEventListener("load", syncSize);
      resizeObserver.disconnect();
      canvas.remove();
      // Unwrap img from wrapper
      wrapper.parentElement?.insertBefore(img, wrapper);
      wrapper.remove();
    },
  };
}
