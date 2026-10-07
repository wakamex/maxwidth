import copy
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import check  # noqa: E402

TURN, BUBBLE = "[data-turn-key]", "[data-user-message-bubble]"


def box(left, right):
    return {"l": left, "r": right, "w": right - left}


def page(turn=(52, 1600), bubbles=((1489, 1600, "70%", 1548),), doc=1600, pane_scroll=1548, targets=1):
    """A synthetic measurement shaped like check.MEASURE's result for a 1600px ChatGPT page."""
    return {"rendered": True, "vw": 1600, "docScroll": doc,
            "pane": {**box(52, 1600), "scroll": pane_scroll, "client": 1548},
            "fill": {TURN: [box(*turn)]}, "inside": {TURN: [box(*turn)]},
            "bubbles": [{**box(l, r), "maxW": m, "row": row} for l, r, m, row in bubbles],
            "targets": {".a": targets}}


BEFORE = page(turn=(442, 1210), bubbles=((1099, 1210, "70%", 768),))


class EvaluateTest(unittest.TestCase):
    def test_full_width_layout_passes(self):
        self.assertEqual(check.evaluate(BEFORE, page(bubbles=((1489, 1600, "100%", 1548),))), [])

    def test_conversation_shifted_behind_sidebar(self):
        # The live regression: a transform moved the thread 134px left of the pane.
        problems = check.evaluate(BEFORE, page(turn=(-82, 1426)))
        self.assertTrue(any("outside the pane" in p for p in problems), problems)

    def test_conversation_not_widened(self):
        problems = check.evaluate(BEFORE, page(turn=(442, 1210)))
        self.assertTrue(any("768px wide in a 1548px pane" in p for p in problems), problems)

    def test_short_message_stretched(self):
        problems = check.evaluate(BEFORE, page(bubbles=((72, 1580, "100%", 1548),)))
        self.assertTrue(any("short message stretched from 111px" in p for p in problems), problems)

    def test_long_message_at_its_cap_may_grow(self):
        before = page(turn=(442, 1210), bubbles=((672, 1210, "70%", 768),))
        self.assertEqual(check.evaluate(before, page(bubbles=((499, 1600, "100%", 1548),))), [])

    def test_horizontal_overflow(self):
        problems = check.evaluate(BEFORE, page(doc=1700))
        self.assertTrue(any("scrolls horizontally" in p for p in problems), problems)
        problems = check.evaluate(BEFORE, page(pane_scroll=1600))
        self.assertTrue(any("pane overflows" in p for p in problems), problems)

    def test_stale_selector(self):
        problems = check.evaluate(BEFORE, page(targets=0))
        self.assertIn("style selector matches nothing: .a", problems)

    def test_missing_pane(self):
        after = copy.deepcopy(page()); after["pane"] = None
        self.assertIn("conversation pane not found", check.evaluate(BEFORE, after))


class BlockedTest(unittest.TestCase):
    def test_reasons(self):
        url = "https://claude.ai/chat/x"
        self.assertEqual(check.blocked_reason(403, url, "claude.ai", False, ""), "HTTP 403")
        self.assertEqual(check.blocked_reason(200, url, "claude.ai", False, "Just a moment... Performing security verification"), "bot check")
        self.assertEqual(check.blocked_reason(202, "https://chat.deepseek.com/a/chat/s/x", "chat.deepseek.com", False, "Let's confirm you are human"), "bot check")
        self.assertEqual(check.blocked_reason(200, url, "claude.ai", False, "Loading"), "conversation did not render")
        self.assertEqual(check.blocked_reason(200, "https://claude.ai/login", "claude.ai", False, ""), "signed out")
        self.assertEqual(check.blocked_reason(200, "https://auth.openai.com/x", "chatgpt.com", False, ""), "signed out")
        self.assertIsNone(check.blocked_reason(200, url, "claude.ai", True, ""))

    def test_conversation_about_bot_checks_is_not_blocked(self):
        self.assertIsNone(check.blocked_reason(200, "https://claude.ai/chat/x", "claude.ai", True, "verify you are human"))

    def test_exit_code(self):
        sites = lambda *v: {"sites": {str(i): {"verdict": x} for i, x in enumerate(v)}}
        self.assertEqual(check.exit_code(sites("PASS", "PASS")), 0)
        self.assertEqual(check.exit_code(sites("PASS", "BLOCKED")), 2)
        self.assertEqual(check.exit_code(sites("BLOCKED", "BROKEN")), 1)


class StyleTest(unittest.TestCase):
    def test_every_site_style_parses(self):
        for name, site in check.SITES.items():
            with self.subTest(name):
                self.assertTrue(check.selectors((ROOT / site.css).read_text()))

    def test_selectors(self):
        css = '@-moz-document domain("x") {\n/* c { } */\n.a, .b > [x="{"] {}\n.c { d: e; }\n}'
        self.assertEqual(check.selectors(css.replace('[x="{"]', ".d")), [".a", ".b > .d", ".c"])

    def test_cap(self):
        self.assertEqual(check.cap_px("70%", 768), 537.6)
        self.assertEqual(check.cap_px("538px", 0), 538)
        self.assertEqual(check.cap_px("none", 768), float("inf"))


class EntryPointTest(unittest.TestCase):
    def test_help(self):
        for script in ("check.py", "lint.py", "firefox_state.py"):
            with self.subTest(script):
                result = subprocess.run([sys.executable, str(ROOT / script), "--help"], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage", result.stdout)


if __name__ == "__main__":
    unittest.main()
