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

const CHEVRON_RIGHT = `<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 6 15 12 9 18"/></svg>`;
const CHEVRON_DOWN = `<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>`;

export function chevronHtml(collapsed: boolean): string {
  return `<span class="pane-chevron" aria-hidden="true">${collapsed ? CHEVRON_RIGHT : CHEVRON_DOWN}</span>`;
}

export function setChevronCollapsed(el: HTMLElement, collapsed: boolean): void {
  el.innerHTML = collapsed ? CHEVRON_RIGHT : CHEVRON_DOWN;
}
