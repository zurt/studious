# Model eval report — run `20261111-eval-v2`

- git sha: `29d8352`
- dataset: `/Users/kurt/Library/Mobile Documents/com~apple~CloudDocs/dev/cc/studious/benchmarks/model_eval/dataset/v2`
- items judged: 47

## Overall league table

| Model | n | mean overall | mean rank | #1 count | char_acc | complete | format | halluc_ctrl |
|---|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | 47 | 9.02 | 2.04 | 23 | 9.96 | 9.68 | 8.23 | 9.85 |
| claude-opus-4-8 | 47 | 7.87 | 2.98 | 7 | 9.00 | 9.40 | 7.83 | 8.36 |
| claude-sonnet-5 | 47 | 8.15 | 3.15 | 7 | 9.26 | 9.26 | 7.83 | 9.00 |
| claude-haiku-5-5 | 47 | 8.11 | 3.34 | 4 | 9.34 | 9.32 | 7.60 | 9.13 |
| claude-sonnet-5-5 | 47 | 7.70 | 3.49 | 6 | 9.09 | 9.57 | 7.26 | 7.91 |

## Pairwise sign tests (ranking-implied preference)

| Model A | Model B | A wins | B wins | n | preferred | p-value |
|---|---|---|---|---|---|---|
| claude-haiku-5-5 | claude-opus-4-8 | 18 | 29 | 47 | claude-opus-4-8 | 0.1439 |
| claude-haiku-5-5 | claude-opus-5-5 | 11 | 36 | 47 | claude-opus-5-5 | 0.0003 |
| claude-haiku-5-5 | claude-sonnet-5 | 24 | 23 | 47 | claude-haiku-5-5 | 1.0000 |
| claude-haiku-5-5 | claude-sonnet-5-5 | 25 | 22 | 47 | claude-haiku-5-5 | 0.7709 |
| claude-opus-4-8 | claude-opus-5-5 | 14 | 33 | 47 | claude-opus-5-5 | 0.0079 |
| claude-opus-4-8 | claude-sonnet-5 | 24 | 23 | 47 | claude-opus-4-8 | 1.0000 |
| claude-opus-4-8 | claude-sonnet-5-5 | 28 | 19 | 47 | claude-opus-4-8 | 0.2430 |
| claude-opus-5-5 | claude-sonnet-5 | 34 | 13 | 47 | claude-opus-5-5 | 0.0031 |
| claude-opus-5-5 | claude-sonnet-5-5 | 36 | 11 | 47 | claude-opus-5-5 | 0.0003 |
| claude-sonnet-5 | claude-sonnet-5-5 | 28 | 19 | 47 | claude-sonnet-5 | 0.2430 |

## By source

| Source | Model | n | mean overall | mean rank |
|---|---|---|---|---|
| textbook | claude-opus-5-5 | 31 | 8.94 | 2.26 |
| textbook | claude-opus-4-8 | 31 | 8.52 | 2.65 |
| textbook | claude-sonnet-5 | 31 | 8.42 | 3.06 |
| textbook | claude-sonnet-5-5 | 31 | 8.13 | 3.42 |
| textbook | claude-haiku-5-5 | 31 | 8.16 | 3.61 |
| workbook | claude-opus-5-5 | 16 | 9.19 | 1.62 |
| workbook | claude-haiku-5-5 | 16 | 8.00 | 2.81 |
| workbook | claude-sonnet-5 | 16 | 7.62 | 3.31 |
| workbook | claude-opus-4-8 | 16 | 6.62 | 3.62 |
| workbook | claude-sonnet-5-5 | 16 | 6.88 | 3.62 |

## By tag

