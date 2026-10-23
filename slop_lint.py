#!/usr/bin/env python3
"""slop-lint: a bilingual readability linter for AI-generated text.

AI output has a recognizable register -- in English: marathon sentences,
abstraction buzzwords ("leverage", "delve", "tapestry", "robust",
"furthermore", "in today's fast-paced ..."), hedge piles; in Chinese:
PPT nouns (赋能/闭环/抓手/打通/对齐/沉淀), 口头禅 (一句话/一件事/踩一遍),
"不是 A，而是 B" contrast structures, em-dash spam (破折号每篇 ≤2 处),
translationese (的-chain, 虚动词, 预判冒号), and 套话开场/收尾.

slop-lint scores text on plainness and flags the offending lines so a
human (or agent) can de-slop before shipping.

The Chinese rule set (L1/L2 severity + behavioral norms) is adapted from
the de-ai-smell skill (MIT, xiaoshuai1024/skills); scene-specific groups
for video narration (课件指代 / 写稿思路词 / 刀改比喻 / 这支片) are
intentionally excluded -- slop-lint targets written prose.

Usage:
    slop-lint check file.txt
    cat file.txt | slop-lint check
    slop-lint check file.txt --json
    slop-lint check file.txt --fail-under 80   # exit 1 if score < 80 (CI)
    slop-lint check draft.md --lang zh         # force Chinese rules

Stdlib only, Python 3.9+.
"""

import argparse
import io
import json
import re
import sys

VERSION = "0.2.0"

# ----------------------------------------------------------------------------
# Built-in word lists -- English
# ----------------------------------------------------------------------------

# ~45 AI-tell words/phrases, matched case-insensitively with word boundaries.
BUZZWORDS = [
    "additionally", "beacon", "comprehensive", "crucial", "cutting-edge",
    "deep dive", "delve", "delve into", "dynamic", "elevate", "embark",
    "empower", "ever-evolving", "facilitate", "fast-paced", "foster",
    "furthermore", "game-changer", "holistic", "in essence",
    "in today's fast-paced", "intricate", "landscape", "leverage",
    "meticulously", "moreover", "multifaceted", "navigate", "noteworthy",
    "paradigm", "pivotal", "realm", "revolutionize", "robust", "seamless",
    "state-of-the-art", "synergy", "tapestry", "testament", "underscore",
    "unlock", "unlock the potential", "unleash", "utilize", "vibrant",
]

# Hedge words/phrases; density matters more than presence.
HEDGES = [
    "arguably", "generally", "in a sense", "kind of", "maybe", "might",
    "perhaps", "possibly", "potentially", "quite", "rather", "relatively",
    "seems", "somewhat", "sort of", "typically", "usually",
]

LONG_SENTENCE_WORDS = 25  # sentences longer than this get flagged

# ----------------------------------------------------------------------------
# Built-in word lists -- Chinese (adapted from de-ai-smell, MIT)
# ----------------------------------------------------------------------------

# L1: absolute bans -- flagged whenever they appear, no exceptions.
# Literal phrases; a few need regex forms (see _ZH_L1 regexes) for exemptions.
ZH_L1_WORDS = [
    # A. 口语套话连接词
    "说白了", "先说", "根子", "扎眼", "总之", "总而言之",
    # B. PPT 名词 / 新晋 AI 网络黑话
    "兜底", "铁证", "赋能", "闭环", "抓手", "打通", "对齐", "拉通",
    "洞察", "沉淀", "底层逻辑", "全生命周期", "降本增效", "技术底座",
    # I. AI 口头禅
    "一句话", "一件事", "踩一遍", "一整个", "拆开看",
    # 拟人禁词
    "出身",
    # 套话开场/收尾里的高频词 (also covered by structural rules)
    "值得注意", "值得一提", "我的判断是", "恰恰",
    # C. 空洞强调词
    "至关重要", "不可或缺", "意义深远", "真正的", "核心在于", "终极",
    "护城河", "分水岭", "定时炸弹",
]

# L1 regex forms with exemptions:
# - 拆 teardown 义全禁, but literal physical senses stay legal:
#   拆分/拆除/拆包/拆迁/拆装/拆散/拆掉/拆穿
# - 记账类比 (X 的账/这笔账/算账/算总账/翻旧账) 全禁, but literal senses stay:
#   账单/账号/账户/分账/对账/结算账期/账务 (checked via _covered_by_exempt).
_ZH_CHAI_RE = re.compile(r"拆(?![分除包迁装散掉穿])")
_ZH_LEDGER_RE = re.compile(r"的账|这笔账|算账|算总账|翻旧账")
_ZH_L1_EXEMPT = [
    "账单", "账号", "账户", "分账", "对账", "结算账期", "账务",
]

