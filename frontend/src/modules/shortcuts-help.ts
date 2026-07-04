type Shortcut = { keys: string[]; desc: string };
type Group = { title: string; items: Shortcut[] };

const GROUPS: Group[] = [
  {
    title: "General",
    items: [
      { keys: ["?"], desc: "Show this help" },
      { keys: ["Esc"], desc: "Close modal, popover, or help" },
    ],
  },
  {
    title: "Document & chapter view",
    items: [
      { keys: ["←"], desc: "Previous page" },
      { keys: ["→"], desc: "Next page" },
    ],
  },
  {
    title: "Page viewer (zoom & pan)",
    items: [
      { keys: ["Trackpad pinch"], desc: "Zoom" },
      { keys: ["Two-finger scroll"], desc: "Pan" },
    ],
  },
  {
    title: "Study session",
    items: [
      { keys: ["Space"], desc: "Show answer" },
      { keys: ["1"], desc: "Grade: Again" },
      { keys: ["2"], desc: "Grade: Hard" },
      { keys: ["3"], desc: "Grade: Good" },
      { keys: ["4"], desc: "Grade: Easy" },
    ],
  },
  {
    title: "Dialogs",
    items: [
      { keys: ["Enter"], desc: "Confirm / submit" },
      { keys: ["Esc"], desc: "Cancel / close" },
    ],
  },
];

let activeOverlay: HTMLElement | null = null;

export function isShortcutsHelpOpen(): boolean {
  return activeOverlay !== null;
}

export function closeShortcutsHelp(): void {
  if (!activeOverlay) return;
  activeOverlay.remove();
  activeOverlay = null;
}

export function openShortcutsHelp(): void {
  if (activeOverlay) return;
  const bg = document.createElement("div");
  bg.className = "modal-bg shortcuts-help-bg";
  bg.innerHTML = `
    <div class="modal shortcuts-help" role="dialog" aria-label="Keyboard shortcuts">
      <div class="settings-header">
        <h2>Keyboard shortcuts</h2>
        <button class="icon-btn" id="shortcuts-help-close" title="Close" aria-label="Close">&#x2716;</button>
      </div>
      <div class="shortcuts-help-body">
        ${GROUPS.map(renderGroup).join("")}
      </div>
    </div>
  `;
  (document.fullscreenElement ?? document.body).appendChild(bg);

  bg.querySelector("#shortcuts-help-close")!.addEventListener("click", closeShortcutsHelp);
  bg.addEventListener("click", (e) => { if (e.target === bg) closeShortcutsHelp(); });

  activeOverlay = bg;
}

function renderGroup(g: Group): string {
  return `
    <section class="shortcuts-group">
      <h3>${escapeHtml(g.title)}</h3>
      <dl>
        ${g.items.map(renderItem).join("")}
      </dl>
    </section>
  `;
}

function renderItem(s: Shortcut): string {
  const keys = s.keys.map((k) => `<kbd>${escapeHtml(k)}</kbd>`).join('<span class="shortcut-plus">+</span>');
  return `<dt>${keys}</dt><dd>${escapeHtml(s.desc)}</dd>`;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]!));
}

export function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  return false;
}
