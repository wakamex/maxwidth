"""Export a Firefox profile's sign-ins for the checked sites as a Playwright storage state.

Run it on the machine where Firefox is signed in; it needs only the standard
library, so it can be piped to a remote Python:

    ssh HOST python - < firefox_state.py > state.json

It copies the cookie and localStorage databases before reading them, so Firefox
may stay open. The output holds live session tokens: keep it out of Git and
logs, and delete it after use. A `userAgent` field names the profile's Firefox
version so the check can present the same browser the cookies were issued to.
"""

import argparse
import configparser
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

DOMAINS = ("chatgpt.com", "openai.com", "claude.ai", "deepseek.com")
# DeepSeek keeps its sign-in in localStorage rather than cookies.
LOCAL_STORAGE = ("https://chat.deepseek.com",)
SAME_SITE = {0: "None", 1: "Lax", 2: "Strict"}


def firefox_home() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Mozilla/Firefox"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Firefox"
    for candidate in (Path.home() / ".config/mozilla/firefox", Path.home() / ".mozilla/firefox"):
        if (candidate / "profiles.ini").exists():
            return candidate
    return Path.home() / ".mozilla/firefox"


def default_profile(home: Path) -> Path:
    """The profile Firefox opens by default: the install's, else the one marked Default."""
    ini = configparser.ConfigParser()
    ini.read(home / "profiles.ini")
    for section in ini.sections():
        if section.startswith("Install") and ini[section].get("Default"):
            return home / ini[section]["Default"]
    for section in ini.sections():
        if section.startswith("Profile") and ini[section].get("Default") == "1":
            p = ini[section]
            return home / p["Path"] if p.get("IsRelative", "1") == "1" else Path(p["Path"])
    raise SystemExit(f"no default Firefox profile in {home / 'profiles.ini'}")


def read_copy(database: Path, query: str, params=()) -> list:
    """Query a copy of a database and its WAL, since Firefox holds the original open."""
    if not database.exists():
        return []
    with tempfile.TemporaryDirectory() as tmp:
        for f in database.parent.glob(database.name + "*"):
            shutil.copy(f, tmp)
        con = sqlite3.connect(Path(tmp) / database.name)
        try:
            return con.execute(query, params).fetchall()
        finally:
            con.close()


def cookies(profile: Path) -> list[dict]:
    rows = read_copy(profile / "cookies.sqlite",
                     "select name, value, host, path, expiry, isSecure, isHttpOnly, sameSite from moz_cookies")
    out = []
    for name, value, host, path, expiry, secure, http_only, same_site in rows:
        if not any(host.lstrip(".") == d or host.lstrip(".").endswith("." + d) for d in DOMAINS):
            continue
        # Firefox stores some expiries in milliseconds.
        expires = expiry / 1000 if expiry > 1e11 else expiry
        out.append({"name": name, "value": value, "domain": host, "path": path, "expires": expires or -1,
                    "secure": bool(secure), "httpOnly": bool(http_only), "sameSite": SAME_SITE.get(same_site, "Lax")})
    return out


def local_storage(profile: Path, origin: str) -> list[dict]:
    folder = origin.replace("://", "+++").replace(":", "+")
    rows = read_copy(profile / "storage/default" / folder / "ls/data.sqlite",
                     "select key, value, compression_type from data")
    # Compressed values (snappy) are caches, not sign-ins; skip them.
    return [{"name": k, "value": v if isinstance(v, str) else bytes(v).decode("utf-8")}
            for k, v, compression in rows if compression == 0]


def user_agent(profile: Path) -> str | None:
    ini = configparser.ConfigParser()
    ini.read(profile / "compatibility.ini")
    version = ini.get("Compatibility", "LastVersion", fallback="").split(".")[0]
    if not version.isdigit():
        return None
    system = {"win32": "Windows NT 10.0; Win64; x64", "darwin": "Macintosh; Intel Mac OS X 10.15"}.get(
        sys.platform, f"X11; Linux {platform.machine()}")
    return f"Mozilla/5.0 ({system}; rv:{version}.0) Gecko/20100101 Firefox/{version}.0"


def export(profile: Path) -> dict:
    state = {"cookies": cookies(profile),
             "origins": [{"origin": o, "localStorage": local_storage(profile, o)} for o in LOCAL_STORAGE]}
    if ua := user_agent(profile):
        state["userAgent"] = ua
    return state


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", type=Path, help="profile directory (default: Firefox's default profile)")
    args = parser.parse_args(argv)
    json.dump(export(args.profile or default_profile(firefox_home())), sys.stdout)


if __name__ == "__main__":
    main()
