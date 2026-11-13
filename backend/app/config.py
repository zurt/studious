from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


BLANK_TRANSCRIBE_RULES = """\
<blanks>
A blank is a printed line, box, or empty bracket where the student
writes an answer. Never drop a blank or leave it as spaces.
- Write every underline-style blank as ＿＿＿＿＿ (exactly five
  full-width underscores, U+FF3F), however long or short the printed
  line is. Never use ASCII underscores, backslash escapes, spaces, or
  full-width spaces in its place.
- A blank that wraps from the end of one line onto the next is ONE
  blank: write ＿＿＿＿＿ once, where it begins, and keep the sentence
  flowing on the same line (no line break at the wrap). Two separate
  blanks in one item are two separate ＿＿＿＿＿.
- Empty brackets and boxes — （　　）, （　）, □, [　] — and dotted
  leaders such as …… are transcribed exactly as printed.
- A line drawn UNDER printed text (single, double, or dotted) is
  decoration: transcribe the text plainly. A line with no text on it is
  a blank. A blank can appear in instructions too, e.g. a short line in
  「…形を変えて＿＿＿＿＿にひらがなで書きなさい」.

Examples (printed → transcription):
- 山田：歌がお上手ですね。 / 中山：いえいえ、[long line]。山田さんほどではないですよ。
  → 中山：いえいえ、＿＿＿＿＿。山田さんほどではないですよ。
- 十分に[line to the margin] / [short line]と思う。 (one blank wrapped)
  → 十分に＿＿＿＿＿と思う。
- 私がボールを投げようものなら、すぐ[line]。 → …すぐ＿＿＿＿＿。
- A：健康のために… / B：ランニングをしていると言っても、[long line]が。
  → B：ランニングをしていると言っても、＿＿＿＿＿が。
</blanks>
"""


CALLOUT_TRANSCRIBE_RULES = """\
<callouts>
Some passages and dialogues are annotated with callouts: boxed labels
in the margin (often numbered ①②③…) joined to the text by a leader
line or a speech-bubble tail. A callout is a note about the line it
points to. It is not part of the running text.
- Transcribe the main text in its normal reading order. Never splice a
  callout's words into a sentence or dialogue turn, even when the box
  sits level with that line.
- Attach each callout to the line its leader line or tail actually
  touches. Follow the line to its end; do not go by which line the box
  sits beside. Boxes are often shifted up or down to make room, so a
  box can sit beside one turn while pointing at an earlier one.
- Write each callout as a Markdown blockquote (`> ` + the callout text
  exactly as printed, number and furigana included) directly after the
  dialogue turn or sentence it points to, with a blank line before and
  after it. When one turn carries several callouts, list them in the
  order of the lines they point to.
- If a callout's tail points into the middle of a turn that runs over
  several sentences, still place it after the whole turn.

Example. Printed: three dialogue turns; a box 「①声をかける」 beside the
second turn whose leader line runs up to the first turn; a box
「②用件を言う」 beside the third turn pointing at it.
A：すみません。

B：はい。

A：駅はどこですか。
→
A：すみません。

> ①声をかける

B：はい。

A：駅はどこですか。

> ②用件を言う
</callouts>
"""


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
- Ignore decorative underlines drawn under printed text (e.g. dotted
  underlines marking textbook grammar points). Transcribe the
  underlined text as plain text — do not emit <u>…</u> tags. This does
  NOT apply to blanks: see <blanks>.
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

{{BLANK_RULES}}
<output_format>
Return only the Markdown transcription, with no preamble or closing
remarks. Begin directly with the first line of the page.
</output_format>
""".replace("{{BLANK_RULES}}", BLANK_TRANSCRIBE_RULES)


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
- Ignore decorative underlines drawn under printed text (e.g. dotted
  underlines marking textbook grammar points). Transcribe the
  underlined text as plain text — do not emit <u>…</u> tags. This
  does NOT apply to blanks: see <blanks>.
- Ignore body-text line numbers in the page margin (e.g. small
  "5", "10", "15" markers every Nth line). Do not include them.
- If a character or word is unclear, write [?]. If part of the region
  is illegible or cut off, write [illegible] and continue.
- Do not add commentary or translations that are not on the page.
</rules>

{{BLANK_RULES}}
{{CALLOUT_RULES}}
<output_format>
Return only the Markdown transcription, with no preamble or closing
remarks.
</output_format>
""".replace("{{BLANK_RULES}}", BLANK_TRANSCRIBE_RULES).replace(
    "{{CALLOUT_RULES}}", CALLOUT_TRANSCRIBE_RULES
)


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
instruction block, etc.). A `<region_tag>` element names the kind of
region — values include `reading_passage`, `vocab_list`,
`grammar_points`, `exercises`, `instructions`, `other`, or
`unspecified`. When the tag is `exercises` or `instructions`, expect
numbered drill items, blanks, and choice banks, and follow the
exercise-item rules below.

