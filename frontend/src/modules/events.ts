// Minimal pub/sub event bus for syncing store state across views
// (docs/vocab-store-plan.md: status changes must reflect across the
// dashboard, breakdown pane, and chapter coverage without a reload).
import type { StoreKind, StoreStatus } from "../api";

type Handler = (payload: unknown) => void;

const handlers = new Map<string, Set<Handler>>();

export const STORE_STATUS_CHANGED = "store-status-changed";

export type StoreStatusChange = {
  kind: StoreKind;
  id: string;
  status: StoreStatus;
};

export function on<T>(event: string, fn: (payload: T) => void): () => void {
  let set = handlers.get(event);
  if (!set) {
    set = new Set();
    handlers.set(event, set);
  }
  set.add(fn as Handler);
  return () => {
    set!.delete(fn as Handler);
    if (set!.size === 0) handlers.delete(event);
  };
}

export function emit<T>(event: string, payload: T): void {
  const set = handlers.get(event);
  if (!set) return;
  for (const fn of [...set]) fn(payload);
}
