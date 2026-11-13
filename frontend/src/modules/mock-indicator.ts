import { getProviders, type ProvidersResponse } from "../api";
import * as log from "../logger";

/** True when the backend's VLM provider is the canned mock (`make dev-backend`). */
export function isMockBackend(providers: ProvidersResponse): boolean {
  return providers.vlm.some((p) => p.mock === true);
}

/** Show `pill` (hidden by default) when the backend runs the mock VLM, so the
 * dev stack is never mistaken for the real one. A failed lookup leaves it
 * hidden: the indicator is advisory and must not break the app shell. */
export async function initMockIndicator(pill: HTMLElement): Promise<void> {
  try {
    const mock = isMockBackend(await getProviders());
    pill.hidden = !mock;
    if (mock) log.info("mock-indicator", "backend is running the mock VLM provider");
  } catch (err) {
    log.warn("mock-indicator", "provider lookup failed", { error: String(err) });
  }
}