# L2: advisory -- meaningful words AI misuses for 铺垫升华/戏剧化.
# Flagged as suggestions; a human decides whether the usage is substantive.
ZH_L2_WORDS = [
    "本质", "本质上", "澄清", "真相", "撕开",
    "揭开面纱", "戳破", "剥开",
    "之一",                       # 滥用 "之一" (one-of translationese)
    "击穿", "打穿", "接住", "穿透", "收紧",   # 物理动词 + 抽象宾语
    "守住", "守好", "守牢", "看住", "护住",
]

# G. 句式红线 -- "不是 A，而是 B" and variants (AI 句型第一名).
# 纯否定 + 让步 ("它不是最快的，但最稳") is NOT matched and stays legal.
# The middle may contain ，/、/： (clause separators) but not 。！？； (sentence
# boundaries) -- "不是A，而是B" is normally written with a comma.
_ZH_MID = r"[^。！？；\n]{1,40}?"
_ZH_NOTBUT_PATTERNS = [
    re.compile(r"(?<!这)不是" + _ZH_MID + r"而是"),  # 不是A，而是B (这不是… covered below)
    re.compile(r"没有" + _ZH_MID + r"而是"),   # 没有A，而是B
    re.compile(r"并非" + _ZH_MID + r"而是"),   # 并非A，而是B
    re.compile(r"不靠" + _ZH_MID + r"靠"),     # 不靠A，靠B
    re.compile(r"这不是" + _ZH_MID + r"是"),   # 这不是A，是B / 这不是A，而是B
    re.compile(_ZH_MID + r"，而不是"),          # A，而不是B
]
# 否定句首 ("不是…/没有…/并非…" 起句制造顿悟铺垫) -- same family, L2 advisory.
_ZH_NEGOPEN_RE = re.compile(r"^\s*(不是|没有|并非)")

# 破折号 quota: ≤2 per text (ideal 0). A "——" pair counts as one dash.
_EMDASH_RE = re.compile(r"——|—")
EMDASH_LIMIT = 2

# J. 翻译腔句法 (translationese) -- L2 advisory.
_ZH_DECHAIN_RE = re.compile(r"的[^，。！？；：\n的]{1,12}的[^，。！？；：\n的]{1,12}的")
_ZH_EMPTYVERB_RE = re.compile(
    r"(进行|作出|做出|加以)(?![时中前后了着过])[\u4e00-\u9fa5]{1,6}")
_ZH_PREJUDGE_RE = re.compile(
    r"(很|非常|十分|特别|相当)(明确|简单|清楚|清晰|明显|重要|关键|容易|困难)[:：]")
_ZH_ZHIYI = "之一"

# D/E. 套话开场 / 套话收尾.
_ZH_OPENINGS = [
    "综上所述", "由此可见", "不难看出", "需要指出的是", "不难发现",
    "毋庸置疑", "众所周知", "不言而喻", "诚然",
    "在当今这个快节奏的时代", "在这个信息爆炸的时代",
    "先泼盆冷水", "先给大家", "先聊聊", "先问一句",
]
_ZH_CLOSINGS = [
    "以上就是", "希望对你有帮助", "希望本文对您有所帮助", "你学会了吗",
    "随着AI不断进化", "随着 AI 不断进化", "未来可期",
]
# 无源权威铺垫 -- audit-only: flagged, never auto-"fixed" with fake sources.
_ZH_UNSOURCED = ["研究表明", "数据显示", "业内人士指出", "有评论认为"]

# ----------------------------------------------------------------------------
# Analysis
# ----------------------------------------------------------------------------


def _compile_phrase_list(phrases):
    """Build one case-insensitive regex matching any phrase as whole words.

    Longer phrases first so "unlock the potential" wins over "unlock".
    """
    ordered = sorted(phrases, key=len, reverse=True)
    # re.escape turns spaces into "\ "; swap those for \s+ (whitespace-flexible).
    alts = [re.escape(p).replace("\\ ", r"\s+") for p in ordered]
    return re.compile(r"\b(?:%s)\b" % "|".join(alts), re.IGNORECASE)


