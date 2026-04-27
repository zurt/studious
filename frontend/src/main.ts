import "./styles.css";
import { initRouter, navigate } from "./router";
import { mountLibrary } from "./pages/library";
import { mountDocumentView } from "./pages/document-view";
import { mountChapterView } from "./pages/chapter-view";

const root = document.getElementById("root")!;

root.innerHTML = `
  <div class="app">
    <div class="topbar">
      <h1><a href="/" id="home-link" style="color:inherit;text-decoration:none">Studious</a></h1>
    </div>
    <div id="page-container" style="flex:1;display:flex;flex-direction:column;min-height:0"></div>
  </div>
`;

root.querySelector<HTMLAnchorElement>("#home-link")!.addEventListener("click", (e) => {
  e.preventDefault();
  navigate("/");
});

const pageContainer = root.querySelector<HTMLElement>("#page-container")!;

initRouter(pageContainer, [
  { pattern: "/", mount: mountLibrary },
  { pattern: "/doc/:id", mount: mountDocumentView },
  { pattern: "/doc/:id/chapter/:chapterId", mount: mountChapterView },
]);
