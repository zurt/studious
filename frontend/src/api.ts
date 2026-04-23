import { getCorrelationId, info, startTimer } from "./logger";

export type DocMeta = {
  id: string;
  name: string;
  source_type: "pdf" | "image";
  page_count: number;
  created_at: string;
  transcribed_pages?: number[];
};

export type Transcription = {
  page: number;
  engine: "ocr" | "vlm";
  provider: string;
  markdown: string;
  raw: string;
  prompt?: string;
  model?: string;
  meta?: Record<string, unknown>;
  duration_ms?: number;
  created_at?: string;
};

export type ProviderInfo = {
  name: string;
  kind: "ocr" | "vlm";
  default_config?: Record<string, unknown>;
  default_prompt?: string;
  models?: string[];
  unavailable?: string;
};

export type ProvidersResponse = {
  ocr: ProviderInfo[];
  vlm: ProviderInfo[];
  defaults: {
    ocr: string;
    vlm: string;
    vlm_model: string;
    vlm_prompt: string;
  };
};

function correlationHeaders(): Record<string, string> {
  const cid = getCorrelationId();
  return cid ? { "x-correlation-id": cid } : {};
}

async function jget<T>(url: string): Promise<T> {
  const done = startTimer("api", `GET ${url}`);
  const r = await fetch(url, { headers: correlationHeaders() });
  done({ status: r.status });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return (await r.json()) as T;
}

export async function listDocuments(): Promise<DocMeta[]> {
  return jget("/api/documents");
}

export async function getDocument(id: string): Promise<DocMeta> {
  return jget(`/api/documents/${id}`);
}

export async function uploadDocument(file: File): Promise<DocMeta> {
  const done = startTimer("api", "POST /api/documents (upload)");
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/documents", {
    method: "POST",
    body: fd,
    headers: correlationHeaders(),
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`upload failed: ${r.status} ${await r.text()}`);
  return (await r.json()) as DocMeta;
}

export function pageImageUrl(docId: string, page: number): string {
  return `/api/documents/${docId}/pages/${page}/image`;
}

export async function getTranscription(
  docId: string,
  page: number
): Promise<Transcription | null> {
  const r = await fetch(`/api/documents/${docId}/pages/${page}/transcription`, {
    headers: correlationHeaders(),
  });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`transcription fetch: ${r.status}`);
  return (await r.json()) as Transcription;
}

export async function getProviders(): Promise<ProvidersResponse> {
  return jget("/api/providers");
}

export type TranscribeRequest = {
  engine: "ocr" | "vlm";
  provider: string;
  pages: string;
  config: Record<string, unknown>;
  prompt?: string | null;
  overwrite?: boolean;
};

export async function submitTranscription(
  docId: string,
  body: TranscribeRequest
): Promise<{ job_id: string; pages: number[] }> {
  const done = startTimer("api", `POST /api/documents/${docId}/transcribe`);
  const r = await fetch(`/api/documents/${docId}/transcribe`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...correlationHeaders() },
    body: JSON.stringify(body),
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`transcribe submit: ${r.status} ${await r.text()}`);
  return await r.json();
}

export type JobEvent = {
  event:
    | "snapshot"
    | "job-started"
    | "page-started"
    | "page-done"
    | "page-skipped"
    | "page-error"
    | "job-done"
    | "job-failed"
    | "ping";
  data: any;
};

export function openJobStream(jobId: string, onEvent: (e: JobEvent) => void): () => void {
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  const types: JobEvent["event"][] = [
    "snapshot",
    "job-started",
    "page-started",
    "page-done",
    "page-skipped",
    "page-error",
    "job-done",
    "job-failed",
    "ping",
  ];
  for (const t of types) {
    es.addEventListener(t, (ev: MessageEvent) => {
      let data: any = ev.data;
      try {
        data = JSON.parse(ev.data);
      } catch {
        /* ignore */
      }
      onEvent({ event: t, data });
    });
  }
  es.onerror = () => {
    es.close();
  };
  return () => es.close();
}
