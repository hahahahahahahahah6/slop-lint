"""Smoke tests for slop-lint (stdlib only, unittest).

Run:  python3 -m unittest tests.test_smoke -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import slop_lint  # noqa: E402

SLOP_TEXT = (
    "In today's fast-paced digital landscape, it is crucial to leverage "
    "cutting-edge tools in order to unlock the potential of your workflow "
    "and foster a seamless experience that is robust, comprehensive, and "
    "holistic across every paradigm.\n"
    "Furthermore, one might argue that to truly elevate your productivity, "
    "you must delve into the intricate tapestry of modern software "
    "development and meticulously navigate its ever-evolving synergy, "
    "which is arguably a testament to the dynamic nature of this vibrant "
    "realm.\n"
    "Perhaps it is generally somewhat difficult to underscore the pivotal "
    "role of empowerment, but deep dives are nonetheless noteworthy.\n"
)

PLAIN_TEXT = (
    "Cats sleep most of the day.\n"
    "A cat needs about sixteen hours of sleep.\n"
    "Kittens play hard and nap after.\n"
    "Give your cat fresh water every day.\n"
)


def run_cli(argv, stdin_text=None):
    """Run main() capturing stdout; return (exit_code, stdout)."""
    old_stdin = sys.stdin
    buf = io.StringIO()
    try:
        if stdin_text is not None:
            sys.stdin = io.StringIO(stdin_text)
        with contextlib.redirect_stdout(buf):
            code = slop_lint.main(argv)
    finally:
        sys.stdin = old_stdin
    return code, buf.getvalue()


class TestScoring(unittest.TestCase):
    def test_slop_text_scores_low(self):
        result = slop_lint.analyze(SLOP_TEXT)
        self.assertLess(result["plainness"], 60, result)
        self.assertEqual(result["grade"], "slop")
        self.assertGreater(result["stats"]["long_sentences"], 0)
        self.assertGreater(result["stats"]["buzzword_hits"], 0)
        self.assertGreater(result["stats"]["hedge_hits"], 0)
        self.assertLess(result["stats"]["reading_ease"], 60)

    def test_plain_text_scores_high(self):
        result = slop_lint.analyze(PLAIN_TEXT)
        self.assertGreaterEqual(result["plainness"], 90, result)
        self.assertEqual(result["grade"], "plain")
        self.assertEqual(result["stats"]["long_sentences"], 0)
        self.assertEqual(result["stats"]["buzzword_hits"], 0)
        self.assertEqual(result["findings"], [])

    def test_empty_input_is_plain(self):
        result = slop_lint.analyze("")
        self.assertEqual(result["plainness"], 100)
        self.assertEqual(result["stats"]["reading_ease"], 100.0)

    def test_findings_carry_rule_ids_and_lines(self):
        result = slop_lint.analyze(SLOP_TEXT)
        rules = {f["rule"] for f in result["findings"]}
        self.assertTrue({"long-sentence", "buzzword", "hedge"} <= rules)
        lines = {f["line"] for f in result["findings"]}
        self.assertEqual(lines, {1, 2, 3})
        # Buzzword findings report the offending word.
        buzz = [f for f in result["findings"] if f["rule"] == "buzzword"]
        joined = " ".join(f["message"] for f in buzz).lower()
        self.assertIn("leverage", joined)
        self.assertIn("tapestry", joined)


class TestCLI(unittest.TestCase):
    def test_check_file(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(SLOP_TEXT)
            path = fh.name
        try:
            code, out = run_cli(["check", path])
        finally:
            os.unlink(path)
        self.assertEqual(code, 0)
        self.assertIn("plainness:", out)
        self.assertIn("buzzword", out)

    def test_stdin_works(self):
        code, out = run_cli(["check"], stdin_text=PLAIN_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("plainness: 100/100 (plain)", out)
        self.assertIn("No findings", out)

    def test_json_output_valid(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(SLOP_TEXT)
            path = fh.name
        try:
            code, out = run_cli(["check", path, "--json"])
        finally:
            os.unlink(path)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("plainness", data)
        self.assertIn("findings", data)
        self.assertIsInstance(data["findings"], list)
        self.assertIn("stats", data)

    def test_fail_under_exits_1_on_slop(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(SLOP_TEXT)
            path = fh.name
        try:
            code, _ = run_cli(["check", path, "--fail-under", "80"])
        finally:
            os.unlink(path)
        self.assertEqual(code, 1)

    def test_fail_under_exits_0_on_plain(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(PLAIN_TEXT)
            path = fh.name
        try:
            code, _ = run_cli(["check", path, "--fail-under", "80"])
        finally:
            os.unlink(path)
        self.assertEqual(code, 0)

    def test_missing_file_errors(self):
        with self.assertRaises((FileNotFoundError, OSError)):
            run_cli(["check", "/nonexistent/path/slop-lint-test.txt"])

    def test_hard_wrapped_long_sentence_detected(self):
        # A 32-word sentence hard-wrapped across lines must score the same
        # as the unwrapped version (regression: wrapped lines were split,
        # so the long sentence was never detected).
        words = ["word%d" % i for i in range(32)]
        sent = " ".join(words) + "."
        wrapped = "\n".join(sent[i:i + 40] for i in range(0, len(sent), 40))
        r_wrapped = slop_lint.analyze(wrapped)
        r_plain = slop_lint.analyze(sent)
        self.assertEqual(r_wrapped["stats"]["long_sentences"], 1)
        self.assertEqual(r_wrapped["plainness"], r_plain["plainness"])

    def test_fenced_code_blocks_excluded(self):
        text = ("```python\n"
                "x = leverage_the_api(deliverable)  # furthermore robust\n"
                "```\n"
                "This line is fine.\n")
        result = slop_lint.analyze(text)
        self.assertEqual(result["findings"], [])

    def test_list_items_not_merged(self):
        result = slop_lint.analyze("- short one\n- short two\n- short three\n")
        self.assertEqual(result["stats"]["long_sentences"], 0)


ZH_PLAIN = (
    "猫每天睡很久。\n"
    "小猫吃饱了就玩，玩累了就睡。\n"
)

ZH_SLOP = (
    "在当今这个快节奏的时代，说白了，我们要赋能业务，实现降本增效，"
    "打通全链路，形成闭环沉淀，还要对齐抓手、做好兜底。\n"
    "这不是运气，而是实力。成功不靠天赋，靠持续的努力"
    "——深度思考——快速行动——长期主义。\n"
    "综上所述，这个方案至关重要，希望对你有帮助。\n"
)


class TestChineseRules(unittest.TestCase):
    def test_zh_l1_ppt_nouns_flagged(self):
        result = slop_lint.analyze("这个方案能赋能业务，实现降本增效。")
        zh1 = [f for f in result["findings"] if f["rule"] == "zh-l1"]
        self.assertEqual(len(zh1), 2, result["findings"])
        self.assertTrue(all(f["severity"] == "L1" for f in zh1))
        joined = " ".join(f["message"] for f in zh1)
        self.assertIn("赋能", joined)
        self.assertIn("降本增效", joined)

    def test_zh_l1_kouchan_flagged(self):
        result = slop_lint.analyze("一句话总结：这就是一整个下午踩一遍的教训。")
        zh1 = [f for f in result["findings"] if f["rule"] == "zh-l1"]
        self.assertEqual(len(zh1), 3, result["findings"])

    def test_zh_chai_teardown_flagged(self):
        result = slop_lint.analyze("我拆了它的客户端，想看看实现。")
        rules = [f["rule"] for f in result["findings"]]
        self.assertIn("zh-l1", rules)

    def test_zh_chai_literal_exempt(self):
        # 拆包/拆散 are physical senses -- not teardown slang.
        result = slop_lint.analyze("把纸箱拆包，把零件拆散重装。")
        zh1 = [f for f in result["findings"] if f["rule"] == "zh-l1"]
        self.assertEqual(zh1, [], result["findings"])

    def test_zh_ledger_metaphor_flagged(self):
        result = slop_lint.analyze("这笔账划得来，时间的账要拆开看。")
        zh1 = [f for f in result["findings"] if f["rule"] == "zh-l1"]
        # 这笔账 / 的账 / 拆开看 (拆 teardown deduped into 拆开看).
        self.assertEqual(len(zh1), 3, result["findings"])

    def test_zh_ledger_literal_exempt(self):
        # 这笔账单 / 账号 are literal -- not bookkeeping metaphors.
        result = slop_lint.analyze("这笔账单已经结清，账号里还有余额。")
        zh1 = [f for f in result["findings"] if f["rule"] == "zh-l1"]
        self.assertEqual(zh1, [], result["findings"])

    def test_zh_not_but_flagged(self):
        result = slop_lint.analyze("这不是运气，而是实力。")
        nb = [f for f in result["findings"] if f["rule"] == "zh-not-but"]
        self.assertEqual(len(nb), 1, result["findings"])
        self.assertEqual(nb[0]["severity"], "L1")

    def test_zh_not_but_variant_bukao(self):
        result = slop_lint.analyze("成功不靠天赋，靠持续的努力。")
        nb = [f for f in result["findings"] if f["rule"] == "zh-not-but"]
        self.assertEqual(len(nb), 1, result["findings"])

    def test_zh_not_but_concession_allowed(self):
        # Pure negation + 让步 is explicitly legal, not a contrast cliché.
        result = slop_lint.analyze("它不是最快的，但最稳。")
        nb = [f for f in result["findings"] if f["rule"] == "zh-not-but"]
        self.assertEqual(nb, [], result["findings"])

    def test_zh_em_dash_quota(self):
        result = slop_lint.analyze("第一——第二——第三——第四。")
        ed = [f for f in result["findings"] if f["rule"] == "zh-em-dash"]
        self.assertEqual(len(ed), 1, result["findings"])  # only the 3rd dash
        self.assertEqual(ed[0]["severity"], "L1")
        self.assertEqual(result["stats"]["zh_structure_hits"], 1)

    def test_zh_em_dash_pair_counts_as_one(self):
        result = slop_lint.analyze("甲——乙——丙。")  # 2 dashes, within quota
        ed = [f for f in result["findings"] if f["rule"] == "zh-em-dash"]
        self.assertEqual(ed, [], result["findings"])

    def test_zh_l2_advisory(self):
        result = slop_lint.analyze("我们要看清问题的本质，澄清事件的真相。")
        l2 = [f for f in result["findings"] if f["rule"] == "zh-l2"]
        self.assertEqual(len(l2), 3, result["findings"])
        self.assertTrue(all(f["severity"] == "L2" for f in l2))
        # L2 deducts like hedges: -1 each.
        self.assertEqual(result["plainness"], 97, result)

    def test_zh_long_sentence_cjk(self):
        result = slop_lint.analyze("这" * 60 + "。")
        ls = [f for f in result["findings"] if f["rule"] == "long-sentence"]
        self.assertEqual(len(ls), 1, result["findings"])
        self.assertIn("effective words", ls[0]["message"])

    def test_zh_translationese_de_chain(self):
        result = slop_lint.analyze("这是提升系统运行效率的最终方案的核心部分的关键。")
        tr = [f for f in result["findings"] if f["rule"] == "zh-translationese"]
        self.assertEqual(len(tr), 1, result["findings"])
        self.assertIn("的-chain", tr[0]["message"])

    def test_zh_translationese_empty_verb(self):
        result = slop_lint.analyze("我们将对系统进行优化，以提升性能。")
        tr = [f for f in result["findings"] if f["rule"] == "zh-translationese"]
        self.assertEqual(len(tr), 1, result["findings"])
        self.assertIn("进行优化", tr[0]["message"])

    def test_zh_translationese_prejudge_colon(self):
        result = slop_lint.analyze("结论很明确：我们必须重构。")
        tr = [f for f in result["findings"] if f["rule"] == "zh-translationese"]
        self.assertEqual(len(tr), 1, result["findings"])

    def test_zh_opening_closing(self):
        result = slop_lint.analyze("综上所述，结论已经很清楚。希望对你有帮助。")
        rules = [f["rule"] for f in result["findings"]]
        self.assertIn("zh-opening", rules)
        self.assertIn("zh-closing", rules)

    def test_zh_unsourced(self):
        result = slop_lint.analyze("研究表明，这个方法更有效。")
        un = [f for f in result["findings"] if f["rule"] == "zh-unsourced"]
        self.assertEqual(len(un), 1, result["findings"])
        self.assertEqual(un[0]["severity"], "L2")

    def test_zh_negation_opening(self):
        result = slop_lint.analyze("不是所有人都能接受这个方案。")
        no = [f for f in result["findings"] if f["rule"] == "zh-negation-opening"]
        self.assertEqual(len(no), 1, result["findings"])

    def test_zh_slop_scores_low(self):
        result = slop_lint.analyze(ZH_SLOP)
        self.assertLess(result["plainness"], 60, result)
        self.assertEqual(result["grade"], "slop")
        self.assertGreater(result["stats"]["zh_l1_hits"], 0)
        self.assertGreater(result["stats"]["zh_structure_hits"], 0)

    def test_zh_plain_scores_high(self):
        result = slop_lint.analyze(ZH_PLAIN)
        self.assertGreaterEqual(result["plainness"], 90, result)
        self.assertEqual(result["findings"], [])


class TestBilingualCLI(unittest.TestCase):
    def test_lang_en_skips_chinese_rules(self):
        result = slop_lint.analyze("这个方案能赋能业务，实现降本增效。", lang="en")
        zh = [f for f in result["findings"] if f["rule"].startswith("zh")]
        self.assertEqual(zh, [])
        self.assertEqual(result["plainness"], 100)

    def test_lang_zh_forces_chinese_rules(self):
        result = slop_lint.analyze("这个方案能赋能业务。", lang="zh")
        self.assertTrue(any(f["rule"] == "zh-l1" for f in result["findings"]))

    def test_lang_auto_detects_cjk(self):
        result = slop_lint.analyze("这个方案能赋能业务。")
        self.assertTrue(any(f["rule"] == "zh-l1" for f in result["findings"]))

    def test_english_unaffected_by_zh_rules(self):
        # No CJK -> Chinese rules never fire; v0.1 behavior intact.
        result = slop_lint.analyze(SLOP_TEXT)
        zh = [f for f in result["findings"] if f["rule"].startswith("zh")]
        self.assertEqual(zh, [])
        self.assertEqual(result["grade"], "slop")

    def test_cli_lang_flag(self):
        code, out = run_cli(["check", "--lang", "en"],
                            stdin_text="这个方案能赋能业务。")
        self.assertEqual(code, 0)
        self.assertIn("plainness: 100/100", out)

    def test_cli_zh_output(self):
        code, out = run_cli(["check"], stdin_text="这不是运气，而是实力。")
        self.assertEqual(code, 0)
        self.assertIn("zh-not-but", out)
        self.assertIn("chinese:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
