"""Live layout check for the wide-chat user styles.

Loads a real conversation per site with a Playwright storage state, measures the
layout, injects the style, measures again, and reports PASS, BROKEN, or BLOCKED.
Only geometry is recorded; message text never leaves the page.
"""

import argparse
import json
import re
import sys
import tomllib
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = Path.home() / ".config/maxwidth/config.toml"
ARTIFACTS = Path.home() / ".local/state/maxwidth/runs"
PUBLISHED = "https://userstyles.world/api/style/{}.user.css"

PASS, BROKEN, BLOCKED = "PASS", "BROKEN", "BLOCKED"

# Desktop, narrow desktop, and phone.
VIEWPORTS = [(1600, 1000), (1100, 800), (390, 844)]

# How far a filled element may stop short of the pane's width, for padding.
FILL_SLACK = 96

CHALLENGE = re.compile(r"just a moment|verify you are human|confirm you are human|security verification"
                       r"|checking your browser|unusual activity", re.I)


@dataclass(frozen=True)
class Site:
    css: str
    style_id: str
    # Present only when a signed-in conversation rendered; absent means BLOCKED.
    marker: str
    # Must stretch to the pane's width once the style applies.
    fill: tuple[str, ...]
    # Must stay inside the pane and the viewport.
    inside: tuple[str, ...]
    # The scrolling conversation area; None means the marker's nearest scrolling ancestor.
    pane: str | None = None
    # User messages that should keep their natural width when short.
    bubbles: str | None = None


SITES = {
    "chatgpt": Site(
        css="chatgpt.user.css", style_id="13403", marker="[data-turn-key]",
        pane=".thread-scroll-container",
        fill=("[data-turn-key]", "[data-composer-surface-variant]"),
        inside=("[data-turn-key]", "[data-user-message-bubble]", "[data-composer-surface-variant]"),
        bubbles="[data-user-message-bubble]"),
    # The Claude and DeepSeek selectors come from their public share pages; the
    # signed-in pages have not rendered past bot checks yet.
    "claude": Site(
        css="claude.user.css", style_id="30655", marker='[data-testid="user-message"]',
        fill=('[class*="--transcript-width"]',),
        inside=('[data-testid="user-message"]', ".font-claude-response"),
        bubbles='[data-testid="user-message"]'),
    "deepseek": Site(
        css="deepseek.user.css", style_id="20024", marker=".ds-markdown",
        fill=(".ds-virtual-list-items",), inside=(".ds-markdown",)),
}


def style_body(css: str) -> str:
    """The rules inside the style's @-moz-document block."""
    start = css.index("{", css.index("@-moz-document"))
    return css[start + 1:css.rindex("}")]


def selectors(css: str) -> list[str]:
    """Every selector the style targets, so each one can be required to match."""
    body = re.sub(r"/\*.*?\*/", "", style_body(css), flags=re.S)
    found = []
    for group in re.findall(r"([^{}]+)\{[^{}]*\}", body):
        found += [s.strip() for s in group.split(",") if s.strip()]
    return found


MEASURE = """([marker, paneSel, fill, inside, bubbles, targets]) => {
  const vis = e => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; };
  const box = e => { const b = e.getBoundingClientRect(); return {l: b.left, r: b.right, w: b.width}; };
  const all = s => [...document.querySelectorAll(s)].filter(vis);
  const scroller = e => { for (let x = e && e.parentElement; x; x = x.parentElement) {
    const o = getComputedStyle(x).overflowY; if (o === 'auto' || o === 'scroll') return x; } return null; };
  const first = document.querySelector(marker);
  const pane = paneSel ? document.querySelector(paneSel) : scroller(first);
  const map = sels => Object.fromEntries(sels.map(s => [s, all(s).map(box)]));
  return {
    rendered: !!first,
    vw: innerWidth, docScroll: document.documentElement.scrollWidth,
    pane: pane ? {...box(pane), scroll: pane.scrollWidth, client: pane.clientWidth} : null,
    fill: map(fill), inside: map(inside),
    bubbles: bubbles ? all(bubbles).map(e => ({...box(e), maxW: getComputedStyle(e).maxWidth,
                                              row: e.parentElement.getBoundingClientRect().width})) : [],
    targets: Object.fromEntries(targets.map(s => { try { return [s, document.querySelectorAll(s).length]; }
                                                   catch (err) { return [s, -1]; } })),
  };
}"""