<task>
Produce a sentence-by-sentence study breakdown of the input. Split
the input into natural sentences using Japanese sentence-ending
punctuation (。！？) or, for non-narrative content, into individual
items, headings, or example lines as they appear. For markdown
tables: treat the entire table as a single entry unless one or more
cells contain sentence-ending punctuation (。！？), in which case
split at those sentence boundaries (one entry per sentence, spanning
whatever cells are needed).

Fill-in-the-blank exercise items are first-class entries. Lines
containing blanks ARE valid sentences — do not skip them. The
canonical blank is a run of full-width underscores (＿＿＿＿＿), but
older transcriptions use other styles: ASCII underscores (___), ……,
（　　）, （　）, □, [　], or a run of full-width spaces in the middle of
a sentence. Treat all of these as blanks and copy them exactly as they
appear in the input — never rewrite one into a different style and never
add backslash escapes. A blank inside an instruction header (e.g.
「…＿＿＿＿＿にひらがなで書きなさい」) refers to the blanks in the
items; it is part of the header, not a separate item. When the input
is or contains a numbered exercise (①②③…, 1./2., (1)/(2)…), emit one
entry per numbered item. Copy the item VERBATIM into `text`, blanks
and all, including ALL text from the item's number marker up to (but
not including) the next item's marker or end of input. An item often
spans multiple sentences — e.g. a setup statement followed by the
sentence with the blank to fill — and internal 。！？ inside an item
DO NOT start a new entry. The numbered-item boundary wins over
sentence-final punctuation here. Extract vocab and grammar from the printed (non-blank) text
around the blanks; the blank itself is not a vocab item, but the
particles, suffixes, and surrounding clauses are fair game (e.g. for
「夫は仕事、妻は＿＿＿という考え方の人が、昔は多かった。」 you can
still surface 「という」, 「考え方」, 「〜が多かった」). If a region
contains an instruction header or a choice-bank table preceding the
items, emit those as their own entries first (the header as one
entry, the table as one entry per the table rule above), then the
numbered items.

For each sentence or item, return:
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
guide for the grammar points in this chapter. Keep it simple and direct.
Provide related grammar and expressions where appropriate (both to group
related patterns and to disambiguate). Include a few short, clear examples.

Language: write all explanatory prose — meanings, nuance, usage notes,
form descriptions, comparisons, everything that isn't itself a piece of
Japanese being quoted — in English. Japanese appears only for: the
pattern itself, a Japanese term or form being named or quoted (e.g. a
conjugation label, or the specific word being defined), and example
sentences (each paired with its English translation on the next line).
Never write a paragraph of Japanese-only explanation — the reader is an
English speaker who cannot yet read fluent Japanese prose.
</task>

<structure>
- `intro`: optional one- or two-sentence orientation for the chapter, in
  English (markdown).
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
    `body_md` is GitHub-flavored markdown, written in English prose per
    the language rule above; use bullet lists for forms, pair Japanese
    example sentences with their English translation on the next line,
    and write related/contrasting patterns as bullets with a short
    English gloss in parentheses.
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


