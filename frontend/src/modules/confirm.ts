export function confirmDialog(title: string, message: string, confirmLabel = "Delete"): Promise<boolean> {
  return new Promise((resolve) => {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `
      <div class="modal" style="width: min(400px, 90vw)">
        <h2></h2>
        <p class="confirm-message"></p>
        <div class="row">
          <div class="grow"></div>
          <button id="confirm-cancel">Cancel</button>
          <button id="confirm-ok" class="btn-danger"></button>
        </div>
      </div>
    `;
    bg.querySelector("h2")!.textContent = title;
    bg.querySelector(".confirm-message")!.textContent = message;
    const okBtn = bg.querySelector<HTMLButtonElement>("#confirm-ok")!;
    okBtn.textContent = confirmLabel;
    document.body.appendChild(bg);

    function close(result: boolean) {
      document.removeEventListener("keydown", onKey);
      bg.remove();
      resolve(result);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close(false);
      else if (e.key === "Enter") close(true);
    }

    bg.querySelector("#confirm-cancel")!.addEventListener("click", () => close(false));
    okBtn.addEventListener("click", () => close(true));
    bg.addEventListener("click", (e) => { if (e.target === bg) close(false); });
    document.addEventListener("keydown", onKey);
    setTimeout(() => okBtn.focus(), 0);
  });
}
