import { describe, it, expect, beforeEach, afterEach } from "vitest";
import {
  applyFurigana,
  createFuriganaToggle,
  cycleFuriganaMode,
  furiganaHtml,
  furiganaUnits,
  getFuriganaMode,
  initFurigana,
  setFuriganaMode,
  snapToUnits,
} from "../src/modules/furigana";

describe("furiganaUnits", () => {
  it("finds kanji runs followed by a hiragana reading", () => {
    const units = furiganaUnits("健康病(けんこうびょう)とは自分(じぶん)の言葉（ことば）で食(た)べる");
    expect(units.map((u) => [u.base, u.reading])).toEqual([
      ["健康病", "けんこうびょう"],
      ["自分", "じぶん"],
      ["言葉", "ことば"], // full-width parentheses too
      ["食", "た"],
    ]);
    expect(units[0]).toMatchObject({ start: 0, end: "健康病(けんこうびょう)".length });
  });

  it("ignores katakana labels, non-kanji bases, and non-kana contents", () => {
    expect(furiganaUnits("次の文(ア)を読む")).toEqual([]);
    expect(furiganaUnits("Aさん（あなた）")).toEqual([]);
    expect(furiganaUnits("（7行目）と (N3) と 問(1)")).toEqual([]);
  });
});

describe("furiganaHtml", () => {
  it("renders ruby with rp parentheses and escapes everything else", () => {
    const html = furiganaHtml("<b>無視(むし)する</b>");
    expect(html).toBe(
      '&lt;b&gt;<ruby class="furi">無視<rp>(</rp><rt>むし</rt><rp>)</rp></ruby>する&lt;/b&gt;',
    );
    // Text content is unchanged, so copy/paste and text assertions still see 漢字(かな).
    const div = document.createElement("div");
    div.innerHTML = html;
    expect(div.textContent).toBe("<b>無視(むし)する</b>");
  });

  it("handles empty input", () => {
    expect(furiganaHtml(null)).toBe("");
    expect(furiganaHtml("")).toBe("");
  });
});

describe("snapToUnits", () => {
  it("widens spans so no reading unit is split", () => {
    const text = "深酒(ふかざけ)をやめる。献身的(けんしんてき)な父";
    const units = furiganaUnits(text);
    // A vocab link on 深酒 (kanji only) grows to include its reading.
    expect(snapToUnits(units, 0, 2)).toEqual([0, "深酒(ふかざけ)".length]);
    // A link on 献身 inside 献身的(…) grows to the whole unit.
    const s = text.indexOf("献身的");
    expect(snapToUnits(units, s, s + 2)).toEqual([s, s + "献身的(けんしんてき)".length]);
    // Spans that don't touch a unit are unchanged.
    expect(snapToUnits(units, 9, 12)).toEqual([9, 12]);
  });
});

describe("applyFurigana", () => {
  it("converts text nodes but leaves code and existing ruby alone", () => {
    const root = document.createElement("div");
    root.innerHTML = "<p>心を惹(ひ)きつける</p><pre><code>惹(ひ)</code></pre>";
    applyFurigana(root);
    expect(root.querySelectorAll("ruby.furi")).toHaveLength(1);
    expect(root.querySelector("p ruby rt")!.textContent).toBe("ひ");
    expect(root.querySelector("code")!.textContent).toBe("惹(ひ)");
    applyFurigana(root); // idempotent
    expect(root.querySelectorAll("ruby.furi")).toHaveLength(1);
  });
});

describe("display mode", () => {
  beforeEach(() => { localStorage.clear(); });
  afterEach(() => { document.body.innerHTML = ""; });

  it("defaults to hidden and persists changes on <html>", () => {
    initFurigana();
    expect(getFuriganaMode()).toBe("hidden");
    expect(document.documentElement.dataset.furigana).toBe("hidden");
    setFuriganaMode("shown");
    expect(localStorage.getItem("studious.furigana.mode")).toBe("shown");
    expect(document.documentElement.dataset.furigana).toBe("shown");
    expect(cycleFuriganaMode()).toBe("off");
    expect(cycleFuriganaMode()).toBe("hidden");
  });

  it("toggle reflects and sets the mode across instances", () => {
    const a = createFuriganaToggle();
    const b = createFuriganaToggle();
    document.body.append(a, b);
    expect(a.querySelector(".active")!.textContent).toBe("Hide");
    b.querySelector<HTMLButtonElement>('[data-furigana-mode="shown"]')!.click();
    expect(getFuriganaMode()).toBe("shown");
    expect(a.querySelector(".active")!.textContent).toBe("Show");
    expect(a.querySelector('[data-furigana-mode="shown"]')!.getAttribute("aria-pressed")).toBe("true");
  });

  it("tapping a word reveals only that reading, and only in hidden mode", () => {
    initFurigana();
    setFuriganaMode("hidden");
    document.body.innerHTML = `<p>${furiganaHtml("健康(けんこう)と病気(びょうき)")}</p><div class="furi-reveal">けんこう</div>`;
    const [first, second] = document.querySelectorAll<HTMLElement>("ruby.furi");
    first.querySelector("rt")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(first.classList.contains("is-revealed")).toBe(true);
    expect(second.classList.contains("is-revealed")).toBe(false);
    first.click();
    expect(first.classList.contains("is-revealed")).toBe(false);

    const line = document.querySelector<HTMLElement>(".furi-reveal")!;
    line.click();
    expect(line.classList.contains("is-revealed")).toBe(true);

    setFuriganaMode("shown");
    second.click();
    expect(second.classList.contains("is-revealed")).toBe(false);
  });
});
