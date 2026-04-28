/**
 * Make a page-info span click-to-edit. Click swaps the span for a number
 * input; Enter commits and navigates, Esc/blur cancels.
 */

export type PageInputOpts = {
  getMin: () => number;
  getMax: () => number;
  getCurrent: () => number;
  onCommit: (page: number) => void;
};

export function attachPageInput(span: HTMLElement, opts: PageInputOpts) {
  span.style.cursor = "pointer";
  span.title = "Click to jump to page";
  span.addEventListener("click", () => beginEdit(span, opts));
}

function beginEdit(span: HTMLElement, opts: PageInputOpts) {
  if (span.querySelector("input")) return;
  const min = opts.getMin();
  const max = opts.getMax();
  const current = opts.getCurrent();
  const prevText = span.textContent || "";

  const input = document.createElement("input");
  input.type = "number";
  input.min = String(min);
  input.max = String(max);
  input.value = String(current);
  input.className = "page-input";

  span.textContent = "";
  span.appendChild(input);
  input.focus();
  input.select();

  let done = false;
  function restore() {
    if (done) return;
    done = true;
    span.textContent = prevText;
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const raw = parseInt(input.value, 10);
      if (Number.isFinite(raw)) {
        const clamped = Math.min(max, Math.max(min, raw));
        restore();
        if (clamped !== current) opts.onCommit(clamped);
      } else {
        restore();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      restore();
    }
  });
  input.addEventListener("blur", restore);
}