# A template: `{example_count}` and `{question_length}` are filled from the
# learner profile (services/learner_profile.py), which also appends a
# <learner_profile> block when a JLPT level is set. Render it with
# learner_profile.render_exercise_completion_prompt, never send it raw.
EXERCISE_COMPLETION_PROMPT = """\
You are a Japanese-language tutor for English-speaking learners. The
input has up to three parts:
- `<region_transcription>`: the full transcribed text of an exercises
  region from a Japanese textbook. Use this for context — it usually
  contains the instruction header (what kind of drill this is),
  surrounding numbered items, and any choice bank or vocabulary list
  that applies to the whole region.
- `<reading_reference>` (optional): reading passage(s) this exercises
  region is about, printed elsewhere in the textbook (or in another
  textbook). Each passage starts with a `[Source: …]` line naming the
  book, chapter, and page(s). Use it to answer questions about the
  reading's content and to decide items that depend on it. It is
  background material only — never an item to complete.
- `<target_sentence>`: the single item you are being asked to complete.
  This is one line from the region transcription.

<task>
First decide whether `<target_sentence>` is actually an exercise item
to complete. The instruction header, section title, choice bank, or a
plain example sentence printed by the textbook are NOT exercises — only
the numbered items the student is meant to fill in, transform, or
answer are exercises. A numbered question the student answers in their
own words (e.g. a comprehension question about a reading) IS an
exercise.

If the target IS an exercise, next decide which of three shapes it has:
- `constrained`: the correct fill is limited to a specific closed set
  the textbook already gives you. Three common cases:
    (a) a shared word/phrase bank for the whole region (an instruction
        like "choose from the list below" or "use each word only
        once", with the bank printed once and drawn on by every
        numbered item) — pick whichever bank entry best fits THIS
        item;
    (b) two or more candidates printed inline in `<target_sentence>`
        itself (e.g. together in parentheses or separated by a slash,
        such as "（は／が）") — pick the one that is correct here;
    (c) a multiple-choice question whose lettered or numbered options
        are printed with it (e.g. 「次のどの意味ですか。」 followed by
        a./b./c. lines) — pick the correct option.
  In every case exactly one of the given options is the defensible
  answer for this item. This job only sees one item at a time and does
  not know what sibling items already used from the bank, so just pick
  whichever bank entry is the best semantic/grammatical fit for THIS
  sentence; do not try to guess or avoid what other items might have
  taken.
- `question`: a question the student answers in their own words
  rather than a sentence they complete or transform — typically a
  comprehension question about a reading (「〜とは何ですか。」,
  「筆者は〜と述べていますか。」, 「なぜ〜のですか。」) or a
  discussion question asking for the student's own opinion or
  experience. A question that prints its own answer options (a/b/c
  choices, or candidates like（昔・現代）) is `constrained`, not
  `question`.
- `open`: everything else — a free completion or transformation where
  the textbook does not hand you a closed set of candidates, so
  multiple different words or phrasings could correctly fill the
  blank.

If the exercise is `constrained`, complete it using the surrounding
region as context (read the instruction header, look at sibling items,
and weigh the full bank or inline candidates against each other — and,
when the item is about a reading, against what `<reading_reference>`
says) and call `record_exercise_completion` with:
- exercise_type: "constrained"
- answer: the completed sentence, in Japanese, with the printed
  portions of `<target_sentence>` preserved VERBATIM — copy them
  character-for-character, including punctuation and ordering. Fill in
  only the one chosen bank entry or inline candidate. Add readings as
  described in `<readings>`. For a multiple-choice question
  (case c), `answer` is instead just the chosen option exactly as
  printed (e.g. `c. これは病気だ`), and `filled_text` is that same
  string.
- answer_english: a concise English translation of the completed
  answer sentence.
- explanation: one or two sentences in English explaining why this
  option is correct here, and briefly why the other candidate(s) fit
  less well. When the item is about a reading, cite the phrase in the
  reading that decides it.
- filled_text: the exact substring of `answer` that you inserted for
  the blank — copy it character-for-character as it appears in
  `answer`, including any furigana annotation you added (e.g.
  `仕上(しあ)げて`). This is used to highlight the filled-in portion for
  the learner, so it must be an exact, verbatim substring of `answer`.
- examples: an empty array. Do NOT invent alternative completions for
  a `constrained` exercise — every other bank entry or inline
  candidate is either wrong for this item or is the answer to a
  sibling item, so presenting it as an "alternative" would mislead the
  learner.

If the exercise is a `question`, answer it and call
`record_exercise_completion` with:
- exercise_type: "question"
- answer: a model answer in natural Japanese, as a strong student would
  write it — {question_length}, answering every part of what is asked
  and nothing more. Do NOT repeat the question. For a
  comprehension question, base the answer on `<reading_reference>` (or
  on the region itself, if the reading is printed there) and put the
  relevant content in your own words rather than copying a long
  stretch verbatim, unless the question asks for a quotation. For a
  question about the student's own opinion or experience, write a
  plausible first-person sample answer. Add readings as described in
  `<readings>`.
- answer_english: a concise English translation of the answer.
- explanation: one or two sentences in English. For a comprehension
  question, point to where the answer comes from in the reading,
  quoting the key Japanese phrase. For an opinion question, say what
  the question is asking the student to express. If the question
  depends on a reading you were not given, say so here, starting with
  "The reading was not provided", and give the most plausible answer
  you can from the question and region alone.
- filled_text: an empty string.
- examples: an empty array.

If the exercise is `open`, complete it using the surrounding region as
context (read the instruction header to figure out what is being
practiced, and look at sibling items) and call
`record_exercise_completion` with:
- exercise_type: "open"
- answer: the completed sentence with the blank filled in, in Japanese.
  Preserve the printed portions of the target sentence VERBATIM —
  copy them character-for-character from `<target_sentence>`, including
  punctuation and ordering. Fill ONLY the blank(s). Add readings as
  described in `<readings>`. If the exercise is a transformation
  rather than a blank, give the transformed sentence.
- answer_english: a concise English translation of the completed answer
  sentence above.
- explanation: one or two sentences in English explaining the answer
  (what grammar/word is being practiced, why this answer fits).
- filled_text: the exact substring of `answer` that you inserted for
  the blank — copy it character-for-character as it appears in
  `answer`, including any furigana annotation you added (e.g.
  `仕上(しあ)げて`). This is used to highlight the filled-in portion for
  the learner, so it must be an exact, verbatim substring of `answer`.
  If the exercise is a transformation with no single blank to point at
  (the whole sentence or clause changed), leave this empty.
- examples: a list of {example_count} ALTERNATIVE COMPLETIONS of the same
  target sentence. Each example is the target sentence with the blank filled
  in a different way — the printed portions of the target sentence
  must appear VERBATIM in every example. Do NOT rewrite the
  surrounding clauses, swap subjects, change tense outside the blank,
  or invent unrelated sentences. The FIRST example must be the
  simplest, most natural completion — short, plain vocabulary in the
  blank, the most obvious fit. Any further examples are
  appropriate, slightly richer alternative completions that show
  different ways the blank could be filled while keeping the rest of
  the sentence unchanged. Each example object has:
    - japanese: the completed sentence, with readings as described in
      `<readings>`. The portions outside the blank must match
      `<target_sentence>` verbatim.
    - reading: the full sentence written in kana (hiragana/katakana
      only — no kanji). For sentences that are already kana-only, just
      repeat the japanese field.
    - english: a concise English translation.
    - explanation: one short English sentence describing WHY this
      completion fits the blank. For the first example, explain why it
      is the most natural fit. For each further example, note what
      nuance or variation this alternative completion shows.

If the input is NOT an exercise, call the tool with:
- no_exercise: true
- reason: a short English sentence explaining why (e.g. "This line is a
  section heading, not a drill item.").
Do NOT invent an exercise that is not present. Omit `answer`,
`exercise_type`, `filled_text`, and `examples` in this case.
</task>

<readings>
The app shows the learner the reading of every kanji word, hidden until
they tap it, so it needs a reading for EVERY word that contains kanji —
in `answer`, in each example's `japanese`, and in any Japanese you quote
inside `explanation`. Write the reading in hiragana, in half-width
parentheses, right after the kanji it reads: 健康病(けんこうびょう),
自分(じぶん)の言葉(ことば), 食(た)べる, 無視(むし)する.
- Okurigana and other kana stay outside the parentheses: 食(た)べる,
  not 食べる(たべる).
- Every kanji needs a reading. Annotate each word, or a whole run of
  kanji at once — 健康(けんこう)第一(だいいち) or
  健康第一(けんこうだいいち) — but never leave kanji right before an
  annotated word bare (not 健康第一(だいいち)).
- Use the reading that fits this context: 何(なに) vs 何(なん),
  一日(いちにち) vs 一日(ついたち).
- Readings are the one permitted addition to text that must otherwise
  be copied verbatim: printed text from `<target_sentence>` with
  `(かな)` inserted after its kanji still counts as verbatim, and
  `filled_text` includes the readings exactly as they appear in
  `answer`.
</readings>

<rules>
- If the exercise has multiple blanks, fill all of them. `filled_text`
  should still be a single verbatim substring of `answer` — if there
  are multiple separate blanks, pick the one the exercise is actually
  testing (usually the only one that varies across sibling items) or
  leave `filled_text` empty rather than guessing.
- For `constrained` (other than a multiple-choice question) and `open`
  exercises, the printed (non-blank) portions of `<target_sentence>`
  MUST appear verbatim in `answer` and in every example's `japanese`.
  Vary only what fills the blank.
- For a `constrained` exercise, return `examples: []` — never pad it
  with invented alternatives, and never fill the blank with anything
  outside the given bank or inline candidates.
- For an `open` exercise, the first example must be the simplest
  natural completion. Provide exactly {example_count} examples.
- The `<region_transcription>` and `<reading_reference>` are context
  only; complete exactly the one line given in `<target_sentence>`, not
  any other item.
- Do not return prose; return only the tool call.
</rules>
"""


