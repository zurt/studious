import "./styles.css";
import { initRouter, navigate } from "./router";
import { mountLibrary } from "./pages/library";
import { mountDocumentView } from "./pages/document-view";
import { mountChapterView } from "./pages/chapter-view";
import { mountGrammarGuide } from "./pages/grammar-guide";
import { mountVocabDashboard, mountGrammarDashboard } from "./pages/study-dashboard";
import { openSettingsModal, syncSettingsModalFromUrl } from "./modules/settings-modal";
import {
  openShortcutsHelp,
  closeShortcutsHelp,
  isShortcutsHelpOpen,
  isTypingTarget,
} from "./modules/shortcuts-help";

const root = document.getElementById("root")!;

root.innerHTML = `
  <div class="app" id="app">
    <div class="topbar" id="app-topbar">
      <h1><a href="/" id="home-link" style="color:inherit;text-decoration:none">Studious</a></h1>
      <nav class="topbar-nav">
        <a href="/vocab" class="topbar-link-btn" data-nav-link>Vocab</a>
        <a href="/grammar" class="topbar-link-btn" data-nav-link>Grammar</a>
      </nav>
      <div class="spacer"></div>
    </div>
    <div id="page-container" style="flex:1;display:flex;flex-direction:column;min-height:0"></div>
    <div class="floating-controls">
      <button id="help-btn" class="icon-btn" title="Keyboard shortcuts (?)" aria-label="Keyboard shortcuts"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></button>
      <button id="settings-btn" class="icon-btn" title="Settings" aria-label="Settings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg></button>
      <button id="fullscreen-btn" class="icon-btn" title="Toggle fullscreen" aria-label="Toggle fullscreen"></button>
    </div>
  </div>
`;

root.querySelector<HTMLAnchorElement>("#home-link")!.addEventListener("click", (e) => {
  e.preventDefault();
  navigate("/");
});

root.querySelectorAll<HTMLAnchorElement>("[data-nav-link]").forEach((a) => {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    navigate(a.getAttribute("href")!);
  });
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

root.querySelector<HTMLButtonElement>("#help-btn")!.addEventListener("click", () => {
  openShortcutsHelp();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && isShortcutsHelpOpen()) {
    closeShortcutsHelp();
    return;
  }
  if (e.key !== "?") return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (isTypingTarget(e.target)) return;
  e.preventDefault();
  if (isShortcutsHelpOpen()) closeShortcutsHelp();
  else openShortcutsHelp();
});

const pageContainer = root.querySelector<HTMLElement>("#page-container")!;

initRouter(pageContainer, [
  { pattern: "/", mount: mountLibrary },
  { pattern: "/doc/:id", mount: mountDocumentView },
  { pattern: "/doc/:id/chapter/:chapterId", mount: mountChapterView },
  { pattern: "/doc/:id/chapter/:chapterId/grammar-guide", mount: mountGrammarGuide },
  { pattern: "/vocab", mount: mountVocabDashboard },
  { pattern: "/grammar", mount: mountGrammarDashboard },
]);

// When the page changes while in fullscreen, ensure controls land in the new page's topbar.
const pageObserver = new MutationObserver(() => {
  if (document.fullscreenElement) relocateFloatingControls();
});
pageObserver.observe(pageContainer, { childList: true });

window.addEventListener("popstate", syncSettingsModalFromUrl);
syncSettingsModalFromUrl();
