# slop-lint — agent skill: de-slop rewriting

`slop-lint` (CLI, single file `slop_lint.py`) **detects** AI-register slop.
This skill tells you how to **rewrite** what it flags. Workflow:

1. Run `slop-lint check draft.txt` (or `--json`).
2. For each flagged line, pick a rung on the reading-level ladder below and rewrite.
3. Re-run until `plainness` passes your `--fail-under` gate.

## The ladder

Match the rung to the audience. When unsure, default to **engineer**.

### ELI5 — explain it like I'm five

Use for: general readers, docs, landing pages, anything public-facing.

Prompt template:

```
Rewrite the passage below so a smart 10-year-old gets it on first read.
- Max 20 words per sentence. One idea per sentence.
- Replace every abstract noun with a concrete verb or example.
- Delete these words outright: leverage, delve, robust, seamless, holistic,
  synergy, paradigm, landscape, realm, furthermore, moreover, additionally,
  utilize, facilitate, crucial, pivotal, noteworthy, vibrant, intricate,
  meticulously, testament, beacon, dynamic, ever-evolving, cutting-edge.
- No hedge piles: pick one — state it or cut it.
- If a sentence starts with "In today's fast-paced", delete the opener.

PASSAGE:
<flagged text>
```

### Engineer — precise, no filler

Use for: READMEs, code comments, technical docs, commit messages, PR descriptions.

Prompt template:

```
Rewrite the passage below for a working engineer who is skimming.
- Max 25 words per sentence. Short paragraphs.
- Lead with the concrete claim: what does it do, what changed, what breaks.
- Kill buzzwords (leverage→use, utilize→use, facilitate→let/help,
  robust→works when X fails, seamless→no manual steps, holistic→all of it).
- Cut hedges unless the uncertainty is the point; then state it once, plainly.
- Keep technical terms; delete everything that only sounds technical.

PASSAGE:
<flagged text>
```

### One-liner — the whole point in one breath

Use for: TL;DRs, commit subjects, changelog entries, status updates.

Prompt template:

```
Compress the passage below into ONE sentence under 25 words.
- Subject, verb, object. No setup clause, no "in order to".
- Drop every adjective that isn't load-bearing.
- If the result sounds like marketing, you failed — try again drier.

PASSAGE:
<flagged text>
```

### 中文 — 去 AI 味改写 (v0.2.0)

Use for: Chinese drafts flagged with `zh-*` rules. The CLI's Chinese word
lists (L1/L2) and behavioral norms are adapted from the de-ai-smell skill
(MIT, xiaoshuai1024/skills).

Prompt template:

```
把下面这段中文改成真人说话的语气，像在工位上跟同事聊天，不要像周报念稿。
- L1 禁词直接删掉或换具体说法：赋能→帮 X 做成什么；闭环→完整回路；沉淀→攒下/留下；
  打通→连上/对接；兜底→回退/降级；说白了/先说/总之→删掉直接说结论；
  至关重要→换具体影响；一句话/一件事/踩一遍→删掉或换具体所指。
- 句式红线必须整句重写，不许只换词：
  「不是 A，而是 B」→ 改成直陈（正面陈述 / 先后动作 / 因果句）；
  破折号全篇最多留 2 处，其余换逗号/句号或拆句；
  的链 ≥3 拆句；「进行/作出/加以 + 动词」删掉虚动词直接用动词；
  「结论很明确：」这类形容词+冒号预判删掉，内容直接成句。
- 套话开场（综上所述/众所周知/先聊聊）删掉直接进正题；
  套话收尾（以上就是/希望对你有帮助/未来可期）删掉，让内容自然结束。
- 「研究表明/数据显示」没有真实来源就删掉，不许编造来源。
- 保真：删套话可以，造事实不行。原文没说的，输出不许说。

TEXT:
<flagged text>
```

Then re-run `slop-lint check` — the score is the referee, not your taste.

## Rules of thumb (all rungs)

- **Buzzword → concrete swap cheat sheet:** leverage→use · utilize→use · delve→dig into / look at · robust→holds up when X · seamless→no extra steps · holistic→whole · synergy→working together · paradigm→model / way · landscape→field · realm→area · furthermore/moreover/additionally→and, or just start the sentence · foster→help grow · elevate→raise / improve · navigate→handle · underscore→show · unlock the potential→makes possible.
- **Long sentence fix:** split at the "and/which/that" joint. If it survives splitting, it wasn't too long.
- **Hedge fix:** "might arguably perhaps" → pick the strongest true claim and state it. If you genuinely don't know, say "unknown" once.
- **Never** add new buzzwords while rewriting. Re-run `slop-lint check` after — the score is the referee, not your taste.