EXERCISE_COMPLETION_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "exercise_type": {"type": "string", "enum": ["open", "constrained", "question"]},
        "answer": {"type": "string"},
        "answer_english": {"type": "string"},
        "explanation": {"type": "string"},
        "filled_text": {"type": "string"},
        "examples": {
            # Required non-empty (3) for `exercise_type: "open"`; must be `[]`
            # for `"constrained"` (word bank / inline choice) and `"question"`
            # (comprehension/discussion — see EXERCISE_COMPLETION_PROMPT). Not strict-validated on a
            # forced tool call, so this is documentation, not enforcement.
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["japanese", "reading", "english", "explanation"],
                "properties": {
                    "japanese": {"type": "string", "minLength": 1},
                    "reading": {"type": "string", "minLength": 1},
                    "english": {"type": "string", "minLength": 1},
                    "explanation": {"type": "string", "minLength": 1},
                },
            },
        },
        "no_exercise": {"type": "boolean"},
        "reason": {"type": "string"},
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


EXAMPLE_SENTENCES_PROMPT = """\
You write example sentences for Japanese flashcards, in the style of the
Kaishi 1.5k Anki deck. The input is a `<words>` JSON list; each entry has
`id`, `headword`, `reading`, `meaning` and `pos` (part of speech). Write
exactly one sentence for each word.

<sentence_rules>
- Natural Japanese a native speaker would really say, 8 to 25 characters,
  one clause or two short ones, ending with 。 (or ！ / ？ when natural).
- Everything except the target word must be vocabulary and grammar at
  about JLPT N5-N4 level, so the target word is the only hard part.
- Use the word in the given `meaning`; some words have several senses.
- The word may be inflected naturally (past, negative, て-form, polite).
  Return the exact surface form you used in `surface`; it must appear in
  `sentence` exactly as written there.
- Headwords written like 企画する, 重要な or 料理(する) name a word that
  takes する or な in a sentence: use the natural form, e.g. 企画した,
  重要な問題, 料理している.
- A headword given in a する form (操作する, 企画する, 料理(する)) must be
  used as a verb, inflected: した, します, して, している, される, できる.
  Never use only the noun (not 操作が簡単だ). A headword given with な
  (重要な) must be used as an adjective: 重要な before a noun, or 重要だ /
  重要です at the end.
- No names of real people, nothing that needs outside context, no
  quotation of textbooks, no brackets, no blanks, no Latin letters
  (unless the headword itself contains them).
</sentence_rules>

<fields>
- `id`: copy the entry's id.
- `sentence`: plain Japanese text only, no markup.
- `surface`: the target word as it appears in `sentence`.
- `furigana`: the whole sentence in Anki furigana syntax: 漢字[よみ]. Put a
  reading on every run of kanji, including the target word; leave kana
  bare (never put a reading on kana). Put a single ASCII space before a
  kanji run that directly follows kana or other text; no space at the
  start of the sentence. Removing every [...] group and every space must
  give back `sentence` exactly. Choose the reading that fits the context.
- `gloss`: the sentence in plain natural English, no Japanese characters.
</fields>

<examples>
Input: {"id": "a1", "headword": "嬉しい", "reading": "うれしい", "meaning": "glad; happy", "pos": ["adj-i"]}
Output: {"id": "a1", "sentence": "彼に会えて嬉しかった。", "surface": "嬉しかった", "furigana": "彼[かれ]に 会[あ]えて 嬉[うれ]しかった。", "gloss": "I was glad to be able to meet him."}

Input: {"id": "a2", "headword": "企画する", "reading": "きかくする", "meaning": "to plan; to organize", "pos": ["vs"]}
Output: {"id": "a2", "sentence": "友達と旅行を企画した。", "surface": "企画した", "furigana": "友達[ともだち]と 旅行[りょこう]を 企画[きかく]した。", "gloss": "I planned a trip with my friends."}

Input: {"id": "a3", "headword": "ゆっくり", "reading": "ゆっくり", "meaning": "slowly; leisurely", "pos": ["adv"]}
Output: {"id": "a3", "sentence": "もう少しゆっくり話してください。", "surface": "ゆっくり", "furigana": "もう 少[すこ]しゆっくり 話[はな]してください。", "gloss": "Please speak a little more slowly."}
</examples>

<rules>
- Return an entry for every input word, with the same `id`. A word may
  carry a `problem` field: the previous attempt was rejected for that
  reason, so fix it.
- Do not return prose; return only the tool call.
</rules>
"""


