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