_BUZZ_RE = _compile_phrase_list(BUZZWORDS)
_HEDGE_RE = _compile_phrase_list(HEDGES)
_ZH_L1_RE = re.compile("|".join(
    sorted((re.escape(w) for w in ZH_L1_WORDS), key=len, reverse=True)))
_ZH_L2_RE = re.compile("|".join(
    sorted((re.escape(w) for w in ZH_L2_WORDS), key=len, reverse=True)))
_ZH_OPENING_RE = re.compile("|".join(
    sorted((re.escape(w) for w in _ZH_OPENINGS), key=len, reverse=True)))
_ZH_CLOSING_RE = re.compile("|".join(
    sorted((re.escape(w) for w in _ZH_CLOSINGS), key=len, reverse=True)))
_ZH_UNSOURCED_RE = re.compile("|".join(
    sorted((re.escape(w) for w in _ZH_UNSOURCED), key=len, reverse=True)))

_CJK_RE = re.compile(r"[\u4e00-\u9fa5]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")
# Sentence boundary: ASCII terminators need following whitespace (so
# "U.S." survives); CJK terminators split even without whitespace.
_BOUND_RE = re.compile(r"(?<=[.!?;])\s+|(?<=[。！？；])")


def count_syllables(word):
    """Estimate syllables by counting vowel groups (minimum 1)."""
    word = word.lower().strip("'-")
    if not word:
        return 0
    n = len(_VOWEL_GROUP_RE.findall(word))
    # Silent trailing 'e' usually doesn't add a syllable.
    if word.endswith("e") and n > 1 and not word.endswith(("ee", "ye", "oe")):
        n -= 1
    return max(n, 1)


def has_cjk(text):
    """True when the text contains any CJK characters."""
    return bool(_CJK_RE.search(text))


def effective_words(sentence):
    """Word count with CJK awareness: each CJK char counts as half a word.

    A 50-char Chinese sentence carries roughly the load of a 25-word
    English one, so the same LONG_SENTENCE_WORDS limit stays meaningful.
    """
    latin = len(_WORD_RE.findall(sentence))
    cjk = len(_CJK_RE.findall(sentence))
    return latin + cjk / 2.0


_FENCE_START_RE = re.compile(r"^\s*(`{3,}|~{3,})")
# Lines that start a new markdown block: keep them as paragraph boundaries
# so list items / headings / quotes don't merge into mega-sentences.
_BLOCK_START_RE = re.compile(r"^\s*(#{1,6}\s|>\s?|[-*+]\s|\d+[.)]\s|\|)")


def _strip_fenced_code(text):
    """Drop fenced code blocks (``` / ~~~); code is not prose."""
    out, in_fence = [], False
    for line in text.splitlines():
        if _FENCE_START_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def _paragraphs_with_lines(text):
    """Group hard-wrapped lines into paragraphs.

    Consecutive non-blank lines form one paragraph (a line ending without
    a blank line continues the paragraph); blank lines and markdown block
    starts (headings, list items, quotes, tables) are boundaries.
    Returns [[(line_text, line_number), ...], ...].
    """
    paras, buf = [], []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            if buf:
                paras.append(buf)
                buf = []
            continue
        if _BLOCK_START_RE.match(line):
            if buf:
                paras.append(buf)
            buf = [(line, i)]
            continue
        buf.append((line, i))
    if buf:
        paras.append(buf)
    return paras


def _sentence_bounds(para):
    """Yield (start, end) offsets of sentences in a paragraph."""
    bounds = [0]
    bounds += [m.end() for m in _BOUND_RE.finditer(para)]
    bounds.append(len(para))
    for a, b in zip(bounds, bounds[1:]):
        if para[a:b].strip():
            yield a, b


def split_sentences(text):
    """Split text into sentences; each entry is (text, line_number).

    Fenced code blocks are excluded. Hard-wrapped lines are joined into
    paragraphs first, so a long sentence broken across lines is still
    measured whole. The line number is where the sentence starts.
    """
    sentences = []
    for lines in _paragraphs_with_lines(_strip_fenced_code(text)):
        para = " ".join(t for t, _ in lines)
        offsets = []  # char offset where each source line starts in para
        pos = 0
        for t, _ in lines:
            offsets.append(pos)
            pos += len(t) + 1  # +1 for the joining space
        for a, b in _sentence_bounds(para):
            part = para[a:b].strip()
            if not part:
                continue
            # Attribute to the source line where the sentence's first
            # non-space char sits (CJK splits are zero-width, so `a` may
            # point at the joining space between hard-wrapped lines).
            sa = a
            while sa < b and para[sa] in " \t":
                sa += 1
            lineno = lines[0][1]
            for idx, off in enumerate(offsets):
                if off <= sa:
                    lineno = lines[idx][1]
                else:
                    break
            sentences.append((part, lineno))
    return sentences