| Tag | Model | n | mean overall | mean rank |
|---|---|---|---|---|
| None | claude-opus-5-5 | 14 | 9.14 | 1.64 |
| None | claude-haiku-5-5 | 14 | 7.71 | 2.93 |
| None | claude-opus-4-8 | 14 | 7.21 | 3.07 |
| None | claude-sonnet-5 | 14 | 7.36 | 3.57 |
| None | claude-sonnet-5-5 | 14 | 6.86 | 3.79 |
| exercises | claude-opus-5-5 | 16 | 9.00 | 2.19 |
| exercises | claude-haiku-5-5 | 16 | 8.56 | 2.94 |
| exercises | claude-opus-4-8 | 16 | 7.94 | 3.06 |
| exercises | claude-sonnet-5 | 16 | 8.31 | 3.31 |
| exercises | claude-sonnet-5-5 | 16 | 7.81 | 3.50 |
| grammar_points | claude-opus-5-5 | 6 | 8.83 | 1.67 |
| grammar_points | claude-opus-4-8 | 6 | 8.33 | 2.33 |
| grammar_points | claude-sonnet-5 | 6 | 7.83 | 3.00 |
| grammar_points | claude-sonnet-5-5 | 6 | 8.00 | 3.67 |
| grammar_points | claude-haiku-5-5 | 6 | 7.33 | 4.33 |
| instructions | claude-sonnet-5 | 1 | 10.00 | 1.00 |
| instructions | claude-opus-4-8 | 1 | 9.00 | 2.00 |
| instructions | claude-haiku-5-5 | 1 | 9.00 | 3.00 |
| instructions | claude-opus-5-5 | 1 | 8.00 | 4.00 |
| instructions | claude-sonnet-5-5 | 1 | 8.00 | 5.00 |
| reading_passage | claude-sonnet-5 | 5 | 9.20 | 2.20 |
| reading_passage | claude-opus-5-5 | 5 | 9.20 | 2.80 |
| reading_passage | claude-sonnet-5-5 | 5 | 7.80 | 3.20 |
| reading_passage | claude-opus-4-8 | 5 | 7.80 | 3.40 |
| reading_passage | claude-haiku-5-5 | 5 | 8.40 | 3.40 |
| vocab_list | claude-opus-5-5 | 5 | 9.00 | 2.00 |
| vocab_list | claude-sonnet-5-5 | 5 | 9.20 | 2.40 |
| vocab_list | claude-opus-4-8 | 5 | 8.80 | 3.00 |
| vocab_list | claude-sonnet-5 | 5 | 8.80 | 3.00 |
| vocab_list | claude-haiku-5-5 | 5 | 8.20 | 4.60 |

## Cost / latency

| Model | n | avg duration (ms) | avg cost (USD) | total cost (USD) | avg output chars |
|---|---|---|---|---|---|
| claude-haiku-5-5 | 47 | 7275 | 0.0012 | 0.0560 | 552 |
| claude-opus-4-8 | 47 | 10608 | 0.0306 | 1.4399 | 584 |
| claude-opus-5-5 | 47 | 7487 | 0.0310 | 1.4549 | 558 |
| claude-sonnet-5 | 47 | 4499 | 0.0121 | 0.5690 | 543 |
| claude-sonnet-5-5 | 47 | 3583 | 0.0121 | 0.5668 | 572 |

## Notable judge quotes (worst items)

- **wb-r-exercises-c70ff50c** (mean overall 6.6) — worst: `claude-opus-4-8` scored 5: Inserts （円グラフ）（帯グラフ）（棒グラフ）（折れ線グラフ） directly under each blank, effectively filling in the answers. Adds furigana 書(か) that is not in the image. Misreads 2004年11月 as 2004年6月. Omits (%) and the y-axis values for chart 4. Statement furigana is otherwise correct and the word bank is complete.
- **wb-p-0070** (mean overall 6.8) — worst: `claude-opus-4-8` scored 5: Adds the same unprinted furigana as A (聞, 大学生, 友人, 買, 学年, 質問作成, 答, 出, sidebar 質問), and also invents 心(こころ) and 体(からだ) in the footer. 回答形式(かいとう) and 肯定文(こうてい) have the reading attached to the wrong span. Heavy &nbsp; clutter and extra bolding on the number markers.
- **wb-p-0073** (mean overall 6.8) — worst: `claude-opus-4-8` scored 3: Base text and word box are correct, but furigana is added to nearly every kanji (企業(きぎょう), 多(おお), 人(ひと), 働(はたら) in the footer, etc.). The image has only about ten furigana glosses, so most are invented. Also adds an emoji and bold not in the source.
- **wb-p-0072** (mean overall 7.0) — worst: `claude-opus-4-8` scored 5: Base text correct and every printed furigana is present. But it adds readings to nearly every kanji where the page has none: 日本(にほん), 日本人(にほんじん), 多(おお), 人(ひと), 中(なか), 高(たか), 店(みせ), 言(い), 長(なが), 名前(なまえ), 買(か), 見(み), 聞(き), 後(あと), 食(た), and 次(つぎ) in '次のような'. Bold 72 matches the page; list structure is good.
- **tb-p-0069** (mean overall 7.2) — worst: `claude-sonnet-5-5` scored 6: Invents furigana not on the page: 入(い), a second 郷(ごう), and 従(したが); only the first 郷, 敷 and 和也 carry furigana. Misses the bold ものの in section 4 examples, though bold in sections 5 and 6 is correct. Side tab (ユニット4 ことばと文化) included. Underline on なんてったって and the second blank lines are not shown.
