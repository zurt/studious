import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Transcription } from "../api";

type Props = {
  transcription: Transcription | null;
  busy?: boolean;
};

export function MarkdownPane({ transcription, busy }: Props) {
  if (busy && !transcription) {
    return <div className="empty">Transcribing…</div>;
  }
  if (!transcription) {
    return (
      <div className="empty">
        No transcription yet. Click <strong>Transcribe…</strong> in the toolbar.
      </div>
    );
  }
  return (
    <div className="markdown">
      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 8 }}>
        <span className="badge">
          {transcription.engine.toUpperCase()} · {transcription.provider}
          {transcription.model ? ` · ${transcription.model}` : ""}
        </span>
        {typeof transcription.duration_ms === "number" && (
          <span className="badge">{(transcription.duration_ms / 1000).toFixed(1)}s</span>
        )}
      </div>
      <div className="action-bar">
        <button disabled title="Coming soon">Furigana</button>
        <button disabled title="Coming soon">Vocabulary</button>
        <button disabled title="Coming soon">Translate / break down</button>
      </div>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{transcription.markdown}</ReactMarkdown>
    </div>
  );
}
