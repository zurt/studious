import { useEffect, useState } from "react";
import { ProvidersResponse, TranscribeRequest, getProviders } from "../api";

type Props = {
  pageCount: number;
  initialPages?: string;
  onClose: () => void;
  onSubmit: (req: TranscribeRequest) => void;
};

export function TranscribePanel({ pageCount, initialPages, onClose, onSubmit }: Props) {
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [engine, setEngine] = useState<"ocr" | "vlm">("vlm");
  const [ocrProvider, setOcrProvider] = useState<string>("tesseract");
  const [vlmProvider, setVlmProvider] = useState<string>("anthropic");
  const [model, setModel] = useState<string>("");
  const [prompt, setPrompt] = useState<string>("");
  const [allPages, setAllPages] = useState<boolean>(!initialPages);
  const [pages, setPages] = useState<string>(initialPages ?? "1");
  const [overwrite, setOverwrite] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProviders()
      .then((p) => {
        setProviders(p);
        setOcrProvider(p.defaults.ocr);
        setVlmProvider(p.defaults.vlm);
        setModel(p.defaults.vlm_model);
        setPrompt(p.defaults.vlm_prompt);
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  function submit() {
    setError(null);
    const effPages = allPages ? "all" : pages.trim() || "all";
    if (engine === "ocr") {
      onSubmit({
        engine: "ocr",
        provider: ocrProvider,
        pages: effPages,
        config: {},
        overwrite,
      });
    } else {
      onSubmit({
        engine: "vlm",
        provider: vlmProvider,
        pages: effPages,
        config: { model },
        prompt,
        overwrite,
      });
    }
  }

  const vlmInfo = providers?.vlm.find((p) => p.name === vlmProvider);
  const modelOptions = vlmInfo?.models ?? [];

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Transcribe</h2>
        {error && <p className="error">{error}</p>}

        <div className="row">
          <span style={{ fontSize: 12, color: "var(--muted)" }}>Engine:</span>
          <label>
            <input
              type="radio"
              name="engine"
              value="ocr"
              checked={engine === "ocr"}
              onChange={() => setEngine("ocr")}
            />{" "}
            OCR
          </label>
          <label>
            <input
              type="radio"
              name="engine"
              value="vlm"
              checked={engine === "vlm"}
              onChange={() => setEngine("vlm")}
            />{" "}
            VLM
          </label>
        </div>

        {engine === "ocr" ? (
          <div className="field">
            <label>OCR provider</label>
            <select value={ocrProvider} onChange={(e) => setOcrProvider(e.target.value)}>
              {providers?.ocr.map((p) => (
                <option key={p.name} value={p.name} disabled={!!p.unavailable}>
                  {p.name}
                  {p.unavailable ? " (unavailable)" : ""}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <>
            <div className="field">
              <label>VLM provider</label>
              <select value={vlmProvider} onChange={(e) => setVlmProvider(e.target.value)}>
                {providers?.vlm.map((p) => (
                  <option key={p.name} value={p.name} disabled={!!p.unavailable}>
                    {p.name}
                    {p.unavailable ? " (unavailable)" : ""}
                  </option>
                ))}
              </select>
            </div>
            {modelOptions.length > 0 && (
              <div className="field">
                <label>Model</label>
                <select value={model} onChange={(e) => setModel(e.target.value)}>
                  {modelOptions.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="field">
              <label>Prompt</label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                spellCheck={false}
              />
            </div>
          </>
        )}

        <div className="field">
          <label>Pages (of {pageCount})</label>
          <div className="row">
            <label>
              <input
                type="checkbox"
                checked={allPages}
                onChange={(e) => setAllPages(e.target.checked)}
              />{" "}
              All pages
            </label>
            <input
              className="grow"
              type="text"
              placeholder="e.g. 1-5, 8, 12-14"
              value={pages}
              onChange={(e) => setPages(e.target.value)}
              disabled={allPages}
            />
          </div>
        </div>

        <label className="row">
          <input
            type="checkbox"
            checked={overwrite}
            onChange={(e) => setOverwrite(e.target.checked)}
          />{" "}
          Overwrite existing transcriptions
        </label>

        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button onClick={onClose}>Cancel</button>
          <button onClick={submit} disabled={!providers}>
            Start
          </button>
        </div>
      </div>
    </div>
  );
}
