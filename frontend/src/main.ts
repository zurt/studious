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
      <button id="fullscreen-btn" class="icon-btn" title="Toggle fullscreen">&#x26F6;</button>
    </div>
  </div>
`;

root.querySelector<HTMLAnchorElement>("#home-link")!.addEventListener("click", (e) => {
  e.preventDefault();
  navigate("/");
});

// Fullscreen toggle
const fsBtn = root.querySelector<HTMLButtonElement>("#fullscreen-btn")!;
fsBtn.addEventListener("click", () => {
  if (document.fullscreenElement) {
    document.exitFullscreen();
  } else {
    document.getElementById("app")!.requestFullscreen();
  }
});
document.addEventListener("fullscreenchange", () => {
  fsBtn.textContent = document.fullscreenElement ? "\u2716" : "\u26F6";
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

window.addEventListener("popstate", syncSettingsModalFromUrl);
syncSettingsModalFromUrl();
