import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import firefox_state  # noqa: E402


class ExportTest(unittest.TestCase):
    """Synthetic profile using the column names of Firefox's cookies.sqlite and LSNG data.sqlite."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = Path(self.tmp.name)
        con = sqlite3.connect(self.profile / "cookies.sqlite")
        con.execute("create table moz_cookies (id integer primary key, originAttributes text, name text, value text, host text,"
                    " path text, expiry integer, lastAccessed integer, creationTime integer, isSecure integer,"
                    " isHttpOnly integer, inBrowserElement integer, sameSite integer, schemeMap integer)")
        rows = [("sessionKey", "synthetic", ".claude.ai", 1893456000000, 1, 1, 1),
                ("sid", "synthetic", ".notclaude.ai", 1893456000, 1, 1, 0),
                ("cf_clearance", "synthetic", "chatgpt.com", 0, 1, 0, 0)]
        for name, value, host, expiry, secure, http_only, same_site in rows:
            con.execute("insert into moz_cookies (name, value, host, path, expiry, isSecure, isHttpOnly, sameSite)"
                        " values (?, ?, ?, '/', ?, ?, ?, ?)", (name, value, host, expiry, secure, http_only, same_site))
        con.commit(); con.close()
        ls = self.profile / "storage/default/https+++chat.deepseek.com/ls"
        ls.mkdir(parents=True)
        con = sqlite3.connect(ls / "data.sqlite")
        con.execute("create table data (key text primary key, utf16_length integer, conversion_type integer,"
                    " compression_type integer, last_access_time integer, value blob)")
        con.execute("insert into data values ('userToken', 9, 1, 0, 0, ?)", (b'{"v":"x"}',))
        con.execute("insert into data values ('cache', 9, 1, 1, 0, ?)", (b"\xff\x00",))
        con.commit(); con.close()
        (self.profile / "compatibility.ini").write_text("[Compatibility]\nLastVersion=156.0.1_20261001000000/20261001000000\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_export(self):
        state = firefox_state.export(self.profile)
        cookies = {c["name"]: c for c in state["cookies"]}
        self.assertEqual(set(cookies), {"sessionKey", "cf_clearance"})
        self.assertEqual(cookies["sessionKey"]["expires"], 1893456000)
        self.assertEqual(cookies["sessionKey"]["sameSite"], "Lax")
        self.assertEqual(cookies["cf_clearance"]["expires"], -1)
        self.assertEqual(state["origins"], [{"origin": "https://chat.deepseek.com",
                                             "localStorage": [{"name": "userToken", "value": '{"v":"x"}'}]}])
        self.assertIn("Firefox/156.0", state["userAgent"])

    def test_default_profile(self):
        (self.profile / "profiles.ini").write_text(
            "[Profile0]\nName=a\nIsRelative=1\nPath=Profiles/a\nDefault=1\n\n[Install1]\nDefault=Profiles/b\n")
        self.assertEqual(firefox_state.default_profile(self.profile), self.profile / "Profiles/b")
        (self.profile / "profiles.ini").write_text("[Profile0]\nName=a\nIsRelative=1\nPath=Profiles/a\nDefault=1\n")
        self.assertEqual(firefox_state.default_profile(self.profile), self.profile / "Profiles/a")


if __name__ == "__main__":
    unittest.main()
