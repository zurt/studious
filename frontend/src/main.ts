import "./styles.css";
import { initRouter, navigate } from "./router";
import { mountLibrary } from "./pages/library";
import { mountDocumentView } from "./pages/document-view";
import { mountChapterView } from "./pages/chapter-view";
import { openSettingsModal, syncSettingsModalFromUrl } from "./modules/settings-modal";

const root = document.getElementById("root")!;

root.innerHTML = `
  <div class="app" id="app">
    <div class="topbar" id="app-topbar">
      <h1><a href="/" id="home-link" style="color:inherit;text-decoration:none">Studious</a></h1>
      <div class="spacer"></div>
    </div>
    <div id="page-container" style="flex:1;display:flex;flex-direction:column;min-height:0"></div>
    <div class="floating-controls">
      <button id="settings-btn" class="icon-btn" title="Settings" aria-label="Settings">&#x2699;</button>
      <button id="fullscreen-btn" class="icon-btn" title="Toggle fullscreen" aria-label="Toggle fullscreen"></button>
    </div>
  </div>
`;

root.querySelector<HTMLAnchorElement>("#home-link")!.addEventListener("click", (e) => {
  e.preventDefault();
  navigate("/");
});

const appEl = document.getElementById("app")!;
const floatingControls = root.querySelector<HTMLElement>(".floating-controls")!;

function relocateFloatingControls() {
  const fs = !!document.fullscreenElement;
  const pageTopbar = document.querySelector<HTMLElement>("#page-container .topbar");
  if (fs && pageTopbar) {
    if (floatingControls.parentElement !== pageTopbar) pageTopbar.appendChild(floatingControls);
    floatingControls.classList.add("inline");
  } else {
    if (floatingControls.parentElement !== appEl) appEl.appendChild(floatingControls);
    floatingControls.classList.remove("inline");
  }
}

// Fullscreen toggle
const fsBtn = root.querySelector<HTMLButtonElement>("#fullscreen-btn")!;
fsBtn.addEventListener("click", () => {
  if (document.fullscreenElement) {
    document.exitFullscreen();
  } else {
    document.getElementById("app")!.requestFullscreen();
  }
});
const FS_ENTER_ICON = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="4 9 4 4 9 4"/><polyline points="20 9 20 4 15 4"/><polyline points="4 15 4 20 9 20"/><polyline points="20 15 20 20 15 20"/></svg>`;
const FS_EXIT_ICON = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 4 9 9 4 9"/><polyline points="15 4 15 9 20 9"/><polyline points="9 20 9 15 4 15"/><polyline points="15 20 15 15 20 15"/></svg>`;
function updateFsIcon() {
  fsBtn.innerHTML = document.fullscreenElement ? FS_EXIT_ICON : FS_ENTER_ICON;
  fsBtn.title = document.fullscreenElement ? "Exit fullscreen" : "Enter fullscreen";
}
updateFsIcon();
document.addEventListener("fullscreenchange", () => {
  updateFsIcon();
  relocateFloatingControls();
});

root.querySelector<HTMLButtonElement>("#settings-btn")!.addEventListener("click", () => {
  openSettingsModal();
});

const pageContainer = root.querySelector<HTMLElement>("#page-container")!;

initRouter(pageContainer, [
  { pattern: "/", mount: mountLibrary },
  { pattern: "/doc/:id", mount: mountDocumentView },
  { pattern: "/doc/:id/chapter/:chapterId", mount: mountChapterView },
]);

// When the page changes while in fullscreen, ensure controls land in the new page's topbar.
const pageObserver = new MutationObserver(() => {
  if (document.fullscreenElement) relocateFloatingControls();
});
pageObserver.observe(pageContainer, { childList: true });

window.addEventListener("popstate", syncSettingsModalFromUrl);
syncSettingsModalFromUrl();
