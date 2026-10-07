import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily  # noqa: E402


def report(**verdicts):
    return {"sites": {k: {"verdict": v} for k, v in verdicts.items()}}


class ChangesTest(unittest.TestCase):
    def test_first_run_reports_only_broken(self):
        self.assertEqual(daily.changes(None, report(a="PASS", b="BLOCKED")), [])
        self.assertEqual(daily.changes(None, report(a="BROKEN")), ["a: none -> BROKEN"])

    def test_verdict_changes(self):
        old = report(a="PASS", b="BLOCKED", c="BROKEN")
        self.assertEqual(daily.changes(old, report(a="PASS", b="BLOCKED", c="BROKEN")), [])
        self.assertEqual(daily.changes(old, report(a="BROKEN", b="PASS", c="BROKEN")),
                         ["a: PASS -> BROKEN", "b: BLOCKED -> PASS"])


if __name__ == "__main__":
    unittest.main()