def find_hits(pattern, text):
    """Return the matched phrase strings (as written in text)."""
    return [m.group(0) for m in pattern.finditer(text)]


def _ledger_literal_spans(text):
    """Spans of literal (non-metaphor) 账 usages: 账单/账号/账户/分账/对账/结算账期/账务."""
    spans = []
    for phrase in _ZH_L1_EXEMPT:
        idx = text.find(phrase)
        while idx != -1:
            spans.append((idx, idx + len(phrase)))
            idx = text.find(phrase, idx + 1)
    return spans


def _dedup_spans(candidates):
    """Drop overlapping candidates, keeping the highest-priority first.

    Each candidate is (start, end, priority, finding_dict). Higher priority
    wins; ties keep the longer span.
    """
    kept = []
    for start, end, prio, finding in sorted(
            candidates, key=lambda c: (-c[2], -(c[1] - c[0]))):
        if any(start < k[1] and end > k[0] for k in kept):
            continue
        kept.append((start, end, prio, finding))
    # Restore document order.
    return [k[3] for k in sorted(kept, key=lambda k: (k[3]["line"], k[0]))]


def _zh_findings(text, stripped):
    """Run the Chinese rule set; return (findings, l1, l2, structure)."""
    findings, l1, l2, structure = [], 0, 0, 0

    # Phrase rules, scanned per sentence for line attribution.
    # Span dedup runs per sentence (offsets are sentence-relative).
    for sentence, line_no in split_sentences(text):
        candidates = []

        def add_phrase(rule, severity, message, start, end, prio):
            candidates.append((start, end, prio, {
                "line": line_no, "rule": rule, "severity": severity,
                "message": message,
            }))

        # zh-l1 literal words (priority 3 = highest).
        for m in _ZH_L1_RE.finditer(sentence):
            add_phrase("zh-l1", "L1",
                       'AI-flavor word (L1, must rewrite): "%s"' % m.group(0),
                       m.start(), m.end(), 3)
        # 拆 teardown 义 (with literal-physical exemptions).
        for m in _ZH_CHAI_RE.finditer(sentence):
            add_phrase("zh-l1", "L1",
                       'AI-flavor word (L1, must rewrite): "%s…"' % m.group(0),
                       m.start(), m.end(), 3)
        # 记账类比 (with literal 账单/账号/账户/分账/对账/结算账期/账务 exemptions).
        for m in _ZH_LEDGER_RE.finditer(sentence):
            zhang = m.start() + m.group(0).index("账")
            if any(s <= zhang < e
                   for s, e in _ledger_literal_spans(sentence)):
                continue
            add_phrase("zh-l1", "L1",
                       'AI-flavor word (L1, must rewrite): "%s"' % m.group(0),
                       m.start(), m.end(), 3)
        # zh-l2 advisory words (priority 2).
        for m in _ZH_L2_RE.finditer(sentence):
            add_phrase("zh-l2", "L2",
                       'Risky word (L2, review): "%s"' % m.group(0),
                       m.start(), m.end(), 2)
        # 套话开场 / 套话收尾 (priority 1; zh-l1 wins overlaps like 值得注意).
        for m in _ZH_OPENING_RE.finditer(sentence):
            add_phrase("zh-opening", "L1",
                       'Cliché opening: "%s"' % m.group(0),
                       m.start(), m.end(), 1)
        for m in _ZH_CLOSING_RE.finditer(sentence):
            add_phrase("zh-closing", "L1",
                       'Cliché closing: "%s"' % m.group(0),
                       m.start(), m.end(), 1)
        # 无源权威铺垫 (priority 1, L2).
        for m in _ZH_UNSOURCED_RE.finditer(sentence):
            add_phrase("zh-unsourced", "L2",
                       'Unsourced authority: "%s" (flag or cite, never invent)'
                       % m.group(0),
                       m.start(), m.end(), 1)

        for f in _dedup_spans(candidates):
            findings.append(f)
            if f["rule"] == "zh-l1":
                l1 += 1
            elif f["rule"] == "zh-l2":
                l2 += 1
            else:  # zh-opening / zh-closing / zh-unsourced
                structure += 1

        # "不是 A，而是 B" family (L1, no span dedup needed).
        for pat in _ZH_NOTBUT_PATTERNS:
            for m in pat.finditer(sentence):
                findings.append({
                    "line": line_no, "rule": "zh-not-but", "severity": "L1",
                    "message": 'Contrast cliché "不是 A，而是 B": "%s…"' % m.group(0)[:24],
                })
                structure += 1
        # 否定句首 (L2 advisory).
        if _ZH_NEGOPEN_RE.match(sentence):
            findings.append({
                "line": line_no, "rule": "zh-negation-opening",
                "severity": "L2",
                "message": "Negation opening (顿悟铺垫); state the point directly",
            })
            structure += 1
        # 翻译腔 (L2 advisory).
        if _ZH_DECHAIN_RE.search(sentence):
            findings.append({
                "line": line_no, "rule": "zh-translationese", "severity": "L2",
                "message": "Translationese: 的-chain (3+ 的); split the sentence",
            })
            structure += 1
        if _ZH_EMPTYVERB_RE.search(sentence):
            m = _ZH_EMPTYVERB_RE.search(sentence)
            findings.append({
                "line": line_no, "rule": "zh-translationese", "severity": "L2",
                "message": 'Translationese: empty verb "%s"; use the verb directly'
                           % m.group(0),
            })
            structure += 1
        if _ZH_PREJUDGE_RE.search(sentence):
            m = _ZH_PREJUDGE_RE.search(sentence)
            findings.append({
                "line": line_no, "rule": "zh-translationese", "severity": "L2",
                "message": 'Translationese: adjective + 冒号预判 ("%s"); drop the setup'
                           % m.group(0),
            })
            structure += 1
        if _ZH_ZHIYI in sentence:
            findings.append({
                "line": line_no, "rule": "zh-translationese", "severity": "L2",
                "message": 'Translationese: overused "之一"; judge or list directly',
            })
            structure += 1

    # 破折号 quota: ≤2 per text (ideal 0). Scanned on prose (no code fences).
    dashes = list(_EMDASH_RE.finditer(stripped))
    if len(dashes) > EMDASH_LIMIT:
        for m in dashes[EMDASH_LIMIT:]:
            line_no = stripped.count("\n", 0, m.start()) + 1
            findings.append({
                "line": line_no, "rule": "zh-em-dash", "severity": "L1",
                "message": "Em-dash quota exceeded: %d in text (limit %d)"
                           % (len(dashes), EMDASH_LIMIT),
            })
        structure += 1

    findings.sort(key=lambda f: (f["line"], f["rule"]))
    return findings, l1, l2, structure


