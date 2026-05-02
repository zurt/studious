import { getCorrelationId, startTimer } from "./logger";

export type DocMeta = {
  id: string;
  name: string;
  source_type: "pdf" | "image";
  page_count: number;
  created_at: string;
  transcribed_pages?: number[];
  chapters?: Chapter[];
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

export type Chapter = {
  id: string;
  doc_id: string;
  title: string;
  page_start: number;
  page_end: number;
  order: number;
  created_at: string;
  regions?: Region[];
};

export type Region = {
  id: string;
  chapter_id: string;
  page: number;
  bbox: [number, number, number, number];
  tag: string;
  label: string;
  transcription_md: string | null;
  transcribed_at?: string | null;
  transcribed_model?: string | null;
  created_at: string;
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

async function jpost<T>(url: string, body?: unknown): Promise<T> {
  const done = startTimer("api", `POST ${url}`);
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...correlationHeaders() },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`${url}: ${r.status} ${await r.text()}`);
  return (await r.json()) as T;
}

async function jput<T>(url: string, body: unknown): Promise<T> {
  const done = startTimer("api", `PUT ${url}`);
  const r = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...correlationHeaders() },
    body: JSON.stringify(body),
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`${url}: ${r.status} ${await r.text()}`);
  return (await r.json()) as T;
}

async function jdelete(url: string): Promise<void> {
  const r = await fetch(url, { method: "DELETE", headers: correlationHeaders() });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
}

// ---------- Documents ----------

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

export async function reuploadDocument(docId: string, file: File): Promise<DocMeta> {
  const done = startTimer("api", `PUT /api/documents/${docId}/file`);
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`/api/documents/${docId}/file`, {
    method: "PUT",
    body: fd,
    headers: correlationHeaders(),
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`reupload failed: ${r.status} ${await r.text()}`);
  return (await r.json()) as DocMeta;
}

export async function deleteDocument(docId: string): Promise<void> {
  return jdelete(`/api/documents/${docId}`);
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

// ---------- Chapters ----------

export async function createChapter(
  docId: string,
  body: { title: string; page_start: number; page_end: number; order?: number }
): Promise<Chapter> {
  return jpost(`/api/documents/${docId}/chapters`, body);
}

export async function listChapters(docId: string): Promise<Chapter[]> {
  return jget(`/api/documents/${docId}/chapters`);
}

export async function getChapter(docId: string, chapterId: string): Promise<Chapter> {
  return jget(`/api/documents/${docId}/chapters/${chapterId}`);
}

export async function updateChapter(
  docId: string,
  chapterId: string,
  body: Partial<Pick<Chapter, "title" | "page_start" | "page_end" | "order">>
): Promise<Chapter> {
  return jput(`/api/documents/${docId}/chapters/${chapterId}`, body);
}

export async function deleteChapter(docId: string, chapterId: string): Promise<void> {
  return jdelete(`/api/documents/${docId}/chapters/${chapterId}`);
}

// ---------- Regions ----------

export async function createRegion(
  docId: string,
  chapterId: string,
  body: { page: number; bbox: number[]; tag: string; label?: string }
): Promise<Region> {
  return jpost(`/api/documents/${docId}/chapters/${chapterId}/regions`, body);
}

export async function listRegions(docId: string, chapterId: string): Promise<Region[]> {
  return jget(`/api/documents/${docId}/chapters/${chapterId}/regions`);
}

export async function updateRegion(
  docId: string,
  chapterId: string,
  regionId: string,
  body: Partial<Pick<Region, "bbox" | "tag" | "label">>
): Promise<Region> {
  return jput(`/api/documents/${docId}/chapters/${chapterId}/regions/${regionId}`, body);
}

export async function deleteRegion(
  docId: string,
  chapterId: string,
  regionId: string
): Promise<void> {
  return jdelete(`/api/documents/${docId}/chapters/${chapterId}/regions/${regionId}`);
}

export async function moveRegion(
  docId: string,
  srcChapterId: string,
  regionId: string,
  dstChapterId: string,
): Promise<Region> {
  return jpost(
    `/api/documents/${docId}/chapters/${srcChapterId}/regions/${regionId}/move`,
    { dst_chapter_id: dstChapterId },
  );
}

export async function transcribeRegion(
  docId: string,
  chapterId: string,
  regionId: string
): Promise<{ job_id: string }> {
  return jpost(`/api/documents/${docId}/chapters/${chapterId}/regions/${regionId}/transcribe`);
}

// ---------- Transcription Jobs ----------

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
  return jpost(`/api/documents/${docId}/transcribe`, body);
}

export function openJobStream(jobId: string, onEvent: (e: JobEvent) => void): () => void {
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  const types: JobEvent["event"][] = [
    "snapshot", "job-started", "page-started", "page-done",
    "page-skipped", "page-error", "job-done", "job-failed", "ping",
  ];
  for (const t of types) {
    es.addEventListener(t, (ev: MessageEvent) => {
      let data: any = ev.data;
      try { data = JSON.parse(ev.data); } catch { /* ignore */ }
      onEvent({ event: t, data });
    });
  }
  es.onerror = () => es.close();
  return () => es.close();
}
