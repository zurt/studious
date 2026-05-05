export type PaneId = "transcription" | "breakdown";

const STORAGE_PREFIX = "studious.pane.";
const storageKey = (id: PaneId) => `${STORAGE_PREFIX}${id}.collapsed`;

export function isPaneCollapsed(id: PaneId): boolean {
  return localStorage.getItem(storageKey(id)) === "1";
}

export function setPaneCollapsed(id: PaneId, collapsed: boolean): void {
  localStorage.setItem(storageKey(id), collapsed ? "1" : "0");
}

export function applyPaneCollapsed(container: HTMLElement, id: PaneId): void {
  container.classList.toggle("is-collapsed", isPaneCollapsed(id));
}

export function chevronHtml(collapsed: boolean): string {
  // Right-pointing when collapsed, down-pointing when open.
  return `<span class="pane-chevron" aria-hidden="true">${collapsed ? "▸" : "▾"}</span>`;
}
