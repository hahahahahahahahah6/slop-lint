# slop-lint

You can spot AI-written text in three seconds: the 60-word sentence that never lands, the "leverage the robust tapestry" filler, the "furthermore / moreover / additionally" drumbeat, the hedge pile ("might arguably perhaps be"). Grammar checkers don't catch any of this — the grammar is perfect; the *register* is the problem. **slop-lint** is a tiny readability linter that scores text on plainness and flags the offending lines, so you (or your agent) can de-slop a draft before it ships.

**v0.2.0 adds a full Chinese rule set** — AI-flavor word lists (L1 absolute bans / L2 advisories), the "不是 A，而是 B" contrast cliché, an em-dash quota (≤2 per text), translationese patterns, and 套话开场/收尾 detection. One tool, two languages, zero dependencies.

## Install

```bash
pip install slop-lint
```

Or from source:

```bash
git clone https://github.com/hahahahahahahahah6/slop-lint
cd slop-lint
python3 slop_lint.py check draft.txt
```

Or just grab the single file — it's stdlib-only, no dependencies:

```bash
curl -O https://raw.githubusercontent.com/hahahahahahahahah6/slop-lint/main/slop_lint.py
python3 slop_lint.py check draft.txt
```

Python 3.9+. The examples below write `slop-lint` — that's shorthand for
`python3 slop_lint.py` (symlink it onto your PATH as `slop-lint` if you
like).

## Usage

```bash
slop-lint check draft.txt          # check a file
cat draft.txt | slop-lint check     # or pipe stdin
slop-lint check draft.txt --json   # machine-readable output
slop-lint check draft.txt --fail-under 80   # exit 1 when score < 80 (for CI)
slop-lint check draft.md --lang zh # force Chinese rules (default: auto-detect)
```

`--lang` takes `auto` (detect CJK, default), `en` (English rules only), or
`zh` (also run the Chinese rules).

What it checks:

**English rules**

1. **Long sentences** — anything over 25 words gets flagged (`long-sentence`).
2. **AI-tell buzzwords** — ~45 built-in words/phrases (`leverage`, `delve`, `tapestry`, `robust`, `furthermore`, `in today's fast-paced`, `unlock the potential`, …), case-insensitive, reported with the offending word (`buzzword`).
3. **Reading ease** — Flesch-style score via a simple vowel-group syllable heuristic, folded into the plainness score.
4. **Hedge density** — `maybe`, `perhaps`, `generally`, `arguably`, `somewhat`, and friends (`hedge`).

**Chinese rules** (run when CJK text is detected, or with `--lang zh`)

5. **L1 absolute bans** (`zh-l1`) — words that must be rewritten on sight: PPT nouns (赋能/闭环/抓手/打通/对齐/沉淀/底层逻辑), 口头禅 (一句话/一件事/踩一遍/一整个/拆开看), teardown-义 拆 (literal senses like 拆包/拆散 stay legal), 记账类比 (literal 账单/账号/账户/对账 stay legal), 空洞强调词 (至关重要/不可或缺/护城河/分水岭).
6. **L2 advisories** (`zh-l2`) — meaningful words AI misuses for drama: 本质/澄清/真相/撕开, overused 之一, 物理动词+抽象宾语 (击穿/接住), 守住/看住 family. Flagged for human review, not auto-condemned.
7. **"不是 A，而是 B"** (`zh-not-but`, L1) — the #1 AI sentence pattern in Chinese, plus variants (没有A而是B / 不靠A靠B / A而不是B). Pure negation + 让步 ("它不是最快的，但最稳") stays legal.
8. **Em-dash quota** (`zh-em-dash`, L1) — more than 2 em-dashes per text gets flagged (a `——` pair counts as one).
9. **Translationese** (`zh-translationese`, L2) — 的-chains (3+ 的), empty verbs (进行/作出/加以 + verb), adjective + 冒号预判 ("结论很明确：").
10. **Cliché openings/closings** (`zh-opening` / `zh-closing`, L1) — 综上所述/众所周知/先聊聊 …, 以上就是/希望对你有帮助/未来可期.
11. **Unsourced authority** (`zh-unsourced`, L2) — 研究表明/数据显示/业内人士指出: flagged for citing or cutting, never "fixed" by inventing a source.

Chinese sentences are split on 。！？； and measured in effective words (each CJK character counts as half a word), so the same 25-word limit stays meaningful across languages.

Example:

```
$ slop-lint check draft.txt
plainness: 45/100 (slop)
sentences: 3  words: 80  reading ease: 30.7
long sentences: 2  buzzwords: 24  hedges: 2

findings:
LINE   RULE           DETAIL
----   ----           ------
1      long-sentence  Sentence has 32 words (limit 25)
1      buzzword       AI-tell buzzword: "In today's fast-paced"
1      buzzword       AI-tell buzzword: "landscape"
1      buzzword       AI-tell buzzword: "crucial"
1      buzzword       AI-tell buzzword: "leverage"
1      buzzword       AI-tell buzzword: "cutting-edge"
1      buzzword       AI-tell buzzword: "unlock"
1      buzzword       AI-tell buzzword: "foster"
1      buzzword       AI-tell buzzword: "seamless"
1      buzzword       AI-tell buzzword: "robust"
1      buzzword       AI-tell buzzword: "comprehensive"
1      buzzword       AI-tell buzzword: "holistic"
2      long-sentence  Sentence has 41 words (limit 25)
2      buzzword       AI-tell buzzword: "Furthermore"
2      buzzword       AI-tell buzzword: "elevate"
2      buzzword       AI-tell buzzword: "delve"
2      buzzword       AI-tell buzzword: "intricate"
2      buzzword       AI-tell buzzword: "tapestry"
2      buzzword       AI-tell buzzword: "meticulously"
2      buzzword       AI-tell buzzword: "navigate"
2      buzzword       AI-tell buzzword: "ever-evolving"
2      buzzword       AI-tell buzzword: "synergy"
2      buzzword       AI-tell buzzword: "testament"
2      buzzword       AI-tell buzzword: "dynamic"
2      buzzword       AI-tell buzzword: "vibrant"
2      buzzword       AI-tell buzzword: "realm"
2      hedge          Hedge word: "might"
2      hedge          Hedge word: "arguably"
```

And a plain passage:

```
$ echo "Cats sleep most of the day. Give your cat fresh water every day." | slop-lint check
plainness: 100/100 (plain)
sentences: 2  words: 14  reading ease: 97.0
long sentences: 0  buzzwords: 0  hedges: 0

No findings. Nice and plain.
```

CI gate example — fail the build when a generated doc is too sloppy:

```bash
slop-lint check release-notes.md --fail-under 80
```

A Chinese example:

```
$ echo "在当今这个快节奏的时代，说白了，我们要赋能业务，实现降本增效。这不是运气，而是实力。" | slop-lint check
plainness: 81/100 (mostly plain)
sentences: 2  words: 0  reading ease: 100.0
long sentences: 0  buzzwords: 0  hedges: 0
chinese: L1 3  L2 0  structure 2

findings:
LINE   RULE                 DETAIL
----   ----                 ------
1      zh-l1[L1]            AI-flavor word (L1, must rewrite): "说白了"
1      zh-l1[L1]            AI-flavor word (L1, must rewrite): "赋能"
1      zh-l1[L1]            AI-flavor word (L1, must rewrite): "降本增效"
1      zh-not-but[L1]       Contrast cliché "不是 A，而是 B": "这不是运气，而是…"
1      zh-opening[L1]       Cliché opening: "在当今这个快节奏的时代"
```

## Differentiation

Grammar checkers (Grammarly, LanguageTool) fix grammar. That's a different problem: AI slop is *grammatically flawless*. What slop-lint targets is the AI **register** — the specific constellation of marathon sentences, abstraction buzzwords, and hedge piles that makes generated text instantly recognizable.

And it does it **bilingually**. Chinese AI-slop detectors exist (notably the excellent [de-ai-smell](https://github.com/xiaoshuai1024/skills) skill by xiaoshuai, MIT-licensed — slop-lint's Chinese word lists and behavioral norms are adapted from it, with attribution), but they ship Chinese-only docs and target article/narration workflows. slop-lint is:

- **One bilingual rule set** — English buzzword/hedge detection and Chinese L1/L2 + 句式红线 rules in a single stdlib-only file, with CJK-aware sentence splitting and word counting.
- **English docs** — the README, rule IDs, and finding messages are all in English, so it drops into English-language CI/agent pipelines without translation.
- **Severity-graded, not binary** — L1 (must rewrite) vs L2 (human review) mirrors how the source skill treats its word list; `--json` exposes severity per finding for programmatic triage.

It's also built for agents, not just humans:

- `--json` and `--fail-under` make it a CI gate for generated docs.
- The repo ships a **`SKILL.md`** agent skill with a reading-level ladder (ELI5 / engineer / one-liner, plus a Chinese rung): prompt templates an agent uses to *rewrite* flagged text. The CLI detects; the skill rewrites. Pair them in a loop: `slop-lint check` → rewrite with the skill → check again until the score passes.

## License

MIT — see [LICENSE](LICENSE).
