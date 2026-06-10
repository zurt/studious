import { generateCorrelationId, startTimer } from "./logger";

export type DocMeta = {
  id: string;
  name: string;
  source_type: "pdf" | "image";
  page_count: number;
  created_at: string;
  transcribed_pages?: number[];
  chapters?: Chapter[];
  regions_total?: number;
  regions_transcribed?: number;
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
  has_grammar_guide?: boolean;
};

export type GrammarGuideSection = { heading: string; body_md: string };
export type GrammarGuidePoint = {
  title: string;
  subtitle?: string;
  sections: GrammarGuideSection[];
};
export type GrammarGuideFingerprint = {
  region_id: string;
  transcribed_at?: string | null;
};
export type GrammarGuide = {
  chapter_id: string;
  model?: string;
  intro?: string;
  points: GrammarGuidePoint[];
  source_fingerprint: GrammarGuideFingerprint[];
  is_stale: boolean;
  created_at?: string;
  updated_at?: string;
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
  continues_to?: string | null;
  created_at: string;
};

export type BreakdownVocab = { word: string; reading?: string; meaning: string };
export type BreakdownGrammar = { pattern: string; explanation: string };
export type BreakdownLinkRef = { kind: "vocab" | "grammar"; index: number };
export type BreakdownLink = {
  start: number;
  end: number;
  kind: "vocab" | "grammar";
  index: number;
  match: "exact" | "stem" | "reading" | "llm";
  extras?: BreakdownLinkRef[];
};
export type BreakdownSentence = {
  text: string;
  gloss: string;
  vocab?: BreakdownVocab[];
  grammar?: BreakdownGrammar[];
  links?: BreakdownLink[];
};
export type Breakdown = {
  region_id: string;
  model?: string;
  sentences: BreakdownSentence[];
  created_at?: string;
  updated_at?: string;
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

async function jget<T>(url: string, cid: string = generateCorrelationId()): Promise<T> {
  const done = startTimer("api", `GET ${url}`, { correlation_id: cid });
  const r = await fetch(url, { headers: { "x-correlation-id": cid } });
  done({ status: r.status });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return (await r.json()) as T;
}

async function jpost<T>(url: string, body?: unknown, cid: string = generateCorrelationId()): Promise<T> {
  const done = startTimer("api", `POST ${url}`, { correlation_id: cid });
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-correlation-id": cid },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`${url}: ${r.status} ${await r.text()}`);
  return (await r.json()) as T;
}

async function jput<T>(url: string, body: unknown, cid: string = generateCorrelationId()): Promise<T> {
  const done = startTimer("api", `PUT ${url}`, { correlation_id: cid });
  const r = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "x-correlation-id": cid },
    body: JSON.stringify(body),
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`${url}: ${r.status} ${await r.text()}`);
  return (await r.json()) as T;
}

async function jdelete(url: string, cid: string = generateCorrelationId()): Promise<void> {
  const r = await fetch(url, { method: "DELETE", headers: { "x-correlation-id": cid } });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
}

// ---------- Documents ----------

export async function listDocuments(): Promise<DocMeta[]> {
  return jget("/api/documents");
}

export async function getDocument(id: string): Promise<DocMeta> {
  return jget(`/api/documents/${id}`);
}

export async function uploadDocument(file: File, cid: string = generateCorrelationId()): Promise<DocMeta> {
  const done = startTimer("api", "POST /api/documents (upload)", { correlation_id: cid });
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/documents", {
    method: "POST",
    body: fd,
    headers: { "x-correlation-id": cid },
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`upload failed: ${r.status} ${await r.text()}`);
  return (await r.json()) as DocMeta;
}

export async function reuploadDocument(docId: string, file: File, cid: string = generateCorrelationId()): Promise<DocMeta> {
  const done = startTimer("api", `PUT /api/documents/${docId}/file`, { correlation_id: cid });
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`/api/documents/${docId}/file`, {
    method: "PUT",
    body: fd,
    headers: { "x-correlation-id": cid },
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`reupload failed: ${r.status} ${await r.text()}`);
  return (await r.json()) as DocMeta;
}

export async function deleteDocument(docId: string, cid?: string): Promise<void> {
  return jdelete(`/api/documents/${docId}`, cid);
}

export function pageImageUrl(docId: string, page: number): string {
  return `/api/documents/${docId}/pages/${page}/image`;
}

export async function getTranscription(
  docId: string,
  page: number,
  cid: string = generateCorrelationId(),
): Promise<Transcription | null> {
  const r = await fetch(`/api/documents/${docId}/pages/${page}/transcription`, {
    headers: { "x-correlation-id": cid },
  });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`transcription fetch: ${r.status}`);
  return (await r.json()) as Transcription;
}

export async function getProviders(): Promise<ProvidersResponse> {
  return jget("/api/providers");
}

export type Preferences = {
  vlm_model: string;
  vlm_model_override: string | null;
  available_vlm_models: string[];
  default_vlm_model: string;
};

export async function getPreferences(): Promise<Preferences> {
  return jget("/api/preferences");
}

export async function updatePreferences(
  patch: { vlm_model?: string | null }
): Promise<Preferences> {
  return jput("/api/preferences", patch);
}

