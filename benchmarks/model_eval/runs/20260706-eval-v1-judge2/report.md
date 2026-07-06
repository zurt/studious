# Model eval report — run `20260706-eval-v1-judge2`

- git sha: `0f18363`
- dataset: `/Users/kurt/Library/Mobile Documents/com~apple~CloudDocs/dev/cc/studious/.claude/worktrees/model-eval/benchmarks/model_eval/dataset/v1`
- items judged: 4

## Overall league table

| Model | n | mean overall | mean rank | #1 count | char_acc | complete | format | halluc_ctrl |
|---|---|---|---|---|---|---|---|---|
| claude-opus-4-8 | 4 | 9.25 | 1.25 | 3 | 10.00 | 10.00 | 9.00 | 10.00 |
| claude-sonnet-5 | 4 | 9.25 | 1.75 | 1 | 10.00 | 9.75 | 9.00 | 10.00 |
| claude-haiku-4-5 | 4 | 6.50 | 3.00 | 0 | 7.00 | 9.25 | 7.75 | 7.50 |

## Pairwise sign tests (ranking-implied preference)

| Model A | Model B | A wins | B wins | n | preferred | p-value |
|---|---|---|---|---|---|---|
| claude-haiku-4-5 | claude-opus-4-8 | 0 | 4 | 4 | claude-opus-4-8 | 0.1250 |
| claude-haiku-4-5 | claude-sonnet-5 | 0 | 4 | 4 | claude-sonnet-5 | 0.1250 |
| claude-opus-4-8 | claude-sonnet-5 | 3 | 1 | 4 | claude-opus-4-8 | 0.6250 |

## By source

| Source | Model | n | mean overall | mean rank |
|---|---|---|---|---|
| textbook | claude-opus-4-8 | 4 | 9.25 | 1.25 |
| textbook | claude-sonnet-5 | 4 | 9.25 | 1.75 |
| textbook | claude-haiku-4-5 | 4 | 6.50 | 3.00 |

## By tag

| Tag | Model | n | mean overall | mean rank |
|---|---|---|---|---|
| vocab_list | claude-opus-4-8 | 4 | 9.25 | 1.25 |
| vocab_list | claude-sonnet-5 | 4 | 9.25 | 1.75 |
| vocab_list | claude-haiku-4-5 | 4 | 6.50 | 3.00 |

## Cost / latency

| Model | n | avg duration (ms) | avg cost (USD) | total cost (USD) | avg output chars |
|---|---|---|---|---|---|
| claude-haiku-4-5 | 4 | 5998 | 0.0041 | 0.0165 | 916 |
| claude-opus-4-8 | 4 | 14968 | 0.0268 | 0.1071 | 1053 |
| claude-sonnet-5 | 4 | 15625 | 0.0169 | 0.0678 | 946 |

## Notable judge quotes (worst items)

- **tb-r-vocab_list-01378521** (mean overall 7.7) — worst: `claude-haiku-4-5` scored 4: Multiple serious misreads: ニンジャライス for ニンジンライス (with invented gloss 'ninja rice'), 励まず（はげまず）'does not encourage' for 励ます（はげます）, 魅める（なぐめる）'charm' for 慰める（なぐさめる）, レジピ for レシピ, ごうした for こうした (gloss left as '[?]'). Also used 【地名】 instead of 〔地名〕. Wrong glosses cascade from the misreadings.
- **tb-r-vocab_list-fa1d820f** (mean overall 7.7) — worst: `claude-haiku-4-5` scored 5: Misreads こうした as ごうした and invents an incorrect gloss 'stubborn; obstinate'. Alters printed readings by appending する/な (ちょうほうする, さいそくする, かいだんする, あいまいな) where the image shows the bare readings. Replaces 〔人名〕 with '[person name]' rather than preserving the Japanese label, and omits an English gloss for ニクソン. Uses ～ instead of 〜.
- **tb-r-vocab_list-5f7efb40** (mean overall 9.0) — worst: `claude-sonnet-5` scored 9: All kanji, kana, and furigana match the image exactly. Glosses are accurate and appropriately dictionary-style. Minor formatting quirk: an extra blank line inserted between the (1) and (2) groups that isn't reflected as a break in the image, and the indentation of sub-entries under (1)/(2) is flattened.
- **tb-r-vocab_list-7ed82817** (mean overall 9.0) — worst: `claude-haiku-4-5` scored 8: Furigana error on first entry: （せっている）instead of （せってい）. Replaced 〔人名〕 with '[person name]' and dropped the 〔大学名〕 label entirely for 京都精華大, so the printed bracketed annotations are not faithfully reproduced. Glosses otherwise accurate.
