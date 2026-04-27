export type Route = {
  pattern: string;
  mount: (params: Record<string, string>, container: HTMLElement) => void | (() => void);
};

type CompiledRoute = Route & {
  regex: RegExp;
  paramNames: string[];
};

let routes: CompiledRoute[] = [];
let currentCleanup: (() => void) | null = null;
let container: HTMLElement;

function compile(pattern: string): { regex: RegExp; paramNames: string[] } {
  const paramNames: string[] = [];
  const parts = pattern.split("/").map((part) => {
    if (part.startsWith(":")) {
      paramNames.push(part.slice(1));
      return "([^/]+)";
    }
    return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  });
  return { regex: new RegExp("^" + parts.join("/") + "$"), paramNames };
}

export function initRouter(el: HTMLElement, routeDefs: Route[]) {
  container = el;
  routes = routeDefs.map((r) => {
    const { regex, paramNames } = compile(r.pattern);
    return { ...r, regex, paramNames };
  });
  window.addEventListener("popstate", () => resolve());
  resolve();
}

export function navigate(path: string) {
  history.pushState(null, "", path);
  resolve();
}

function resolve() {
  const path = location.pathname;

  if (currentCleanup) {
    currentCleanup();
    currentCleanup = null;
  }
  container.innerHTML = "";

  for (const route of routes) {
    const match = path.match(route.regex);
    if (match) {
      const params: Record<string, string> = {};
      route.paramNames.forEach((name, i) => {
        params[name] = match[i + 1];
      });
      const cleanup = route.mount(params, container);
      if (cleanup) currentCleanup = cleanup;
      return;
    }
  }

  container.innerHTML = `<div class="library"><h2>Not found</h2><p><a href="/">Back to library</a></p></div>`;
}
