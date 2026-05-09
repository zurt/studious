import { describe, it, expect, beforeEach, vi } from "vitest";
import { initRouter, navigate, replaceQuery } from "../src/router";

function setPath(path: string) {
  history.replaceState(null, "", path);
}

describe("router", () => {
  beforeEach(() => {
    setPath("/");
    document.body.innerHTML = "";
  });

  it("matches a literal path and renders mount output", () => {
    const container = document.createElement("div");
    const home = vi.fn(() => {
      container.appendChild(document.createTextNode("home"));
    });
    setPath("/");
    initRouter(container, [{ pattern: "/", mount: home }]);
    expect(home).toHaveBeenCalledTimes(1);
    expect(container.textContent).toBe("home");
  });

  it("extracts named params from the path", () => {
    const container = document.createElement("div");
    const detail = vi.fn();
    setPath("/doc/abc123");
    initRouter(container, [
      { pattern: "/doc/:id", mount: detail },
      { pattern: "/", mount: vi.fn() },
    ]);
    expect(detail).toHaveBeenCalledTimes(1);
    const params = detail.mock.calls[0]![0];
    expect(params).toEqual({ id: "abc123" });
  });

  it("extracts multiple params and respects literal segments", () => {
    const container = document.createElement("div");
    const handler = vi.fn();
    setPath("/doc/d1/chapter/c2");
    initRouter(container, [
      { pattern: "/doc/:doc/chapter/:chapter", mount: handler },
    ]);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0]![0]).toEqual({ doc: "d1", chapter: "c2" });
  });

  it("renders a not-found view when no route matches", () => {
    const container = document.createElement("div");
    setPath("/no-such-route");
    initRouter(container, [{ pattern: "/", mount: vi.fn() }]);
    expect(container.textContent).toContain("Not found");
  });

  it("navigate updates location.pathname and dispatches the new route", () => {
    const container = document.createElement("div");
    const home = vi.fn();
    const detail = vi.fn();
    setPath("/");
    initRouter(container, [
      { pattern: "/", mount: home },
      { pattern: "/doc/:id", mount: detail },
    ]);
    home.mockClear();
    navigate("/doc/xyz");
    expect(location.pathname).toBe("/doc/xyz");
    expect(detail).toHaveBeenCalledTimes(1);
    expect(detail.mock.calls[0]![0]).toEqual({ id: "xyz" });
  });

  it("calls cleanup returned by previous mount before navigating", () => {
    const container = document.createElement("div");
    const cleanup = vi.fn();
    const first = vi.fn(() => cleanup);
    const second = vi.fn();
    setPath("/a");
    initRouter(container, [
      { pattern: "/a", mount: first },
      { pattern: "/b", mount: second },
    ]);
    expect(cleanup).not.toHaveBeenCalled();
    navigate("/b");
    expect(cleanup).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalled();
  });

  it("replaceQuery preserves the path and updates query params", () => {
    const container = document.createElement("div");
    setPath("/doc/d1?keep=1&drop=x");
    initRouter(container, [{ pattern: "/doc/:id", mount: vi.fn() }]);
    replaceQuery({ drop: null, add: "v" });
    expect(location.pathname).toBe("/doc/d1");
    const search = new URLSearchParams(location.search);
    expect(search.get("keep")).toBe("1");
    expect(search.get("drop")).toBeNull();
    expect(search.get("add")).toBe("v");
  });

  it("replaceQuery with empty string removes the param", () => {
    const container = document.createElement("div");
    setPath("/?x=1");
    initRouter(container, [{ pattern: "/", mount: vi.fn() }]);
    replaceQuery({ x: "" });
    expect(location.search).toBe("");
  });
});
