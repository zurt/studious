// jsdom in Node 20+ provides crypto.randomUUID via the global webcrypto. If
// missing, polyfill so logger.generateCorrelationId works.
import { webcrypto } from "node:crypto";

if (typeof globalThis.crypto === "undefined" || typeof globalThis.crypto.randomUUID !== "function") {
  // @ts-expect-error - assigning crypto for tests
  globalThis.crypto = webcrypto;
}

// jsdom doesn't ship a canvas backend. Stub getContext so region-drawer can
// run its draw routines without "Not implemented" warnings.
if (typeof HTMLCanvasElement !== "undefined") {
  HTMLCanvasElement.prototype.getContext = function () {
    return {
      clearRect() {},
      fillRect() {},
      strokeRect() {},
      fillText() {},
      setLineDash() {},
      save() {},
      restore() {},
      beginPath() {},
      closePath() {},
      moveTo() {},
      lineTo() {},
      stroke() {},
      fill() {},
      translate() {},
      scale() {},
      rotate() {},
      drawImage() {},
      set fillStyle(_v: string) {},
      set strokeStyle(_v: string) {},
      set lineWidth(_v: number) {},
      set font(_v: string) {},
    } as unknown as CanvasRenderingContext2D;
  } as unknown as HTMLCanvasElement["getContext"];
}
