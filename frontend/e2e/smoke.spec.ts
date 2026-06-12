import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Smoke journeys against the real stack (vite + FastAPI) with the mock VLM
// provider and a fresh data dir per run (see playwright.config.ts).
//
// Tests run in source order on one worker and intentionally build on each
// other's state: the empty-state check must come before the upload, and the
// chapter test reuses the uploaded document.

const FIXTURE_PDF = path.join(__dirname, "fixtures", "sample.pdf");

test("library shows empty state on a fresh data dir", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
  await expect(page.locator("#doc-grid .empty")).toContainText("No documents yet");
});

test("uploading a PDF renders its pages in the document view", async ({ page }) => {
  await page.goto("/");
  await page.locator("#upload-input").setInputFiles(FIXTURE_PDF);

  // Upload navigates to /doc/:id once the backend has rendered pages.
  await page.waitForURL(/\/doc\/[0-9a-f]+$/, { timeout: 30_000 });
  await expect(page.locator("#doc-title")).toContainText("sample.pdf");
  await expect(page.locator("#page-info")).toHaveText("1 / 2");

  const pageImage = page.locator("#left-pane img");
  await expect(pageImage).toBeVisible();
  // The page PNG must actually load, not just be present in the DOM.
  await expect
    .poll(async () => pageImage.evaluate((el: HTMLImageElement) => el.naturalWidth))
    .toBeGreaterThan(0);

  await page.locator("#next-btn").click();
  await expect(page.locator("#page-info")).toHaveText("2 / 2");
});

test("creating a chapter opens the chapter view", async ({ page }) => {
  await page.goto("/");
  await page.locator("#doc-grid .doc-card").first().click();
  await page.waitForURL(/\/doc\/[0-9a-f]+$/);

  await page.locator("#new-chapter-btn").click();
  await page.locator("#ch-title").fill("第1課 テスト");
  await page.locator("#ch-start").fill("1");
  await page.locator("#ch-end").fill("2");
  await page.locator("#ch-save").click();

  // Creating a chapter navigates straight into its chapter view.
  await page.waitForURL(/\/doc\/[0-9a-f]+\/chapter\/[0-9a-f]+/);
  await expect(page.locator("#chapter-title")).toContainText("第1課 テスト");
  await expect(page.locator("#page-info")).toContainText("1");

  // Back in the document view, page 1 now sits inside the chapter's range,
  // so the banner linking back to the chapter appears.
  await page.locator("#back-link").click();
  await expect(page.locator("#chapter-banner")).toContainText("第1課 テスト");
});

test("drawing a region and transcribing it renders mock markdown", async ({ page }) => {
  // Reach the chapter view created by the previous test via the banner link.
  await page.goto("/");
  await page.locator("#doc-grid .doc-card").first().click();
  await page.locator("#banner-link").click();
  await page.waitForURL(/\/doc\/[0-9a-f]+\/chapter\/[0-9a-f]+/);

  // The drawer overlays a canvas on the page image once it loads.
  const canvas = page.locator("#left-pane canvas");
  await expect(canvas).toBeVisible();
  const box = (await canvas.boundingBox())!;

  // Drag a box well above the drawer's 2%-of-canvas minimum size.
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.55, { steps: 5 });
  await page.mouse.up();

  // Tag the new region in the popover.
  await page.locator("#tag-select").selectOption("reading_passage");
  await page.locator("#region-label").fill("本文");
  await page.locator("#tag-save").click();

  const card = page.locator(".region-card");
  await expect(card).toHaveCount(1);
  await expect(card.locator(".badge")).toHaveClass(/tag-reading_passage/);

  // Transcribe via the mock provider; the job stream flips the card state
  // and the detail pane renders the canned markdown.
  await card.getByRole("button", { name: "Transcribe" }).click();
  await expect(page.locator("#region-detail")).toContainText("Mock transcription", {
    timeout: 15_000,
  });
  await expect(page.locator("#region-detail")).toContainText("私(わたし)は日本語(にほんご)を");
});

