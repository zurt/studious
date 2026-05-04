/** Structured frontend logger with correlation ID support.
 *
 * Correlation IDs are per-request: each call to `generateCorrelationId()`
 * returns a fresh id. Pages that want to bind several related calls together
 * (e.g. a batch transcribe loop) should generate one CID up front and pass
 * it to each `jget`/`jpost`/etc. call, plus to any `info`/`warn`/`error`
 * log lines that should be attributed to the same trace.
 */

export function generateCorrelationId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
}

type LogEntry = {
  ts: string;
  level: string;
  component: string;
  msg: string;
  correlation_id: string | null;
  duration_ms?: number;
  [key: string]: unknown;
};

function emit(level: string, component: string, msg: string, extra?: Record<string, unknown>) {
  const cid = (extra && typeof extra.correlation_id === "string") ? extra.correlation_id : null;
  const rest = extra ? { ...extra } : {};
  delete (rest as any).correlation_id;
  const entry: LogEntry = {
    ts: new Date().toISOString(),
    level,
    component,
    msg,
    correlation_id: cid,
    ...rest,
  };
  if (level === "error") {
    console.error("[studious]", JSON.stringify(entry));
  } else if (level === "warn") {
    console.warn("[studious]", JSON.stringify(entry));
  } else {
    console.log("[studious]", JSON.stringify(entry));
  }
}

export function info(component: string, msg: string, extra?: Record<string, unknown>) {
  emit("info", component, msg, extra);
}

export function warn(component: string, msg: string, extra?: Record<string, unknown>) {
  emit("warn", component, msg, extra);
}

export function error(component: string, msg: string, extra?: Record<string, unknown>) {
  emit("error", component, msg, extra);
}

/** Returns a function that, when called, logs the elapsed time. */
export function startTimer(
  component: string,
  msg: string,
  baseExtra?: Record<string, unknown>,
): (extra?: Record<string, unknown>) => void {
  const t0 = performance.now();
  return (extra) => {
    const duration_ms = Math.round(performance.now() - t0);
    info(component, msg, { duration_ms, ...baseExtra, ...extra });
  };
}
