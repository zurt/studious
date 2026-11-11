export type ChooseOption = { value: string; label: string; hint?: string };

/** Modal radio-list picker; resolves the chosen value, or null on cancel. */
export function chooseDialog(
  title: string,
  message: string,
  options: ChooseOption[],
  confirmLabel = "OK",
): Promise<string | null> {
  return new Promise((resolve) => {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `
      <div class="modal" style="width: min(440px, 90vw)">
        <h2></h2>
        <p class="confirm-message"></p>
        <div class="choose-options"></div>
        <div class="row">
          <div class="grow"></div>
          <button id="choose-cancel">Cancel</button>
          <button id="choose-ok"></button>
        </div>
      </div>
    `;
    bg.querySelector("h2")!.textContent = title;
    bg.querySelector(".confirm-message")!.textContent = message;
    const list = bg.querySelector<HTMLElement>(".choose-options")!;
    options.forEach((opt, i) => {
      const label = document.createElement("label");
      label.className = "choose-option";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "choose-option";
      radio.value = opt.value;
      radio.checked = i === 0;
      const text = document.createElement("span");
      text.textContent = opt.label;
      label.append(radio, text);
      if (opt.hint) {
        const hint = document.createElement("span");
        hint.className = "choose-option-hint";
        hint.textContent = opt.hint;
        label.appendChild(hint);
      }
      list.appendChild(label);
    });
    const okBtn = bg.querySelector<HTMLButtonElement>("#choose-ok")!;
    okBtn.textContent = confirmLabel;
    (document.fullscreenElement ?? document.body).appendChild(bg);

    function chosen(): string | null {
      return bg.querySelector<HTMLInputElement>('input[name="choose-option"]:checked')?.value ?? null;
    }
    function close(result: string | null) {
      document.removeEventListener("keydown", onKey);
      bg.remove();
      resolve(result);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close(null);
      else if (e.key === "Enter") close(chosen());
    }

    bg.querySelector("#choose-cancel")!.addEventListener("click", () => close(null));
    okBtn.addEventListener("click", () => close(chosen()));
    bg.addEventListener("click", (e) => { if (e.target === bg) close(null); });
    document.addEventListener("keydown", onKey);
    setTimeout(() => okBtn.focus(), 0);
  });
}

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
    (document.fullscreenElement ?? document.body).appendChild(bg);

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
