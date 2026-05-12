from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


DEFAULT_VLM_PROMPT = """\
You are an expert OCR transcriber specializing in Japanese textbooks
for English speakers. The image is a single page that mixes Japanese
(kanji, hiragana, katakana, possibly with furigana) and English.

<task>
Transcribe the page into clean Markdown. Preserve the original reading
order — top-to-bottom for horizontal text, right-to-left and
top-to-bottom for vertical text. Preserve paragraph breaks. Convert
visual structure to Markdown semantics:
- Headings (chapter/section titles) → # / ## / ###
- Bold or boxed terms → **bold**
- Vocabulary lists or dialogue turns → bulleted or numbered lists
- Tables (conjugation charts, vocab tables) → Markdown tables
- Furigana (small kana annotating a kanji's reading, appearing
  either above or below the word) → inline parens immediately
  after the kanji, e.g. 食(た)べる. Capture furigana whether it
  appears above or below the line.
- Example sentences and their translations → keep on adjacent lines
</task>

<rules>
- Transcribe Japanese exactly as printed. Do not "correct" spelling,
  punctuation (including 、 and 。), or kana/kanji choices.
- Transcribe English exactly as printed.
- Ignore decorative underlines (e.g. dotted underlines marking
  textbook grammar points). Transcribe the underlined text as plain
  text — do not emit <u>…</u> tags.
- Ignore body-text line numbers in the page margin (e.g. small "5",
  "10", "15" markers every Nth line). Do not include them in the
  transcription.
- If a character or word is unclear, write [?] in its place. Do not
  guess.
- If a region is too blurry, illegible, or cut off to read, write
  [illegible] and continue.
- Do not add commentary, translations, or explanations that are not
  on the page.
- Do not summarize. Output the full page text.
</rules>

<output_format>
Return only the Markdown transcription, with no preamble or closing
remarks. Begin directly with the first line of the page.
</output_format>
"""


REGION_TRANSCRIBE_PROMPT = """\
You are an expert OCR transcriber specializing in Japanese textbooks
for English speakers. The image is a selected region from a single
page — it may be a passage, vocabulary list, table, or other element.

<task>
Transcribe the region into clean Markdown. Preserve the original
reading order — top-to-bottom for horizontal text, right-to-left and
top-to-bottom for vertical text — and preserve paragraph breaks. Use
Markdown lists for enumerations and tables for tabular content.
Render furigana inline with parens, e.g. 食(た)べる; capture furigana
whether it appears above or below the word. Do not invent a heading
if the region has no title.
</task>

<rules>
- Transcribe Japanese and English exactly as printed. Do not
  "correct" spelling, punctuation (including 、 and 。), or
  kana/kanji choices.
- Ignore decorative underlines (e.g. dotted underlines marking
  textbook grammar points). Transcribe the underlined text as
  plain text — do not emit <u>…</u> tags.
- Ignore body-text line numbers in the page margin (e.g. small
  "5", "10", "15" markers every Nth line). Do not include them.
- If a character or word is unclear, write [?]. If part of the region
  is illegible or cut off, write [illegible] and continue.
- Do not add commentary or translations that are not on the page.
</rules>

<output_format>
Return only the Markdown transcription, with no preamble or closing
remarks.
</output_format>
"""


VOCAB_LIST_TRANSCRIBE_PROMPT = """\
You are an expert OCR transcriber specializing in Japanese textbook
vocabulary lists for English speakers. The image is a selected region
containing a vocabulary list, possibly with section headers and item
indices that tie entries back to a reading passage.

<task>
Transcribe the region into clean Markdown, one vocabulary entry per
line, in the order printed. Never use bulleted or numbered lists —
do not prefix entries with `- `, `*`, or `1.`. Each entry MUST end
with two trailing spaces followed by a newline (standard Markdown
hard line break) so entries render on separate lines.

Entry format:
- With kanji + reading: `term（reading）gloss1; gloss2`
- Kana-only or expression with no separate reading: `term　gloss1; gloss2`

Use full-width parentheses （ ） for the reading. When a reading is
present, the English gloss MUST butt directly against the closing
`）` with no space, full-width space, or any other character between
them. When there is no reading, separate the term from the gloss
with a single full-width ideographic space 　 (U+3000). Separate
multiple English senses with `; `.

Preserve item indices exactly as printed at the start of the line:
plain numbers (`1`, `2`), parenthesized labels (`(1)`, `(4)`),
or section labels like `（前文）`. Keep them on the same line as
the entry.

Preserve section headers verbatim on their own line, including any
decorative characters and page references — for example:
`【📖】読む前に（p. 28）`, `■ 内容を確認しよう（p. 31）`,
`1．（p. 33）`.
</task>

<rules>
- Transcribe Japanese exactly as printed. Do not "correct" spelling,
  punctuation, or kana/kanji choices.
- For English glosses: if the textbook prints a gloss next to the
  entry, transcribe it exactly. If no gloss is printed, supply a
  short dictionary-style English translation (one or two senses,
  separated by `; `). Do not invent example sentences or
  part-of-speech tags that are not on the page.
- Entries with no kanji (e.g. `〜によって`, `〜カ国`) have no reading
  column — emit just `term　gloss`.
- Ignore decorative underlines and body-text line numbers in the
  page margin. Do not emit <u>…</u> tags.
- If a character is unclear, write [?]. If part of the region is
  illegible or cut off, write [illegible] and continue.
- Do not add commentary outside the entries themselves.
</rules>

<output_format>
Return only the Markdown transcription, with no preamble or closing
remarks. One entry per line, ending each entry with two trailing
spaces before the newline; blank line between sections. Never emit
bulleted or numbered list markers.
</output_format>
"""


