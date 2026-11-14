#!/usr/bin/env node
// Screenshot helper: "show me page X in state Y" without a person at the
// browser. Boots the same throwaway stack `make dev-backend` uses (mock VLM,
// the seeded sample textbook, no key) on its own ports and data dir, opens
// each requested view in headless Chromium and writes a PNG per view.
//
//   make shot                              every named view
//   make shot SHOT="reading vocab"         some of them
//   make shot SHOT="reading --dark --mobile"
//   make shot SHOT="'/vocab?status=learning' --name vocab-learning"
//   make shot SHOT="chapter --click '#tracker-btn'"
//   make shot SHOT="--list"
//
// Run `node scripts/shot.mjs --help` (from frontend/) for every option.
// docs/screenshots.md is the longer guide.

import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { VIEWS, fillPath, parseArgs, slugify, usage } from "./shot-lib.mjs";

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BACKEND_DIR = path.resolve(FRONTEND_DIR, "../backend");

// Not the dev stack (8000/5173) and not the E2E suite (8775/5273): a shot
// can be taken while either is running.
const BACKEND_PORT = 8776;
const FRONTEND_PORT = 5274;
const DATA_DIR = ".shot-data";

// The same isolation as `make dev-backend`: no key, no WaniKani, Anki on a
// closed port, no background speech.
const BACKEND_ENV = {
  STUDIOUS_DATA_DIR: DATA_DIR,
  STUDIOUS_VLM_PROVIDER: "mock",
  ANTHROPIC_API_KEY: "",
  WANIKANI_API_TOKEN: "",
  ANKI_CONNECT_URL: "http://127.0.0.1:9",
  STUDIOUS_TTS_PREGENERATE: "0",
  STUDIOUS_LOG_LEVEL: "WARNING",
};

const children = [];

function start(command, args, opts) {
  const child = spawn(command, args, { ...opts, detached: true, stdio: ["ignore", "pipe", "pipe"] });
  let output = "";
  const keep = (chunk) => {
    output = (output + chunk).slice(-4000);
  };
  child.stdout.on("data", keep);
  child.stderr.on("data", keep);
  const record = { child, command, exited: false, output: () => output };
  child.on("exit", () => {
    record.exited = true;
  });
  children.push(record);
  return record;
}

function stopAll() {
  for (const { child, exited } of children) {
    if (exited || child.pid === undefined) continue;
    try {
      // The whole group: `uv run` and `npm run` both put the server in a child.
      process.kill(-child.pid, "SIGTERM");
    } catch {
      // already gone
    }
  }
}

function run(command, args, opts) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { ...opts, stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    child.stdout.on("data", (c) => {
      output += c;
    });
    child.stderr.on("data", (c) => {
      output += c;
    });
    child.on("error", reject);
    child.on("exit", (code) =>
      code === 0 ? resolve(output) : reject(new Error(`${command} ${args.join(" ")} exited ${code}\n${output}`)),
    );
  });
}

function portInUse(port) {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host: "127.0.0.1" });
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("error", () => resolve(false));
  });
}

async function waitForUrl(url, server, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (server.exited) throw new Error(`${server.command} exited before ${url} answered:\n${server.output()}`);
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`${url} did not answer within ${timeoutMs} ms:\n${server.output()}`);
}

/** Start the seeded mock stack; returns its base URL. */
async function startStack() {
  for (const port of [BACKEND_PORT, FRONTEND_PORT]) {
    if (await portInUse(port)) {
      throw new Error(`port ${port} is in use (an earlier shot run still going? lsof -i :${port})`);
    }
  }
  const env = { ...process.env, ...BACKEND_ENV };
  // A fresh seed every run, so a view looks the same whatever an earlier run
  // clicked. The seeder itself refuses to touch backend/data.
  fs.rmSync(path.join(BACKEND_DIR, DATA_DIR), { recursive: true, force: true });
  await run("uv", ["run", "python", "-m", "app.services.seed"], { cwd: BACKEND_DIR, env });

  const backend = start("uv", ["run", "uvicorn", "app.main:app", "--port", String(BACKEND_PORT)], {
    cwd: BACKEND_DIR,
    env,
  });
  const frontend = start("npm", ["run", "dev", "--", "--port", String(FRONTEND_PORT), "--strictPort"], {
    cwd: FRONTEND_DIR,
    env: { ...process.env, STUDIOUS_BACKEND_PORT: String(BACKEND_PORT) },
  });
  await waitForUrl(`http://127.0.0.1:${BACKEND_PORT}/api/health`, backend);
  const baseUrl = `http://localhost:${FRONTEND_PORT}`;
  await waitForUrl(baseUrl, frontend);
  return baseUrl;
}

/** The ids the `{doc}`, `{chapter1}`, `{region:tag}` placeholders stand for. */
async function loadContext(baseUrl) {
  const get = async (p) => {
    const res = await fetch(baseUrl + p);
    if (!res.ok) throw new Error(`GET ${p} -> ${res.status}`);
    return res.json();
  };
  const docs = await get("/api/documents");
  if (docs.length === 0) return { doc: null, chapters: [], regions: [] };
  const doc = docs[0].id;
  const chapters = await get(`/api/documents/${doc}/chapters`);
  const regions = [];
  for (const [index, ch] of chapters.entries()) {
    for (const r of await get(`/api/documents/${doc}/chapters/${ch.id}/regions`)) {
      regions.push({ id: r.id, tag: r.tag, page: r.page, chapter: index + 1 });
    }
  }
  return { doc, chapters: chapters.map((c) => c.id), regions };
}

