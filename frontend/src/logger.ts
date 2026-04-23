/** Structured frontend logger with correlation ID support. */

let _activeCorrelationId: string | null = null;

export function generateCorrelationId(): string {
  const id = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  _activeCorrelationId = id;
  return id;
}

export function getCorrelationId(): string | null {
  return _activeCorrelationId;
}

export function clearCorrelationId(): void {
  _activeCorrelationId = null;
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
  const entry: LogEntry = {
    ts: new Date().toISOString(),
    level,
    component,
    msg,
    correlation_id: _activeCorrelationId,
    ...extra,
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
export function startTimer(component: string, msg: string): (extra?: Record<string, unknown>) => void {
  const t0 = performance.now();
  return (extra) => {
    const duration_ms = Math.round(performance.now() - t0);
    info(component, msg, { duration_ms, ...extra });
  };
}