// ---------- Costs ----------

export type CostBucket = {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
};

export type CostSummary = {
  total_requests: number;
  success_count: number;
  error_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_estimated_cost_usd: number;
  by_model: Record<string, CostBucket>;
  by_doc: Record<string, CostBucket>;
  unknown_models: string[];
  first_timestamp: string | null;
  last_timestamp: string | null;
};

export async function getCostSummary(): Promise<CostSummary> {
  return jget("/api/costs/summary");
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

export async function getGrammarGuide(
  docId: string,
  chapterId: string,
  cid: string = generateCorrelationId(),
): Promise<GrammarGuide | null> {
  const r = await fetch(`/api/documents/${docId}/chapters/${chapterId}/grammar-guide`, {
    headers: { "x-correlation-id": cid },
  });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`grammar guide fetch: ${r.status}`);
  return (await r.json()) as GrammarGuide;
}

export async function requestGrammarGuide(
  docId: string,
  chapterId: string,
  opts: { overwrite?: boolean } = {},
  cid: string = generateCorrelationId(),
): Promise<{ job_id: string }> {
  const url = `/api/documents/${docId}/chapters/${chapterId}/grammar-guide`;
  const done = startTimer("api", `POST ${url}`, { correlation_id: cid });
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-correlation-id": cid },
    body: JSON.stringify({ overwrite: !!opts.overwrite }),
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`${url}: ${r.status} ${await r.text()}`);
  return (await r.json()) as { job_id: string };
}

export async function deleteGrammarGuide(
  docId: string,
  chapterId: string,
  cid?: string,
): Promise<void> {
  return jdelete(`/api/documents/${docId}/chapters/${chapterId}/grammar-guide`, cid);
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

export async function linkRegion(
  docId: string,
  chapterId: string,
  regionId: string,
  continuesTo: string | null,
): Promise<Region> {
  return jpost(
    `/api/documents/${docId}/chapters/${chapterId}/regions/${regionId}/link`,
    { continues_to: continuesTo },
  );
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

export async function getBreakdown(
  docId: string,
  chapterId: string,
  regionId: string,
  cid: string = generateCorrelationId(),
): Promise<Breakdown | null> {
  const r = await fetch(
    `/api/documents/${docId}/chapters/${chapterId}/regions/${regionId}/breakdown`,
    { headers: { "x-correlation-id": cid } },
  );
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`breakdown fetch: ${r.status}`);
  return (await r.json()) as Breakdown;
}

export async function requestBreakdown(
  docId: string,
  chapterId: string,
  regionId: string,
  opts: { overwrite?: boolean } = {},
  cid: string = generateCorrelationId(),
): Promise<{ job_id: string }> {
  const url = `/api/documents/${docId}/chapters/${chapterId}/regions/${regionId}/breakdown`;
  const done = startTimer("api", `POST ${url}`, { correlation_id: cid });
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-correlation-id": cid },
    body: JSON.stringify({ overwrite: !!opts.overwrite }),
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`${url}: ${r.status} ${await r.text()}`);
  return (await r.json()) as { job_id: string };
}

export type ExerciseCompletionExample = {
  japanese: string;
  reading: string;
  english: string;
  explanation: string;
};
export type ExerciseCompletionEntry = {
  answer: string;
  answer_english?: string;
  explanation?: string;
  examples: ExerciseCompletionExample[];
  model?: string;
  updated_at?: string;
};
export type ExerciseCompletion = {
  region_id: string;
  completions: Record<string, ExerciseCompletionEntry>;
  created_at?: string;
  updated_at?: string;
};

export async function getExerciseCompletion(
  docId: string,
  chapterId: string,
  regionId: string,
  cid: string = generateCorrelationId(),
): Promise<ExerciseCompletion | null> {
  const r = await fetch(
    `/api/documents/${docId}/chapters/${chapterId}/regions/${regionId}/exercise-completion`,
    { headers: { "x-correlation-id": cid } },
  );
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`exercise completion fetch: ${r.status}`);
  return (await r.json()) as ExerciseCompletion;
}

export async function requestExerciseCompletion(
  docId: string,
  chapterId: string,
  regionId: string,
  body: { sentence_index: number; overwrite?: boolean },
  cid: string = generateCorrelationId(),
): Promise<{ job_id: string }> {
  const url = `/api/documents/${docId}/chapters/${chapterId}/regions/${regionId}/exercise-completion`;
  const done = startTimer("api", `POST ${url}`, { correlation_id: cid });
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-correlation-id": cid },
    body: JSON.stringify({ sentence_index: body.sentence_index, overwrite: !!body.overwrite }),
  });
  done({ status: r.status });
  if (!r.ok) throw new Error(`${url}: ${r.status} ${await r.text()}`);
  return (await r.json()) as { job_id: string };
}

export async function transcribeRegion(
  docId: string,
  chapterId: string,
  regionId: string,
  cid?: string,
): Promise<{ job_id: string }> {
  return jpost(`/api/documents/${docId}/chapters/${chapterId}/regions/${regionId}/transcribe`, undefined, cid);
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