test("generating a sentence breakdown renders cards and vocab/grammar popovers", async ({ page }) => {
  await page.goto("/");
  await page.locator("#doc-grid .doc-card").first().click();
  await page.locator("#banner-link").click();
  await page.waitForURL(/\/doc\/[0-9a-f]+\/chapter\/[0-9a-f]+/);

  // The chapter view auto-selects the page's first region on load, so the
  // breakdown pane mounts in its empty state for the transcribed region.
  const pane = page.locator("#breakdown-pane");
  await expect(pane).toContainText("No breakdown yet");

  await pane.locator("#bd-generate").click();
  const card = pane.locator(".breakdown-card");
  await expect(card).toHaveCount(1, { timeout: 15_000 });
  await expect(card.locator(".breakdown-text")).toContainText(
    "私(わたし)は日本語(にほんご)を勉強(べんきょう)しています。",
  );

  // The backend annotates vocab/grammar spans as inline links; clicking one
  // opens the popover with the matching entry.
  const popover = page.locator(".bd-link-popover");
  await card.locator(".bd-link", { hasText: "日本語" }).click();
  await expect(popover).toBeVisible();
  await expect(popover.locator(".bd-popover-word")).toHaveText("日本語");
  await expect(popover).toContainText("Japanese language");

  // Clicking a grammar link swaps the popover to the grammar entry.
  await card.locator(".bd-link", { hasText: "しています" }).click();
  await expect(popover.locator(".bd-popover-pattern")).toHaveText("〜ている");
  await expect(popover).toContainText("Ongoing action or continuing state.");

  await page.keyboard.press("Escape");
  await expect(popover).toBeHidden();

  // The gloss starts blurred; its toggle reveals the translation.
  await card.locator("[data-gloss-toggle]").click();
  await expect(card.locator(".breakdown-gloss")).not.toHaveClass(/is-blurred/);
  await expect(card.locator(".breakdown-gloss")).toHaveText("I am studying Japanese.");
});

test("a transcribed grammar_points region powers grammar guide generation", async ({ page }) => {
  await page.goto("/");
  await page.locator("#doc-grid .doc-card").first().click();
  await page.locator("#banner-link").click();
  await page.waitForURL(/\/doc\/[0-9a-f]+\/chapter\/[0-9a-f]+/);

  // No grammar_points regions yet, so the topbar button stays hidden.
  const guideBtn = page.locator("#grammar-guide-btn");
  await expect(guideBtn).toBeHidden();

  const canvas = page.locator("#left-pane canvas");
  await expect(canvas).toBeVisible();
  const box = (await canvas.boundingBox())!;

  // Draw to the right of the reading-passage region from the earlier
  // journey: a mousedown inside an existing bbox selects that region instead
  // of drawing, and the fit-width canvas extends below the viewport, so the
  // drag must stay in the visible upper area.
  await page.mouse.move(box.x + box.width * 0.75, box.y + box.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.95, box.y + box.height * 0.5, { steps: 5 });
  await page.mouse.up();

  await page.locator("#tag-select").selectOption("grammar_points");
  await page.locator("#region-label").fill("文法");
  await page.locator("#tag-save").click();

  // The button appears but stays disabled until the region is transcribed.
  await expect(guideBtn).toBeVisible();
  await expect(guideBtn).toHaveAttribute("aria-disabled", "true");

  const grammarCard = page.locator(".region-card", { hasText: "文法" });
  await grammarCard.getByRole("button", { name: "Transcribe" }).click();
  await expect(guideBtn).toHaveText("Generate grammar guide", { timeout: 15_000 });

  // Generation navigates into the guide page once the job completes.
  await guideBtn.click();
  await page.waitForURL(/\/grammar-guide$/, { timeout: 15_000 });
  await expect(page.locator("#gg-title")).toContainText("Grammar Guide");
  const body = page.locator("#gg-body");
  await expect(body).toContainText("Mock grammar guide for E2E runs.");
  await expect(body).toContainText("〜ている");
  await expect(body).toContainText("Meaning");

  // Back on the chapter, the same button now opens the stored guide.
  await page.locator("#back-link").click();
  await expect(guideBtn).toHaveText("Open grammar guide");
});
