"""Daily live check of the published styles, with a notification when a verdict changes.

A run in which a verdict changes exits with status 1, so a systemd OnFailure= handler hears
about it as well as the notify_command; a run with no change exits 0.

Reads `[daily]` from the check's config file:

    export_command = ["ssh", "windows", "python", "-"]   # gets firefox_state.py on stdin
    notify_command = ["python3", "/path/to/send.py"]      # optional; subject as last argument, body on stdin

The storage state stays in memory for the run and is never written to disk. The report goes to
~/.local/state/maxwidth/last.json; failure screenshots go beside it under runs/.
"""

import json
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

import check

STATE_DIR = Path.home() / ".local/state/maxwidth"


def export_state(command: list[str]) -> dict:
    script = (check.ROOT / "firefox_state.py").read_bytes()
    result = subprocess.run(command, input=script, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"export command exited {result.returncode}")
    return json.loads(result.stdout.replace(b"\0", b""))


def changes(previous: dict | None, report: dict) -> list[str]:
    old = (previous or {}).get("sites", {})
    return [f"{name}: {old.get(name, {}).get('verdict', 'none')} -> {result['verdict']}"
            for name, result in report["sites"].items()
            if result["verdict"] != old.get(name, {}).get("verdict")
            and (previous or result["verdict"] == check.BROKEN)]


def main() -> int:
    config = tomllib.loads(check.CONFIG.read_text())
    daily = config.get("daily", {})
    artifacts = check.ARTIFACTS / datetime.now().strftime("%Y%m%dT%H%M%S")
    try:
        state = export_state(daily["export_command"])
    except Exception as e:
        report = {"time": datetime.now().astimezone().isoformat(timespec="seconds"), "source": "published",
                  "sites": {n: {"verdict": check.BLOCKED, "viewports": [],
                                "problems": [f"sign-in export failed: {type(e).__name__}: {e}"]} for n in check.SITES}}
    else:
        report = check.run(list(check.SITES), config.get("conversations", {}), state, "published", artifacts=artifacts)
    report["artifacts"] = str(artifacts) if artifacts.exists() else None
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    last = STATE_DIR / "last.json"
    previous = json.loads(last.read_text()) if last.exists() else None
    last.write_text(json.dumps(report, indent=1))
    body = check.summary(report) + (f"\n\nArtifacts: {report['artifacts']}" if report["artifacts"] else "")
    print(body)
    changed = changes(previous, report)
    if changed and daily.get("notify_command"):
        subject = "maxwidth: " + "; ".join(changed)
        subprocess.run([*daily["notify_command"], subject], input=body.encode(), check=True, timeout=120)
    # A changed verdict also fails the unit, for an OnFailure= handler; the report above is its output.
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
