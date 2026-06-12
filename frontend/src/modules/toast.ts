export type ToastKind = "error" | "info";

const DEFAULT_DURATION_MS = 6000;

function getContainer(): HTMLElement {
  const root = document.fullscreenElement ?? document.body;
  let container = document.querySelector<HTMLElement>(".toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
  }
  // Re-append so toasts stay visible if fullscreen was entered/exited.
  if (container.parentElement !== root) root.appendChild(container);
  return container;
}

export function showToast(message: string, kind: ToastKind = "error", durationMs = DEFAULT_DURATION_MS): HTMLElement {
  const container = getContainer();
  const toast = document.createElement("div");
  toast.className = `toast toast-${kind}`;
  toast.setAttribute("role", kind === "error" ? "alert" : "status");
  toast.textContent = message;
  container.appendChild(toast);

  let dismissed = false;
  const dismiss = () => {
    if (dismissed) return;
    dismissed = true;
    clearTimeout(timer);
    toast.classList.add("toast-leaving");
    // Match the CSS transition; remove() in case transitionend never fires (jsdom, reduced motion).
    toast.addEventListener("transitionend", () => toast.remove(), { once: true });
    setTimeout(() => {
      toast.remove();
      if (container.childElementCount === 0) container.remove();
    }, 300);
  };

  const timer = setTimeout(dismiss, durationMs);
  toast.addEventListener("click", dismiss);
  return toast;
}

export function toastError(message: string): HTMLElement {
  return showToast(message, "error");
}

export function toastInfo(message: string): HTMLElement {
  return showToast(message, "info");
}
