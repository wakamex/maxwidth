# maxwidth

Three [Stylus](https://github.com/openstyles/stylus) user styles, in the [UserCSS](https://github.com/openstyles/stylus/wiki/Writing-UserCSS) format, that widen the conversation and composer of AI chat sites to the available width. Users install and update them from [UserStyles.world](https://userstyles.world/) (USw); this repository is the source those listings mirror.

| File | Site | Install | Source USw mirrors |
| --- | --- | --- | --- |
| `chatgpt.user.css` | chatgpt.com | [style 13403](https://userstyles.world/style/13403/chatgpt-wide-chat-max-width-100) | https://raw.githubusercontent.com/wakamex/maxwidth/main/chatgpt.user.css |
| `claude.user.css` | claude.ai | [style 30655](https://userstyles.world/style/30655) | https://raw.githubusercontent.com/wakamex/maxwidth/main/claude.user.css |
| `deepseek.user.css` | chat.deepseek.com | [style 20024](https://userstyles.world/style/20024/deepseek-wide-chat-max-width-100) | https://raw.githubusercontent.com/wakamex/maxwidth/main/deepseek.user.css |

Each file keeps the name, author, and namespace its USw listing declares, and declares `@license MIT`.

## Checks

`check.py` opens a real conversation on each site in [Playwright](https://playwright.dev/python/)'s Firefox, signed in with a Playwright storage state. It measures the layout, injects the style, and measures again, at 1600, 1100, and 390 pixels wide. It records geometry only; message text never leaves the page.

With the style applied, a site passes when:

- every selector in the style matches at least one element, so a site rename shows up as a stale selector rather than a silent no-op;
- the conversation and the composer reach the width of the scrolling conversation pane, within 96px of padding;
- conversation turns, messages, and the composer stay inside the pane and the viewport, which catches content shifted behind the sidebar, such as the 154px `transform` on ChatGPT's thread that the style now resets;
- neither the page nor the pane scrolls horizontally;
- a user message that was narrower than its cap without the style keeps its width, so short messages do not stretch while long ones may grow.

Each site gets one of three verdicts:

| Verdict | Meaning |
| --- | --- |
| PASS | The conversation rendered at every width and every condition held. |
| BROKEN | The conversation rendered, and with the style applied at least one condition failed. |
| BLOCKED | The conversation could not be verified: HTTP error, network failure, bot check or CAPTCHA, signed-out redirect, missing conversation, or a page replaced by a challenge while measuring. A BLOCKED site says nothing about the style. |

`check.py` exits 0 when every site passes, 1 when any is BROKEN, and 2 otherwise.

The repository has no saved HTML fixtures. The styles only fail when a site changes its markup, and a frozen copy of the markup cannot show that; it would only re-test unchanged CSS against an unchanged page. The unit tests instead cover the check's own logic with synthetic measurements, including the 154px shift, a style that stops widening, and a stretched short message.

### Coverage by site

| Site | Live check from this setup | Verified |
| --- | --- | --- |
| ChatGPT | Runs signed in with exported Firefox cookies and Firefox's user agent. | PASS on 2026-10-07 with the sidebar collapsed to its icon rail. Deliberately broken copies of the style (the 154px shift, the old stretched message bubble, and no width rule) each report BROKEN. |
| Claude | Cloudflare shows "Verify you are human" to Playwright's Firefox and Chromium on signed-in conversation pages, with or without the exported cookies. | Not verified. On a public share page, Claude's transcript stays 752px wide with the style because a parent `max-w-3xl` wrapper caps it; whether signed-in pages have that wrapper is unknown. |
| DeepSeek | Its AWS bot check ("Let's confirm you are human") blocks Playwright's browsers. | Not verified. The `.aaff8b8f` selector is a generated class name and the most likely to go stale. |

Other gaps: the ChatGPT check does not open the sidebar or ChatGPT's floating outputs panel, which overlays the top right of the conversation without the style's involvement. The Claude and DeepSeek page selectors in `check.py` come from public share pages and may need adjusting once a signed-in page renders.

GitHub Actions cannot run the live check. Each site needs a signed-in session, which would mean storing session cookies as repository secrets, and the bot checks that block Playwright here are stricter for datacenter addresses. CI therefore runs the header lint and unit tests, and the live check runs on the maintainer's machine.

## Setup

The check uses [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run --locked playwright install firefox
```

List the conversations to load in `~/.config/maxwidth/config.toml`. Use dedicated test conversations that hold no private content, with at least one short user message and one long one so both message rules are exercised:

```toml
[conversations]
chatgpt = "https://chatgpt.com/c/..."
claude = "https://claude.ai/chat/..."
deepseek = "https://chat.deepseek.com/a/chat/s/..."
```

### Signing in

`firefox_state.py` exports a Firefox profile's sign-ins for the three sites as a Playwright storage state: their cookies, DeepSeek's localStorage sign-in token, and a `userAgent` naming the profile's Firefox version. It needs only the Python standard library and works while Firefox is open. Run it where Firefox is signed in, locally or over SSH:

```sh
python3 firefox_state.py > ~/.config/maxwidth/state.json
ssh HOST python - < firefox_state.py > ~/.config/maxwidth/state.json
```

The file holds live session tokens. Keep it out of the repository (`.gitignore` excludes `state*.json`), give it mode 0600, and delete it when done. The daily job below never writes it to disk.

## Running

```sh
uv run --locked python check.py --state ~/.config/maxwidth/state.json
uv run --locked python check.py chatgpt --state ~/.config/maxwidth/state.json --source published
```

`--source repo` (the default) checks this checkout's CSS; `--source published` downloads what USw currently serves. Unit tests and the header lint need no dependencies:

```sh
python3 -m unittest discover -s tests
python3 lint.py --base origin/main
```

## Daily check

`daily.py` exports the sign-in state, checks the published styles, saves the report to `~/.local/state/maxwidth/last.json`, and runs a notification command when any site's verdict changes from the previous run, or on the first run when a site is BROKEN. Configure it in the same file:

```toml
[daily]
# Gets firefox_state.py on stdin and prints the storage state.
export_command = ["ssh", "HOST", "python", "-"]
# Optional. Gets the subject as its last argument and the report on stdin.
notify_command = ["python3", "/path/to/send-notification.py"]
```

A [systemd](https://systemd.io/) user timer runs it once a day:

```ini
# ~/.config/systemd/user/maxwidth-check.service
[Service]
Type=oneshot
WorkingDirectory=/path/to/maxwidth
ExecStart=uv --no-config run --locked python daily.py
TimeoutStartSec=30min

# ~/.config/systemd/user/maxwidth-check.timer
[Timer]
OnCalendar=*-*-* 10:15
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
```

```sh
systemctl --user enable --now maxwidth-check.timer
journalctl --user -u maxwidth-check.service -n 40
```

If the machine with Firefox is off or unreachable, every site reports BLOCKED for that day.

## Investigating a failure

Every viewport that does not pass saves a screenshot and its measurements under `~/.local/state/maxwidth/runs/<time>/` (or `--artifacts DIR`). The JSON holds the pane, each measured element's left and right edges and width, the style selectors' match counts, and the user-message widths before and after the style. Screenshots show the conversation, so they stay local.

- A stale selector names the rule to update.
- "outside the pane" gives the element's and the pane's edges; compare `transform`, `margin`, and `left` on its ancestors in the browser's inspector.
- "N px wide in a M px pane" means a wrapper still caps the width; walk up from the named element to the first ancestor with a `max-width`.
- A BLOCKED page's screenshot shows what loaded instead.

To watch a run, add `--headed` under a display, or `xvfb-run -a` on a headless machine.

## Publishing

1. Edit the style and raise `@version`. The versions are the UTC time of the change as `YYYYMMDD.HH.MM`; Stylus and USw compare them numerically.
2. Run the live check with `--source repo`, the unit tests, and `python3 lint.py --base origin/main`, then push. Every push to `main` is a release: USw may copy it before CI finishes. CI repeats the tests and the lint, and fails a change to a style's code that leaves `@version` unchanged.
3. USw picks up the change by mirroring the file's raw URL, listed in the table above. To set this up once per style, open the style's edit page on USw, set the source URL to that raw URL, enable "Mirror source code updates", and save. USw checks mirrored styles every four hours, at four minutes past 00:00, 04:00, and so on (UTC), and replaces the code when `@version` differs from the stored one. Opening the raw URL with Stylus installed should show its install page.

## License

Everything in this repository, the styles and the check scripts, is under the [MIT License](LICENSE).