SENTENCE_BREAKDOWN_PROMPT = """\
You are a Japanese-language tutor for English-speaking learners. The
input is the already-transcribed text of a single region from a
Japanese textbook (a reading passage, grammar example, exercise,
instruction block, etc.).

<task>
Produce a sentence-by-sentence study breakdown of the input. Split
the input into natural sentences using Japanese sentence-ending
punctuation (。！？) or, for non-narrative content, into individual
items, headings, or example lines as they appear. For markdown
tables: treat the entire table as a single entry unless one or more
cells contain sentence-ending punctuation (。！？), in which case
split at those sentence boundaries (one entry per sentence, spanning
whatever cells are needed). For each sentence or item, return:
- text: the original Japanese sentence, copied verbatim from the
  input. Preserve furigana already written inline as 漢字(かな).
- vocab: notable vocabulary entries that an intermediate learner
  would benefit from looking up. Include word, reading (kana), and
  a short English meaning. Skip trivial particles and basic
  function words.
- grammar: grammar patterns demonstrated by the sentence. Give the
  pattern (e.g. "～を主人公に", "～てしまう"), a short English
  explanation of when/why it is used, and `surfaces`: a non-empty
  list of literal substrings copied verbatim from `text` that
  anchor the pattern in this sentence.
  Surface rules:
  - Each surface must appear in `text` exactly as written; do not
    paraphrase, romanize, or substitute kana for kanji.
  - Include only the particles, suffixes, or fixed surface chars
    of the pattern itself — not the content words that fill the
    placeholders and not characters between anchors.
  - Single-anchor patterns get one surface. `〜ます` → `["ます"]`.
    `〜ている` → `["ている"]` (or `["てる"]` if that's what's in
    the sentence). `〜てください` → `["てください"]`.
  - Range or pair patterns with two anchors (`〜から〜まで`,
    `〜ば〜ほど`, `〜たり〜たり`, `〜も〜も`) get two surfaces, one
    per anchor — `["から", "まで"]`, never a single span bridging
    them.
  - Omit the leading/trailing `〜` placeholder marker from each
    surface — it is not in `text`.
- gloss: a concise, natural English translation of the full
  sentence.
</task>

<rules>
- Copy the Japanese text exactly. Do not "correct" the original.
- Do not invent vocabulary or grammar that is not in the sentence.
- For purely English content, leave vocab and grammar empty and
  echo the line in both `text` and `gloss`.
- If the input contains no parseable sentence (e.g. a heading or
  pure-numbers line), still return one entry with the line as `text`
  and a brief `gloss` describing it.
</rules>

Call the `record_breakdown` tool with your result. Do not return
prose; return only the tool call.
"""