def analyze(text, lang="auto"):
    """Score text and collect findings.

    lang: "auto" (detect CJK), "zh" (force Chinese rules), "en" (skip them).
    Returns (result_dict) with keys: plainness, grade, stats, findings.
    """
    findings = []
    long_sentences = 0
    buzzword_hits = 0
    hedge_hits = 0
    zh_l1 = zh_l2 = zh_structure = 0

    sentences = split_sentences(text)
    stripped = _strip_fenced_code(text)
    total_words = 0
    total_syllables = 0
    total_cjk = 0

    for sentence, line_no in sentences:
        words = _WORD_RE.findall(sentence)
        cjk = len(_CJK_RE.findall(sentence))
        total_cjk += cjk
        ew = len(words) + cjk / 2.0
        total_words += len(words)
        total_syllables += sum(count_syllables(w) for w in words)

        if ew > LONG_SENTENCE_WORDS:
            long_sentences += 1
            if cjk:
                msg = "Sentence has %d effective words (limit %d)" % (
                    round(ew), LONG_SENTENCE_WORDS)
            else:
                msg = "Sentence has %d words (limit %d)" % (
                    len(words), LONG_SENTENCE_WORDS)
            findings.append({
                "line": line_no,
                "rule": "long-sentence",
                "message": msg,
            })

        seen = set()
        for hit in find_hits(_BUZZ_RE, sentence):
            key = hit.lower()
            if key in seen:
                continue
            seen.add(key)
            buzzword_hits += 1
            findings.append({
                "line": line_no,
                "rule": "buzzword",
                "message": 'AI-tell buzzword: "%s"' % hit,
            })

        for hit in find_hits(_HEDGE_RE, sentence):
            hedge_hits += 1
            findings.append({
                "line": line_no,
                "rule": "hedge",
                "message": 'Hedge word: "%s"' % hit,
            })

    use_zh = (lang == "zh") or (lang == "auto" and has_cjk(text))
    if use_zh:
        zh_f, zh_l1, zh_l2, zh_structure = _zh_findings(text, stripped)
        findings.extend(zh_f)
        findings.sort(key=lambda f: (f["line"], f["rule"]))

    # Flesch-style reading ease from the syllable heuristic (Latin text only;
    # it is meaningless for Chinese, so it only feeds the score for
    # Latin-dominant text).
    if sentences and total_words:
        avg_words = total_words / len(sentences)
        avg_syll = total_syllables / total_words
        reading_ease = 206.835 - 1.015 * avg_words - 84.6 * avg_syll
        reading_ease = round(max(0.0, min(100.0, reading_ease)), 1)
    else:
        reading_ease = 100.0

    # Score: start at 100, deduct.
    score = 100.0
    score -= min(20.0, 4.0 * long_sentences)
    score -= min(30.0, 3.0 * (buzzword_hits + zh_l1))
    score -= min(15.0, 5.0 * zh_structure)
    score -= min(10.0, 1.0 * (hedge_hits + zh_l2))
    if reading_ease < 60 and total_words >= total_cjk:
        score -= min(25.0, (60.0 - reading_ease) * 0.5)
    plainness = int(round(max(0.0, min(100.0, score))))

    if plainness >= 90:
        grade = "plain"
    elif plainness >= 75:
        grade = "mostly plain"
    elif plainness >= 60:
        grade = "needs polish"
    else:
        grade = "slop"

    return {
        "plainness": plainness,
        "grade": grade,
        "stats": {
            "sentences": len(sentences),
            "words": total_words,
            "long_sentences": long_sentences,
            "buzzword_hits": buzzword_hits,
            "hedge_hits": hedge_hits,
            "zh_l1_hits": zh_l1,
            "zh_l2_hits": zh_l2,
            "zh_structure_hits": zh_structure,
            "reading_ease": reading_ease,
        },
        "findings": findings,
    }


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------


