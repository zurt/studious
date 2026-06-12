import { marked } from "marked";
import DOMPurify from "dompurify";

/**
 * Parse model-generated markdown to HTML and sanitize the result.
 *
 * VLM transcriptions and tool outputs are untrusted input, and `marked`
 * does not sanitize: raw HTML embedded in a transcription (script tags,
 * event-handler attributes, javascript: URLs) would execute when the
 * result is assigned to innerHTML. Render model markdown through this
 * helper instead of calling `marked.parse` directly.
 */
export function renderMarkdown(md: string): string {
  return DOMPurify.sanitize(marked.parse(md) as string);
}