def cap_px(max_width: str, row: float) -> float:
    if max_width.endswith("%"):
        return row * float(max_width[:-1]) / 100
    if max_width.endswith("px"):
        return float(max_width[:-2])
    return float("inf")


def evaluate(before: dict, after: dict) -> list[str]:
    """Problems with the styled layout, from two measurements of the same page."""
    problems = []
    for sel, count in after["targets"].items():
        if count <= 0:
            problems.append(f"style selector matches nothing: {sel}")
    pane = after["pane"]
    if pane is None:
        return problems + ["conversation pane not found"]
    left, right = max(pane["l"], 0), min(pane["r"], after["vw"])
    if after["docScroll"] > after["vw"] + 1:
        problems.append(f"page scrolls horizontally: {after['docScroll']:.0f}px content in {after['vw']}px viewport")
    if pane["scroll"] > pane["client"] + 1:
        problems.append(f"pane overflows: {pane['scroll']:.0f}px content in {pane['client']:.0f}px")
    for sel, boxes in after["fill"].items():
        if not boxes:
            problems.append(f"nothing to measure for {sel}")
        elif max(b["w"] for b in boxes) < (right - left) - FILL_SLACK:
            problems.append(f"{sel} is {max(b['w'] for b in boxes):.0f}px wide in a {right - left:.0f}px pane")
    for sel, boxes in after["inside"].items():
        for b in boxes:
            if b["l"] < left - 1 or b["r"] > right + 1:
                problems.append(f"{sel} spans {b['l']:.0f}..{b['r']:.0f}px outside the pane {left:.0f}..{right:.0f}px")
                break
    # A user message narrower than its cap without the style has its natural
    # width; the style may lift the cap but should not stretch it.
    for b0, b1 in zip(before["bubbles"], after["bubbles"]):
        if b0["w"] < cap_px(b0["maxW"], b0["row"]) - 4 and b1["w"] > b0["w"] + 4:
            problems.append(f"short message stretched from {b0['w']:.0f}px to {b1['w']:.0f}px")
            break
    return problems


def blocked_reason(status: int | None, url: str, expected_host: str, rendered: bool, text: str) -> str | None:
    """Why a loaded page does not show the conversation, or None if it does.

    Only a page without the conversation is scanned for bot-check wording, so a
    conversation that discusses bot checks is not mistaken for one.
    """
    if status is not None and status >= 400:
        return f"HTTP {status}"
    if expected_host not in url or re.search(r"/(log-?in|auth|sign-?in)\b", url):
        return "signed out"
    if rendered:
        return None
    return "bot check" if CHALLENGE.search(text) else "conversation did not render"


def load_css(site: Site, source: str) -> str:
    if source == "published":
        with urllib.request.urlopen(PUBLISHED.format(site.style_id), timeout=30) as r:
            return r.read().decode()
    return (ROOT / site.css).read_text()


