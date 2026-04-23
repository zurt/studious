import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { DocMeta, listDocuments, pageImageUrl, uploadDocument } from "../api";

export function Library() {
  const [docs, setDocs] = useState<DocMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    setLoading(true);
    try {
      setDocs(await listDocuments());
    } catch (e: any) {
      setError(String(e.message ?? e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onFileChosen(ev: React.ChangeEvent<HTMLInputElement>) {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await uploadDocument(file);
      await refresh();
    } catch (e: any) {
      setError(String(e.message ?? e));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="library">
      <div className="row" style={{ marginBottom: 16 }}>
        <button onClick={() => fileRef.current?.click()} disabled={uploading}>
          {uploading ? "Uploading…" : "Upload PDF or image"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp"
          style={{ display: "none" }}
          onChange={onFileChosen}
        />
        <span className="badge">{docs.length} document{docs.length === 1 ? "" : "s"}</span>
      </div>
      {error && <p className="error">{error}</p>}
      {loading ? (
        <p>Loading…</p>
      ) : docs.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>
          No documents yet. Upload a PDF or image to get started.
        </p>
      ) : (
        <div className="grid">
          {docs.map((d) => (
            <Link
              key={d.id}
              to={`/doc/${d.id}`}
              className="doc-card"
              style={{ color: "inherit", textDecoration: "none" }}
            >
              <img src={pageImageUrl(d.id, 1)} alt="" />
              <div className="name">{d.name}</div>
              <div className="meta">
                {d.source_type.toUpperCase()} · {d.page_count} page
                {d.page_count === 1 ? "" : "s"}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