def format_human(result):
    out = io.StringIO()
    out.write("plainness: %d/100 (%s)\n" % (result["plainness"], result["grade"]))
    s = result["stats"]
    out.write(
        "sentences: %d  words: %d  reading ease: %.1f\n"
        % (s["sentences"], s["words"], s["reading_ease"])
    )
    out.write(
        "long sentences: %d  buzzwords: %d  hedges: %d\n"
        % (s["long_sentences"], s["buzzword_hits"], s["hedge_hits"])
    )
    if s["zh_l1_hits"] or s["zh_l2_hits"] or s["zh_structure_hits"]:
        out.write(
            "chinese: L1 %d  L2 %d  structure %d\n"
            % (s["zh_l1_hits"], s["zh_l2_hits"], s["zh_structure_hits"])
        )
    if result["findings"]:
        out.write("\nfindings:\n")
        out.write("%-6s %-20s %s\n" % ("LINE", "RULE", "DETAIL"))
        out.write("%-6s %-20s %s\n" % ("----", "----", "------"))
        for f in result["findings"]:
            rule = f["rule"]
            if f.get("severity"):
                rule = "%s[%s]" % (rule, f["severity"])
            out.write("%-6d %-20s %s\n" % (f["line"], rule, f["message"]))
    else:
        out.write("\nNo findings. Nice and plain.\n")
    return out.getvalue()


def format_json(result):
    return json.dumps(result, indent=2, ensure_ascii=False) + "\n"


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(
        prog="slop-lint",
        description="Bilingual (EN/ZH) readability linter for AI-generated text.",
    )
    p.add_argument("--version", action="version", version="slop-lint " + VERSION)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="Check a file (or stdin) for AI-register slop.")
    c.add_argument("file", nargs="?", help="File to check; reads stdin if omitted.")
    c.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    c.add_argument(
        "--fail-under", type=int, default=None, metavar="N",
        help="Exit 1 when plainness score is below N (for CI).",
    )
    c.add_argument(
        "--lang", choices=["auto", "en", "zh"], default="auto",
        help="Rule language: auto (detect CJK), en (English only), "
             "zh (also run Chinese rules). Default: auto.",
    )
    return p


def cmd_check(args):
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()

    result = analyze(text, lang=args.lang)

    if args.json:
        sys.stdout.write(format_json(result))
    else:
        sys.stdout.write(format_human(result))

    if args.fail_under is not None and result["plainness"] < args.fail_under:
        return 1
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return cmd_check(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
