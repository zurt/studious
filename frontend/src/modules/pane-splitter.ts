const STORAGE_KEY = "studious.pane-split";
const COLLAPSED_KEY = "studious.pane-collapsed";
const MIN_RATIO = 0.1;
const MAX_RATIO = 0.9;

type Collapsed = "none" | "left" | "right";

export function attachPaneSplitter(paneRow: HTMLElement) {
  const left = paneRow.querySelector<HTMLElement>(".pane.left");
  const right = paneRow.querySelector<HTMLElement>(".pane:not(.left)");
  if (!left || !right) return;

  const splitter = document.createElement("div");
  splitter.className = "pane-splitter";
  splitter.setAttribute("role", "separator");
  splitter.setAttribute("aria-orientation", "vertical");
  splitter.innerHTML = `
    <button type="button" class="pane-collapse-btn left" title="Collapse left pane" aria-label="Collapse left pane">‹</button>
    <div class="pane-splitter-handle" title="Drag to resize"></div>
    <button type="button" class="pane-collapse-btn right" title="Collapse right pane" aria-label="Collapse right pane">›</button>
  `;
  paneRow.insertBefore(splitter, right);

  const handle = splitter.querySelector<HTMLElement>(".pane-splitter-handle")!;
  const collapseLeftBtn = splitter.querySelector<HTMLButtonElement>(".pane-collapse-btn.left")!;
  const collapseRightBtn = splitter.querySelector<HTMLButtonElement>(".pane-collapse-btn.right")!;

  let ratio = loadRatio();
  let collapsed = loadCollapsed();

  function apply() {
    paneRow.dataset.collapsed = collapsed;
    if (collapsed === "left") {
      paneRow.style.setProperty("--pane-left", "0fr");
      paneRow.style.setProperty("--pane-right", "1fr");
    } else if (collapsed === "right") {
      paneRow.style.setProperty("--pane-left", "1fr");
      paneRow.style.setProperty("--pane-right", "0fr");
    } else {
      paneRow.style.setProperty("--pane-left", `${ratio}fr`);
      paneRow.style.setProperty("--pane-right", `${1 - ratio}fr`);
    }
    collapseLeftBtn.textContent = collapsed === "left" ? "›" : "‹";
    collapseLeftBtn.title = collapsed === "left" ? "Restore left pane" : "Collapse left pane";
    collapseRightBtn.textContent = collapsed === "right" ? "‹" : "›";
    collapseRightBtn.title = collapsed === "right" ? "Restore right pane" : "Collapse right pane";
  }

  apply();

  collapseLeftBtn.addEventListener("click", () => {
    collapsed = collapsed === "left" ? "none" : "left";
    saveCollapsed(collapsed);
    apply();
  });
  collapseRightBtn.addEventListener("click", () => {
    collapsed = collapsed === "right" ? "none" : "right";
    saveCollapsed(collapsed);
    apply();
  });

  handle.addEventListener("pointerdown", (e) => {
    if (collapsed !== "none") {
      collapsed = "none";
      saveCollapsed(collapsed);
    }
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    paneRow.classList.add("pane-row-resizing");

    const onMove = (ev: PointerEvent) => {
      const rect = paneRow.getBoundingClientRect();
      const splitterWidth = splitter.offsetWidth;
      const usable = rect.width - splitterWidth;
      if (usable <= 0) return;
      const x = ev.clientX - rect.left - splitterWidth / 2;
      let r = x / usable;
      if (r < MIN_RATIO) r = MIN_RATIO;
      if (r > MAX_RATIO) r = MAX_RATIO;
      ratio = r;
      apply();
    };
    const onUp = (ev: PointerEvent) => {
      handle.releasePointerCapture(ev.pointerId);
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      paneRow.classList.remove("pane-row-resizing");
      saveRatio(ratio);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
  });

  handle.addEventListener("dblclick", () => {
    ratio = 0.5;
    collapsed = "none";
    saveRatio(ratio);
    saveCollapsed(collapsed);
    apply();
  });
}

function loadRatio(): number {
  const raw = localStorage.getItem(STORAGE_KEY);
  const n = raw ? parseFloat(raw) : NaN;
  if (!Number.isFinite(n) || n < MIN_RATIO || n > MAX_RATIO) return 0.5;
  return n;
}
function saveRatio(r: number) {
  localStorage.setItem(STORAGE_KEY, String(r));
}
function loadCollapsed(): Collapsed {
  const raw = localStorage.getItem(COLLAPSED_KEY);
  return raw === "left" || raw === "right" ? raw : "none";
}
function saveCollapsed(c: Collapsed) {
  localStorage.setItem(COLLAPSED_KEY, c);
}
