import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lint  # noqa: E402

STYLE = """/* ==UserStyle==
@name         example
@version      20261007.15.10
@namespace    https://example.invalid
==/UserStyle== */

@-moz-document domain("example.invalid") {
.a { max-width: 100% !important; }
}
"""


class LintTest(unittest.TestCase):
    def test_repository_styles(self):
        self.assertEqual(lint.main([]), 0)

    def test_valid(self):
        self.assertEqual(lint.problems(STYLE), [])

    def test_header(self):
        self.assertEqual(lint.problems("body {}"), ["missing ==UserStyle== header at the top of the file"])
        self.assertEqual(lint.problems(STYLE.replace("@namespace    https://example.invalid\n", "")), ["header lacks @namespace"])
        self.assertIn("is not dot-separated numbers", lint.problems(STYLE.replace("20261007.15.10", "v2"))[0])

    def test_braces(self):
        self.assertEqual(lint.problems(STYLE.replace(".a {", ".a ")), ["unbalanced braces"])

    def test_changed_code_needs_higher_version(self):
        changed = STYLE.replace("100%", "90%")
        self.assertEqual(lint.problems(changed, STYLE), ["code changed but @version 20261007.15.10 is not above 20261007.15.10"])
        self.assertEqual(lint.problems(changed.replace("15.10", "18.00"), STYLE), [])
        # Numeric, not string, comparison.
        self.assertEqual(lint.problems(changed.replace("20261007.15.10", "20261007.15.9"), STYLE)[0][:12], "code changed")

    def test_version_only_change(self):
        self.assertEqual(lint.problems(STYLE.replace("15.10", "15.11"), STYLE), [])


if __name__ == "__main__":
    unittest.main()