def check_site(browser, name: str, site: Site, url: str, state: dict, user_agent: str | None,
               css: str, artifacts: Path | None) -> dict:
    body, targets = style_body(css), selectors(css)
    host = url.split("/")[2]
    runs = []
    for width, height in VIEWPORTS:
        tag = f"{name}-{width}"
        ctx = browser.new_context(storage_state=state, viewport={"width": width, "height": height},
                                  **({"user_agent": user_agent} if user_agent else {}))
        page = ctx.new_page()
        run = {"viewport": width}
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_selector(site.marker, timeout=20_000)
            except Exception:
                pass
            rendered = page.query_selector(site.marker) is not None
            text = "" if rendered else page.title() + " " + page.evaluate("document.body ? document.body.innerText.slice(0, 3000) : ''")
            reason = blocked_reason(response.status if response else None, page.url, host, rendered, text)
            if reason:
                run.update(verdict=BLOCKED, problems=[reason])
            else:
                page.wait_for_timeout(2_000)
                args = [site.marker, site.pane, list(site.fill), list(site.inside), site.bubbles, targets]
                run["before"] = page.evaluate(MEASURE, args)
                page.add_style_tag(content=body)
                page.wait_for_timeout(1_500)
                run["after"] = page.evaluate(MEASURE, args)
                # A bot check can replace the page after it first rendered.
                if not (run["before"]["rendered"] and run["after"]["rendered"]):
                    run.update(verdict=BLOCKED, problems=["page was replaced while measuring"])
                else:
                    problems = evaluate(run["before"], run["after"])
                    run.update(verdict=BROKEN if problems else PASS, problems=problems)
        except Exception as e:
            run.update(verdict=BLOCKED, problems=[f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"])
        if artifacts and run["verdict"] != PASS:
            artifacts.mkdir(parents=True, exist_ok=True)
            try:
                page.screenshot(path=artifacts / f"{tag}.png")
            except Exception:
                pass
            (artifacts / f"{tag}.json").write_text(json.dumps(run, indent=1))
        ctx.close()
        runs.append(run)
    verdicts = {r["verdict"] for r in runs}
    verdict = BROKEN if BROKEN in verdicts else PASS if verdicts == {PASS} else BLOCKED
    return {"verdict": verdict, "viewports": [{k: r[k] for k in ("viewport", "verdict", "problems")} for r in runs]}


def run(sites: list[str], conversations: dict, state: dict | None, source: str = "repo",
        headed: bool = False, artifacts: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    state = dict(state or {"cookies": [], "origins": []})
    user_agent = state.pop("userAgent", None)
    report = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source, "sites": {}}
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=not headed)
        for name in sites:
            site, url = SITES[name], conversations.get(name)
            if not url:
                report["sites"][name] = {"verdict": BLOCKED, "viewports": [], "problems": ["no conversation configured"]}
                continue
            try:
                css = load_css(site, source)
            except OSError as e:
                report["sites"][name] = {"verdict": BLOCKED, "viewports": [], "problems": [f"style download failed: {e}"]}
                continue
            report["sites"][name] = check_site(browser, name, site, url, state, user_agent, css, artifacts)
        browser.close()
    return report


def summary(report: dict) -> str:
    lines = []
    for name, result in report["sites"].items():
        lines.append(f"{name}: {result['verdict']}")
        for problem in result.get("problems", []):
            lines.append(f"  {problem}")
        for v in result["viewports"]:
            for problem in v["problems"]:
                lines.append(f"  {v['viewport']}px {v['verdict']}: {problem}")
    return "\n".join(lines)


def exit_code(report: dict) -> int:
    verdicts = {r["verdict"] for r in report["sites"].values()}
    return 1 if BROKEN in verdicts else 2 if BLOCKED in verdicts else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="Exit status: 0 all PASS, 1 any BROKEN, 2 otherwise BLOCKED.")
    parser.add_argument("sites", nargs="*", help=f"sites to check: {', '.join(SITES)} (default: all)")
    parser.add_argument("--state", type=Path, help="Playwright storage state JSON (see firefox_state.py)")
    parser.add_argument("--config", type=Path, default=CONFIG, help=f"conversation URLs (default: {CONFIG})")
    parser.add_argument("--source", choices=["repo", "published"], default="repo",
                        help="check this checkout's CSS or the code UserStyles.world serves")
    parser.add_argument("--headed", action="store_true", help="show the browser (needs a display)")
    parser.add_argument("--artifacts", type=Path, help=f"where failures save screenshots and geometry (default: {ARTIFACTS}/<time>)")
    parser.add_argument("--json", type=Path, help="also write the report here")
    args = parser.parse_args(argv)
    if unknown := set(args.sites) - set(SITES):
        parser.error(f"unknown site: {', '.join(sorted(unknown))}")
    conversations = tomllib.loads(args.config.read_text()).get("conversations", {}) if args.config.exists() else {}
    state = json.loads(args.state.read_text()) if args.state else None
    artifacts = args.artifacts or ARTIFACTS / datetime.now().strftime("%Y%m%dT%H%M%S")
    report = run(args.sites or list(SITES), conversations, state, args.source, args.headed, artifacts)
    report["artifacts"] = str(artifacts) if artifacts.exists() else None
    if args.json:
        args.json.write_text(json.dumps(report, indent=1))
    print(summary(report))
    if report["artifacts"]:
        print(f"artifacts: {report['artifacts']}")
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
