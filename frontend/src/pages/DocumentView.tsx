import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  DocMeta,
  JobEvent,
  Transcription,
  getDocument,
  getTranscription,
  openJobStream,
  pageImageUrl,
  submitTranscription,
} from "../api";
import { MarkdownPane } from "../components/MarkdownPane";
import { TranscribePanel } from "../components/TranscribePanel";

type JobState = {
  jobId: string;
  pages: number[];
  current: number | null;
  done: number;
  errors: { page: number; message: string }[];
  status: "running" | "done" | "failed";
};

export function DocumentView() {
  const { id = "" } = useParams<{ id: string }>();
  const [doc, setDoc] = useState<DocMeta | null>(null);
  const [page, setPage] = useState<number>(1);
  const [transcription, setTranscription] = useState<Transcription | null>(null);
  const [showPanel, setShowPanel] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<JobState | null>(null);

  const refreshDoc = useCallback(async () => {
    try {
      setDoc(await getDocument(id));
    } catch (e: any) {
      setError(String(e.message ?? e));
    }
  }, [id]);

  const refreshTranscription = useCallback(async () => {
    try {
      setTranscription(await getTranscription(id, page));
    } catch (e: any) {
      setError(String(e.message ?? e));
    }
  }, [id, page]);

  useEffect(() => {
    refreshDoc();
  }, [refreshDoc]);

  useEffect(() => {
    refreshTranscription();
  }, [refreshTranscription]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLElement && ["INPUT", "TEXTAREA"].includes(e.target.tagName)) {
        return;
      }
      if (e.key === "ArrowLeft") setPage((p) => Math.max(1, p - 1));
      if (e.key === "ArrowRight") setPage((p) => (doc ? Math.min(doc.page_count, p + 1) : p));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doc]);

  function handleJobEvent(ev: JobEvent) {
    setJob((prev) => {
      if (!prev) return prev;
      switch (ev.event) {
        case "page-started":
          return { ...prev, current: ev.data.page };
        case "page-done":
          if (ev.data.page === page) refreshTranscription();
          return { ...prev, done: prev.done + 1 };
        case "page-skipped":
          return { ...prev, done: prev.done + 1 };
        case "page-error":
          return {
            ...prev,
            done: prev.done + 1,
            errors: [...prev.errors, { page: ev.data.page, message: ev.data.message }],
          };
        case "job-done":
          refreshDoc();
          refreshTranscription();
          return { ...prev, status: "done" };
        case "job-failed":
          return { ...prev, status: "failed" };
        default:
          return prev;
      }
    });
  }

  async function startJob(req: Parameters<typeof submitTranscription>[1]) {
    setShowPanel(false);
    setError(null);
    try {
      const { job_id, pages } = await submitTranscription(id, req);
      setJob({
        jobId: job_id,
        pages,
        current: pages[0] ?? null,
        done: 0,
        errors: [],
        status: "running",
      });
      const close = openJobStream(job_id, handleJobEvent);
      // Auto-close stream after job-done/failed; cleanup on unmount.
      const onUnload = () => close();
      window.addEventListener("beforeunload", onUnload);
      return () => {
        close();
        window.removeEventListener("beforeunload", onUnload);
      };
    } catch (e: any) {
      setError(String(e.message ?? e));
    }
  }

  if (!doc) return <p style={{ padding: 20 }}>Loading…</p>;

  return (
    <div className="viewer">
      <div className="topbar" style={{ borderBottom: "1px solid var(--border)" }}>
        <strong>{doc.name}</strong>
        <span className="badge">
          {doc.source_type.toUpperCase()} · {doc.page_count} pages
        </span>
        <div className="row">
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
            ←
          </button>
          <span>
            page {page} / {doc.page_count}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(doc.page_count, p + 1))}
            disabled={page >= doc.page_count}
          >
            →
          </button>
        </div>
        <div className="spacer" />
        <button onClick={() => setShowPanel(true)}>Transcribe…</button>
      </div>

      <div className="pane-row">
        <div className="pane left">
          <img className="page-img" src={pageImageUrl(doc.id, page)} alt={`page ${page}`} />
        </div>
        <div className="pane">
          <MarkdownPane
            transcription={transcription}
            busy={job?.status === "running" && job.current === page}
          />
        </div>
      </div>

      <div className="footer">
        {error && <span className="error">{error}</span>}
        {job && (
          <span>
            Job {job.jobId.slice(0, 6)} · {job.status}
            {job.status === "running" && job.current !== null
              ? ` · page ${job.current} (${job.done}/${job.pages.length})`
              : ""}
            {job.errors.length > 0 ? ` · ${job.errors.length} error(s)` : ""}
          </span>
        )}
        {!job && !error && <span>Use ← / → to flip pages.</span>}
      </div>

      {showPanel && (
        <TranscribePanel
          pageCount={doc.page_count}
          initialPages={String(page)}
          onClose={() => setShowPanel(false)}
          onSubmit={startJob}
        />
      )}
    </div>
  );
}
