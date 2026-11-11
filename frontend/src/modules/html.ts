// The one HTML-escaping helper. Use it for every value interpolated into
// an innerHTML template, in text or attribute position.
//
// Nullish-safe: a missing field renders as "" rather than throwing, so one
// absent value can't take down a whole render pass.
export function escapeHtml(s: string | null | undefined): string {
  if (s == null) return "";
  return s
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
