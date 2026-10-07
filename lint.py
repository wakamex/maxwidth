"""Check each style's UserCSS header and that changed code raises @version.

Uses only the standard library so CI needs no setup. With --base REF, any
style whose code differs from REF must carry a higher @version, since
UserStyles.world mirroring and Stylus updates only pick up a higher version.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HEADER = re.compile(r"\A/\* ==UserStyle==\n(.*?)\n==/UserStyle== \*/\n", re.S)
REQUIRED = ("name", "namespace", "version")


def metadata(css: str) -> dict[str, str]:
    match = HEADER.match(css)
    if not match:
        raise ValueError("missing ==UserStyle== header at the top of the file")
    meta = {}
    for line in match.group(1).splitlines():
        if m := re.match(r"@(\S+)\s+(.*\S)", line):
            meta[m.group(1)] = m.group(2)
    return meta


def version_key(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        raise ValueError(f"@version {version!r} is not dot-separated numbers")
    return tuple(int(part) for part in version.split("."))


def code(css: str) -> str:
    """The file without its @version line, so a version bump alone is not a code change."""
    return re.sub(r"^@version.*\n", "", css, count=1, flags=re.M)


def problems(css: str, base: str | None = None) -> list[str]:
    try:
        meta = metadata(css)
        missing = [k for k in REQUIRED if k not in meta]
        if missing:
            return [f"header lacks @{', @'.join(missing)}"]
        version = version_key(meta["version"])
    except ValueError as e:
        return [str(e)]
    found = []
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    if "@-moz-document" not in body:
        found.append("no @-moz-document block")
    depth = 0
    for ch in body:
        depth += {"{": 1, "}": -1}.get(ch, 0)
        if depth < 0:
            break
    if depth:
        found.append("unbalanced braces")
    if base is not None and code(base) != code(css):
        try:
            old = metadata(base)["version"]
            if version <= version_key(old):
                found.append(f"code changed but @version {meta['version']} is not above {old}")
        except (ValueError, KeyError):
            pass
    return found


def at_ref(ref: str, path: Path) -> str | None:
    result = subprocess.run(["git", "show", f"{ref}:{path.name}"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="git ref to compare against for the @version rule")
    args = parser.parse_args(argv)
    failed = False
    for path in sorted(ROOT.glob("*.user.css")):
        base = at_ref(args.base, path) if args.base else None
        for problem in problems(path.read_text(), base):
            print(f"{path.name}: {problem}")
            failed = True
    if not failed:
        print("styles ok")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