async function launchBrowser() {
  const explicit = process.env.STUDIOUS_CHROMIUM_PATH;
  if (explicit) return chromium.launch({ executablePath: explicit });
  try {
    return await chromium.launch();
  } catch (err) {
    // Cloud sessions ship one Chromium that rarely matches the pinned
    // Playwright's revision, and cannot download another.
    const preinstalled = "/opt/pw-browsers/chromium";
    if (fs.existsSync(preinstalled)) return chromium.launch({ executablePath: preinstalled });
    throw new Error(
      `${String(err.message).split("\n")[0]}\n` +
        "No Chromium for this Playwright version. Run `npx playwright install chromium` in frontend/, " +
        "or set STUDIOUS_CHROMIUM_PATH to a Chromium binary.",
    );
  }
}

/** Wait until the page has stopped changing: network quiet, fonts and images in. */
async function settle(page) {
  // A page with an open job stream never goes idle; the cap keeps that from
  // failing the shot.
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page
    .evaluate(async () => {
      await document.fonts.ready;
      const pending = Array.from(document.images).filter((img) => !img.complete);
      await Promise.all(
        pending.map(
          (img) =>
            new Promise((resolve) => {
              img.addEventListener("load", resolve, { once: true });
              img.addEventListener("error", resolve, { once: true });
            }),
        ),
      );
    })
    .catch(() => {});
}

async function runStep(page, step) {
  if (step.kind === "click") await page.locator(step.value).first().click();
  else if (step.kind === "hover") await page.locator(step.value).first().hover();
  else if (step.kind === "press") await page.keyboard.press(step.value);
  else if (step.kind === "wait") await page.locator(step.value).first().waitFor({ state: "visible" });
  else if (step.kind === "fill") {
    const at = step.value.indexOf("=");
    await page.locator(step.value.slice(0, at)).first().fill(step.value.slice(at + 1));
  }
}

async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (err) {
    console.error(`shot: ${err.message}\n\n${usage()}`);
    return 2;
  }
  if (opts.help) {
    console.log(usage());
    return 0;
  }
  if (opts.list) {
    for (const [name, view] of Object.entries(VIEWS)) {
      console.log(`${name.padEnd(16)}${view.path.padEnd(52)}${view.about}`);
    }
    return 0;
  }

  const baseUrl = opts.baseUrl ?? (await startStack());
  const context = await loadContext(baseUrl);
  const targets = opts.targets.length > 0 ? opts.targets : Object.keys(VIEWS);
  const outDir = path.resolve(FRONTEND_DIR, opts.out);
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await launchBrowser();
  const browserContext = await browser.newContext({
    viewport: opts.viewport,
    deviceScaleFactor: opts.scale,
    colorScheme: opts.dark ? "dark" : "light",
    locale: "en-US",
    // A fixed clock would be better still; "reduce" at least stops a shot
    // from catching a transition halfway.
    reducedMotion: "reduce",
  });

  let failed = 0;
  for (const target of targets) {
    const view = VIEWS[target];
    const page = await browserContext.newPage();
    const problems = [];
    page.on("pageerror", (err) => problems.push(`page error: ${err.message}`));
    page.on("console", (msg) => {
      // A failed request is reported once, by the response handler below,
      // with its URL; the browser's own line for it has none.
      if (msg.type() === "error" && !msg.text().startsWith("Failed to load resource")) {
        problems.push(`console error: ${msg.text()}`);
      }
    });
    page.on("response", (res) => {
      if (res.status() >= 400) problems.push(`HTTP ${res.status()} ${res.url().replace(baseUrl, "")}`);
    });
    let name = target;
    try {
      const urlPath = fillPath(view ? view.path : target, context);
      name = opts.name && targets.length === 1 ? opts.name : view ? target : slugify(urlPath);
      const suffix = `${opts.dark ? "-dark" : ""}${opts.mobile ? "-mobile" : ""}`;
      const file = path.join(outDir, `${name}${suffix}.png`);

      await page.goto(baseUrl + urlPath);
      await settle(page);
      for (const step of [...(view?.steps ?? []), ...opts.steps]) {
        await runStep(page, step);
        await settle(page);
      }
      if (opts.selector) await page.locator(opts.selector).first().screenshot({ path: file });
      else await page.screenshot({ path: file, fullPage: opts.fullPage });
      console.log(`${path.relative(process.cwd(), file)}  <- ${urlPath}`);
    } catch (err) {
      failed += 1;
      console.error(`shot: ${name} failed: ${String(err.message).split("\n")[0]}`);
    }
    // What the page complained about is half the point of looking at it.
    for (const problem of [...new Set(problems)]) console.log(`    ${problem}`);
    await page.close();
  }
  await browser.close();
  return failed > 0 ? 1 : 0;
}

process.on("SIGINT", () => {
  stopAll();
  process.exit(130);
});
process.on("SIGTERM", () => {
  stopAll();
  process.exit(143);
});

main()
  .catch((err) => {
    console.error(`shot: ${err.message}`);
    return 1;
  })
  .then((code) => {
    stopAll();
    process.exit(code);
  });