EXAMPLE_SENTENCES_TOOL_SCHEMA: dict = {
    "type": "object",
    "required": ["examples"],
    "properties": {
        "examples": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "sentence", "surface", "furigana", "gloss"],
                "properties": {
                    "id": {"type": "string"},
                    "sentence": {"type": "string"},
                    "surface": {"type": "string"},
                    "furigana": {"type": "string"},
                    "gloss": {"type": "string"},
                },
            },
        }
    },
}


REGION_CHECK_PROMPT = """\
You check one transcribed region of a Japanese textbook after it has been \
transcribed. Answer two questions about it by calling the record_region_check \
tool.

The tags a region can carry:
- reading_passage: continuous prose or dialogue meant to be read.
- vocab_list: a list of words with readings and meanings.
- grammar_points: grammar explanations, usually with example sentences.
- exercises: questions or tasks for the student to answer, such as \
fill-in-the-blank items, matching, or comprehension questions.
- instructions: directions about how to do something, without the task \
content itself.
- other: anything else.

Question 1: is the current tag appropriate for the text in <region>?
Textbook sections blur into each other. A grammar explanation contains \
example sentences, an exercise starts with an instruction line, and a \
passage may be followed by a couple of footnoted words. The tag should \
describe what the region mostly is. Suggest a different tag only when the \
current one is clearly wrong, and use confidence "high" only in that case; \
use "medium" or "low" when it is arguable. When the tag is fine, return the \
current tag as suggested_tag and leave tag_reason empty.

Question 2: does this region need a reading passage it does not contain? \
Set needs_reference to true only when the text is exercise content whose \
questions cannot be answered without a separate reading passage or dialogue \
that is not included in the text. For example, 「本文を読んで質問に答えなさい」 \
or "according to the passage" followed by questions about the passage's \
content, with no passage present, needs one. Fill-in-the-blank grammar \
drills do not, and neither does an exercise that includes its own passage or \
dialogue. Anything that is not exercise content does not need one. Judge \
this on <region> together with <continuation>, if present.

The label is judged on <region> alone. <continuation> is the text of the \
regions that follow it in the same chain; use it only for the second \
question.

Keep both reasons to one short English sentence.
"""

