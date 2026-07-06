# Model eval report — run `20260706-eval-v1`

- git sha: `95be7f3`
- dataset: `/Users/kurt/Library/Mobile Documents/com~apple~CloudDocs/dev/cc/studious/.claude/worktrees/model-eval/benchmarks/model_eval/dataset/v1`
- items judged: 31

## Overall league table

| Model | n | mean overall | mean rank | #1 count | char_acc | complete | format | halluc_ctrl |
|---|---|---|---|---|---|---|---|---|
| claude-opus-4-8 | 31 | 8.45 | 1.45 | 17 | 9.48 | 9.48 | 8.00 | 8.35 |
| claude-sonnet-5 | 31 | 8.39 | 1.61 | 13 | 9.32 | 9.29 | 7.77 | 8.77 |
| claude-haiku-4-5 | 31 | 5.58 | 2.94 | 1 | 6.71 | 8.13 | 5.94 | 6.23 |

## Pairwise sign tests (ranking-implied preference)

| Model A | Model B | A wins | B wins | n | preferred | p-value |
|---|---|---|---|---|---|---|
| claude-haiku-4-5 | claude-opus-4-8 | 1 | 30 | 31 | claude-opus-4-8 | 0.0000 |
| claude-haiku-4-5 | claude-sonnet-5 | 1 | 30 | 31 | claude-sonnet-5 | 0.0000 |
| claude-opus-4-8 | claude-sonnet-5 | 18 | 13 | 31 | claude-opus-4-8 | 0.4731 |

## By source

| Source | Model | n | mean overall | mean rank |
|---|---|---|---|---|
| textbook | claude-opus-4-8 | 22 | 8.55 | 1.36 |
| textbook | claude-sonnet-5 | 22 | 8.23 | 1.73 |
| textbook | claude-haiku-4-5 | 22 | 5.59 | 2.91 |
| workbook | claude-sonnet-5 | 9 | 8.78 | 1.33 |
| workbook | claude-opus-4-8 | 9 | 8.22 | 1.67 |
| workbook | claude-haiku-4-5 | 9 | 5.56 | 3.00 |

## By tag

| Tag | Model | n | mean overall | mean rank |
|---|---|---|---|---|
| None | claude-opus-4-8 | 6 | 9.00 | 1.33 |
| None | claude-sonnet-5 | 6 | 8.67 | 1.67 |
| None | claude-haiku-4-5 | 6 | 4.83 | 3.00 |
| exercises | claude-sonnet-5 | 12 | 8.67 | 1.50 |
| exercises | claude-opus-4-8 | 12 | 8.42 | 1.50 |
| exercises | claude-haiku-4-5 | 12 | 5.75 | 3.00 |
| grammar_points | claude-opus-4-8 | 5 | 9.20 | 1.40 |
| grammar_points | claude-sonnet-5 | 5 | 8.60 | 1.60 |
| grammar_points | claude-haiku-4-5 | 5 | 6.80 | 3.00 |
| instructions | claude-opus-4-8 | 1 | 9.00 | 1.00 |
| instructions | claude-sonnet-5 | 1 | 8.00 | 2.00 |
| instructions | claude-haiku-4-5 | 1 | 6.00 | 3.00 |
| reading_passage | claude-opus-4-8 | 3 | 8.67 | 1.33 |
| reading_passage | claude-sonnet-5 | 3 | 8.67 | 1.67 |
| reading_passage | claude-haiku-4-5 | 3 | 5.33 | 3.00 |
| vocab_list | claude-sonnet-5 | 4 | 6.75 | 1.75 |
| vocab_list | claude-opus-4-8 | 4 | 6.50 | 1.75 |
| vocab_list | claude-haiku-4-5 | 4 | 4.75 | 2.50 |

## Cost / latency

| Model | n | avg duration (ms) | avg cost (USD) | total cost (USD) | avg output chars |
|---|---|---|---|---|---|
| claude-haiku-4-5 | 31 | 6221 | 0.0040 | 0.1240 | 574 |
| claude-opus-4-8 | 31 | 30809 | 0.0263 | 0.8156 | 600 |
| claude-sonnet-5 | 31 | 9336 | 0.0112 | 0.3485 | 589 |

## Notable judge quotes (worst items)

- **tb-r-vocab_list-fa1d820f** (mean overall 5.3) — worst: `claude-haiku-4-5` scored 4: Misreads こうした as ごうした (and glosses it wrongly as 'stubborn; obstinate'). Alters furigana against the image: ちょうほうする, さいそくする, かいだんする, あいまいな where the image shows ちょうほう, さいそく, かいだん, あいまい. Replaces 〔人名〕 with [person name]. Also invents English glosses not in the image.
- **tb-r-vocab_list-5f7efb40** (mean overall 6.0) — worst: `claude-sonnet-5` scored 6: All Japanese headwords and furigana (望む/のぞむ, 異文化/いぶんか, 内容/ないよう, 距離/きょり, 当たり前/あたりまえ, 故郷/こきょう, 初めて/はじめて, 具体例/ぐたいれい, 挙げる/あげる) transcribed correctly. However, the image contains NO English glosses; all definitions (e.g. 'to hope; to wish for', 'natural; obvious; taken for granted') are invented. This candidate adds the longest/most elaborate hallucinated glosses. Line/indent structure roughly preserved.
- **tb-r-vocab_list-7ed82817** (mean overall 6.0) — worst: `claude-haiku-4-5` scored 5: Furigana error: 設定する transcribed as （せっている） instead of （せってい）. Replaced 〔人名〕 with '[person name]' and dropped the 〔大学名〕 annotation for 京都精華大, substituting an English translation. Also adds invented English glosses throughout.
- **tb-r-exercises-ab46750d** (mean overall 6.7) — worst: `claude-haiku-4-5` scored 5: Spurious spaces inserted ('うもの なら' throughout), incorrect bold spans ('つこう**もの なら**', '**しよう**もの なら'), exercise bullets rendered as ①② instead of ❶❷, added furigana 叱(しか) not visible in image, and missed the 逆(さか) furigana.
- **tb-r-vocab_list-01378521** (mean overall 6.7) — worst: `claude-haiku-4-5` scored 4: Multiple serious character errors: ニンジャライス for ニンジンライス, 励まず（はげまず）for 励ます（はげます）, 魅める（なぐめる）for 慰める（なぐさめる）, レジピ for レシピ, ごうした for こうした, 【地名】 instead of 〔地名〕. Also invented English glosses not present in the image (including nonsense glosses like 'does not encourage', 'ninja rice'). Lost the indentation of the ＊腕をふるう sub-entry.
