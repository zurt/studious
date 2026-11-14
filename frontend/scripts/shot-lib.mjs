// The pure half of the screenshot helper (shot.mjs): the named views, path
// placeholders and argument parsing. Kept apart so vitest can cover it
// without starting a browser or a server.

/**
 * Named views of the seeded sample textbook (backend/seed/textbook.json).
 * `path` may hold placeholders (see fillPath); `steps` run after the page
 * has settled, before the shot.
 */
export const VIEWS = {
  library: { path: "/", about: "document grid" },
  document: { path: "/doc/{doc}", about: "page viewer with chapter list" },
  chapter: { path: "/doc/{doc}/chapter/{chapter1}", about: "chapter 1, no region selected" },
  reading: {
    path: "/doc/{doc}/chapter/{chapter1}?page={page:reading_passage}&region={region:reading_passage}",
    about: "reading passage with its sentence breakdown",
  },
  "vocab-list": {
    path: "/doc/{doc}/chapter/{chapter1}?page={page:vocab_list}&region={region:vocab_list}",
    about: "transcribed vocab list region",
  },
  exercises: {
    path: "/doc/{doc}/chapter/{chapter1}?page={page:exercises}&region={region:exercises}",
    about: "exercise region with completions",
  },
  chapter2: { path: "/doc/{doc}/chapter/{chapter2}", about: "chapter 2: one region still untranscribed" },
  tracker: {
    path: "/doc/{doc}/chapter/{chapter2}",
    steps: [{ kind: "click", value: "#tracker-btn" }],
    about: "chapter 2 with the pending-regions popover open",
  },
  "grammar-guide": { path: "/doc/{doc}/chapter/{chapter1}/grammar-guide", about: "chapter 1 grammar guide" },
  vocab: { path: "/vocab", about: "vocab dashboard" },
  grammar: { path: "/grammar", about: "grammar dashboard" },
  study: { path: "/study", about: "flashcard session, first card" },
  answer: {
    path: "/study",
    steps: [{ kind: "click", value: "#srs-reveal" }],
    about: "flashcard with its answer and the grade buttons",
  },
  settings: { path: "/?settings=general", about: "settings modal, General" },
  usage: { path: "/?settings=usage", about: "settings modal, Usage" },
  shortcuts: { path: "/", steps: [{ kind: "press", value: "?" }], about: "keyboard shortcuts help" },
};

const STEP_FLAGS = { "--click": "click", "--hover": "hover", "--press": "press", "--wait": "wait", "--fill": "fill" };
const MOBILE = { width: 390, height: 844 };
const DESKTOP = { width: 1440, height: 900 };

export function usage() {
  return `usage: node scripts/shot.mjs [view|path ...] [options]

  view            a named view (--list shows them); none means all of them
  path            anything starting with "/", e.g. '/vocab?status=learning'.
                  Placeholders: {doc} {chapter1} {chapter2} {region:<tag>}
                  {page:<tag>} (first region with that tag; add :2 for
                  chapter 2, e.g. {region:vocab_list:2})

  --list          print the named views and exit
  --dark          dark colour scheme
  --mobile        390x844 viewport
  --viewport WxH  any other viewport (default 1440x900)
  --full-page     the whole scroll height, not just the viewport
  --selector SEL  shoot one element instead of the page
  --scale N       device scale factor (default 1; 2 for a shot a person reads)
  --name NAME     file name for a single target (default: the view name)
  --out DIR       output dir, relative to frontend/ (default: screenshots)
  --base-url URL  shoot a stack that is already running (e.g. the dev stack,
                  http://localhost:5173) instead of starting the seeded one

  Steps run in the order given, after the view's own, before the shot:
  --click SEL  --hover SEL  --press KEY  --wait SEL  --fill SEL=TEXT`;
}

export function parseViewport(value) {
  const match = /^(\d+)x(\d+)$/.exec(value);
  if (!match) throw new Error(`--viewport wants WIDTHxHEIGHT, got "${value}"`);
  return { width: Number(match[1]), height: Number(match[2]) };
}

export function parseArgs(argv) {
  const opts = {
    targets: [],
    steps: [],
    viewport: DESKTOP,
    mobile: false,
    dark: false,
    fullPage: false,
    selector: null,
    scale: 1,
    name: null,
    out: "screenshots",
    baseUrl: null,
    list: false,
    help: false,
  };
  const args = [...argv];
  const value = (flag) => {
    if (args.length === 0) throw new Error(`${flag} needs a value`);
    return args.shift();
  };
  while (args.length > 0) {
    const arg = args.shift();
    if (arg in STEP_FLAGS) {
      const step = { kind: STEP_FLAGS[arg], value: value(arg) };
      if (step.kind === "fill" && !step.value.includes("=")) throw new Error("--fill wants SELECTOR=TEXT");
      opts.steps.push(step);
    } else if (arg === "--list") opts.list = true;
    else if (arg === "--help" || arg === "-h") opts.help = true;
    else if (arg === "--dark") opts.dark = true;
    else if (arg === "--full-page") opts.fullPage = true;
    else if (arg === "--mobile") {
      opts.mobile = true;
      opts.viewport = MOBILE;
    } else if (arg === "--viewport") opts.viewport = parseViewport(value(arg));
    else if (arg === "--selector") opts.selector = value(arg);
    else if (arg === "--name") opts.name = value(arg);
    else if (arg === "--out") opts.out = value(arg);
    else if (arg === "--base-url") opts.baseUrl = value(arg).replace(/\/+$/, "");
    else if (arg === "--scale") {
      opts.scale = Number(value(arg));
      if (!(opts.scale > 0)) throw new Error("--scale wants a positive number");
    } else if (arg.startsWith("--")) throw new Error(`unknown option ${arg}`);
    else if (arg.startsWith("/") || arg in VIEWS) opts.targets.push(arg);
    else throw new Error(`unknown view "${arg}" (--list shows them; a path starts with "/")`);
  }
  if (opts.name && opts.targets.length !== 1) throw new Error("--name needs exactly one view or path");
  return opts;
}

/**
 * Replace `{doc}`, `{chapterN}`, `{region:tag[:chapter]}` and
 * `{page:tag[:chapter]}` with ids from `context`
 * ({ doc, chapters: [id], regions: [{ id, tag, page, chapter }] }).
 */
export function fillPath(template, context) {
  return template.replace(/\{([^}]+)\}/g, (_, token) => {
    const [kind, tag, chapterArg] = token.split(":");
    if (kind === "doc") {
      if (!context.doc) throw new Error("{doc}: the stack has no document");
      return context.doc;
    }
    const chapterMatch = /^chapter(\d+)$/.exec(kind);
    if (chapterMatch) {
      const id = context.chapters[Number(chapterMatch[1]) - 1];
      if (!id) throw new Error(`{${token}}: the document has ${context.chapters.length} chapter(s)`);
      return id;
    }
    if ((kind === "region" || kind === "page") && tag) {
      const chapter = chapterArg ? Number(chapterArg) : 1;
      const region = context.regions.find((r) => r.tag === tag && r.chapter === chapter);
      if (!region) throw new Error(`{${token}}: no ${tag} region in chapter ${chapter}`);
      return kind === "region" ? region.id : String(region.page);
    }
    throw new Error(`unknown placeholder {${token}}`);
  });
}

/** A file name for an ad-hoc path: "/vocab?status=learning" -> "vocab-status-learning". */
export function slugify(urlPath) {
  const slug = urlPath
    .replace(/[^A-Za-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return slug || "root";
}