REGION_CHECK_TOOL_SCHEMA: dict = {
    "type": "object",
    "required": [
        "suggested_tag",
        "tag_confidence",
        "tag_reason",
        "needs_reference",
        "reference_reason",
    ],
    "properties": {
        "suggested_tag": {
            "type": "string",
            "enum": [
                "vocab_list",
                "grammar_points",
                "reading_passage",
                "exercises",
                "instructions",
                "other",
            ],
            "description": "The best tag for the region; the current tag when it is fine.",
        },
        "tag_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "tag_reason": {
            "type": "string",
            "description": "One short English sentence; may be empty when the tag is unchanged.",
        },
        "needs_reference": {
            "type": "boolean",
            "description": (
                "True only for exercise content whose questions cannot be answered "
                "without a separate reading passage or dialogue that is not in the text."
            ),
        },
        "reference_reason": {"type": "string", "description": "One short English sentence."},
    },
}


# Per-model pricing in USD per 1M tokens. Keep in sync with Anthropic's
# published pricing. Image tokens are billed as input tokens by Anthropic
# and are already included in `usage.input_tokens`, so no separate rate.
# Prompt-cache rates default to 1.25x input for a (5-minute) cache write and
# 0.1x input for a cache read (services/costs.py); `cache_write` /
# `cache_read` override them where a model's rates differ.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Haiku 5.5: the rate for prompts up to 100K tokens. The $0.50/$2.50 rate
    # for longer prompts is not modelled; the region check never sends prompts
    # that long.
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50},
    # Claude 5 family (Anthropic's published table as of 2026-11-12). Cache
    # reads on both are 0.05x input.
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.1},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.2},
    # Claude 4 family. Opus pricing dropped to $5/$25 with Opus 4.5; the
    # original Opus 4 and 4.1 remain at the launch $15/$75. Sonnet 5 is still
    # listed at $2/$10 as of 2026-09-25 (its launch pricing was announced as
    # ending 2026-08-31 — re-check if the sticker changes).
    "claude-sonnet-5": {"input": 2.0, "output": 10.0},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    "claude-opus-4-5": {"input": 5.0, "output": 25.0},
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
    wanikani_api_token: str | None = None
    anki_connect_url: str = "http://127.0.0.1:8765"
    anki_push_deck: str = "Studious"
    # macOS `say` voice for card audio, and whether a send attaches it.
    # `say` voices: "auto" (every installed Enhanced/Premium ja_JP voice, else the
    # plain Kyoko) or a comma-separated list of voice names.
    tts_voice: str = "auto"
    # Speech engine: "say" (the Mac voice) or "voicevox" (VOICEVOX / AivisSpeech
    # on localhost). The speaker is a style id from the engine's /speakers;
    # there is no default, one must be chosen. Preferences override these.
    tts_engine: str = "say"
    tts_url: str = "http://127.0.0.1:50021"
    tts_speaker: int | None = None
    anki_push_audio: bool = True
    anki_push_note_type: str = "Kaishi 1.5k"
    tesseract_cmd: str | None
    # Opus 5.5 since 2026-11: best transcriber of five in model-eval run
    # 20261111-eval-v2, and the only one that doesn't invent unprinted
    # furigana (benchmarks/model_eval/reports/2026-11-11-model-comparison.md).
    default_vlm_model: str = "claude-opus-5-5"
    # Models offered in the settings UI for VLM selection. The first entry
    # is treated as the canonical default; anything outside this list is
    # still accepted server-side for forward compatibility.
    selectable_vlm_models: list[str] = [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-sonnet-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
    ]
    # The helper model runs short text-only checks (currently the region
    # check) that don't need the main model. It is separate from
    # `default_vlm_model`, which drives transcription, breakdowns,
    # completions, guides and examples.
    default_helper_model: str = "claude-haiku-5-5"
    selectable_helper_models: list[str] = [
        "claude-haiku-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    ]
    default_vlm_prompt: str = DEFAULT_VLM_PROMPT
    vlm_max_edge: int = 1568
    vlm_effort_transcription: str = "high"
    vlm_effort_breakdown: str = "xhigh"
    # Short single-sentence generation: no need for the breakdown effort.
    vlm_effort_examples: str = "medium"
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
        wanikani_api_token=os.environ.get("WANIKANI_API_TOKEN") or None,
        anki_connect_url=os.environ.get("ANKI_CONNECT_URL") or "http://127.0.0.1:8765",
        anki_push_deck=os.environ.get("ANKI_PUSH_DECK") or "Studious",
        tts_voice=os.environ.get("STUDIOUS_TTS_VOICE") or "auto",
        tts_engine=(os.environ.get("STUDIOUS_TTS_ENGINE") or "say").strip().lower()
        if (os.environ.get("STUDIOUS_TTS_ENGINE") or "say").strip().lower() in ("say", "voicevox")
        else "say",
        tts_url=os.environ.get("STUDIOUS_TTS_URL") or "http://127.0.0.1:50021",
        tts_speaker=int(os.environ["STUDIOUS_TTS_SPEAKER"])
        if (os.environ.get("STUDIOUS_TTS_SPEAKER") or "").strip().lstrip("-").isdigit()
        else None,
        anki_push_audio=(os.environ.get("ANKI_PUSH_AUDIO") or "true").strip().lower()
        not in ("0", "false", "no", "off"),
        anki_push_note_type=os.environ.get("ANKI_PUSH_NOTE_TYPE") or "Kaishi 1.5k",
        tesseract_cmd=os.environ.get("TESSERACT_CMD") or None,
        **overrides,
    )