GRAMMAR_GUIDE_PROMPT = """\
You are helping an English-speaking learner study Japanese grammar. The
input is a concatenation of all transcribed grammar-point regions from a
single chapter of a Japanese textbook. Different regions are separated by
`---`.

<task>
Read through these grammar points from the textbook. Make a concise study
guide in a mix of Japanese and English for the grammar points in this
chapter. Keep it simple and direct. Provide related grammar and
expressions where appropriate (both to group related patterns and to
disambiguate). Include a few short, clear examples.
</task>

<structure>
- `intro`: optional one- or two-sentence orientation for the chapter
  (markdown).
- `points`: one entry per grammar point in the chapter, in the order
  they appear. For each point:
  - `title`: the Japanese pattern itself, e.g. "〜ばかりで",
    "このように見てみると／考えると、〜ということになる". Use 〜 as a
    placeholder where the textbook does.
  - `subtitle` (optional): a short English label naming the function
    (e.g. "Soft speculation / proposal", "Logical conclusion").
  - `sections`: an ordered list of titled markdown blocks. Typical
    headings are `Meaning`, `Form`, `Nuance`, `Pattern`, `Examples`,
    `Variations`, `Related`. Adapt the set to what each grammar point
    actually needs — do not invent content, but do regroup the
    textbook's information into these clearer buckets. Each section's
    `body_md` is GitHub-flavored markdown; use bullet lists for forms,
    pair Japanese example sentences with their English translation on
    the next line, and write related/contrasting patterns as bullets
    with a short English gloss in parentheses.
</structure>

<rules>
- Cover every distinct grammar point in the input, in input order.
- Do not invent grammar that is not in the input. You may add a small
  number of related patterns under `Related` when they help group or
  disambiguate; mark them clearly.
- Keep examples short (one line of Japanese, one line of English).
- Do not include a chapter heading; the renderer adds one.
- Do not return prose. Call the `record_grammar_guide` tool with the
  structured result.
</rules>
"""


GRAMMAR_GUIDE_TOOL_SCHEMA: dict = {
    "type": "object",
    "required": ["points"],
    "properties": {
        "intro": {"type": "string"},
        "points": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["title", "sections"],
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "subtitle": {"type": "string"},
                    "sections": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["heading", "body_md"],
                            "properties": {
                                "heading": {"type": "string", "minLength": 1},
                                "body_md": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                },
            },
        },
    },
}


BREAKDOWN_TOOL_SCHEMA: dict = {
    "type": "object",
    "required": ["sentences"],
    "properties": {
        "sentences": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["text", "gloss"],
                "properties": {
                    "text": {"type": "string"},
                    "gloss": {"type": "string"},
                    "vocab": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["word", "meaning"],
                            "properties": {
                                "word": {"type": "string"},
                                "reading": {"type": "string"},
                                "meaning": {"type": "string"},
                            },
                        },
                    },
                    "grammar": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["pattern", "explanation", "surfaces"],
                            "properties": {
                                "pattern": {"type": "string"},
                                "explanation": {"type": "string"},
                                "surfaces": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string", "minLength": 1},
                                },
                            },
                        },
                    },
                },
            },
        }
    },
}


# Per-model pricing in USD per 1M tokens. Keep in sync with Anthropic's
# published pricing. Image tokens are billed as input tokens by Anthropic
# and are already included in `usage.input_tokens`, so no separate rate.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Claude 4 family
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-opus-4-5": {"input": 15.0, "output": 75.0},
    "claude-opus-4-1": {"input": 15.0, "output": 75.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
}


class Settings(BaseModel):
    data_dir: Path
    anthropic_api_key: str | None
    tesseract_cmd: str | None
    default_vlm_model: str = "claude-opus-4-7"
    default_vlm_prompt: str = DEFAULT_VLM_PROMPT
    vlm_max_edge: int = 1568
    vlm_effort_transcription: str = "high"
    vlm_effort_breakdown: str = "xhigh"
    pdf_render_dpi: int = 300
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(os.environ.get("STUDIOUS_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "documents").mkdir(exist_ok=True)
    (data_dir / "jobs").mkdir(exist_ok=True)
    overrides: dict = {}
    dpi_env = os.environ.get("STUDIOUS_PDF_RENDER_DPI")
    if dpi_env:
        overrides["pdf_render_dpi"] = int(dpi_env)
    log_level_env = os.environ.get("STUDIOUS_LOG_LEVEL")
    if log_level_env:
        overrides["log_level"] = log_level_env.upper()
    transcription_effort_env = os.environ.get("STUDIOUS_VLM_EFFORT_TRANSCRIPTION")
    if transcription_effort_env:
        overrides["vlm_effort_transcription"] = transcription_effort_env.lower()
    breakdown_effort_env = os.environ.get("STUDIOUS_VLM_EFFORT_BREAKDOWN")
    if breakdown_effort_env:
        overrides["vlm_effort_breakdown"] = breakdown_effort_env.lower()
    return Settings(
        data_dir=data_dir,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        tesseract_cmd=os.environ.get("TESSERACT_CMD") or None,
        **overrides,
    )
