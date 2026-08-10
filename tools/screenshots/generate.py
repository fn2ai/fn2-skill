#!/usr/bin/env python3
"""Regenerate everything in `docs/media/`.

    python3 tools/screenshots/generate.py            # all scenes
    python3 tools/screenshots/generate.py agents     # just one

Needs a Chromium/Chrome binary on PATH and ImageMagick's `convert` for the
final trim. Nothing here is required to use the skill: it only rebuilds the
documentation images. The terminal text, colour included, is captured from the
real CLI (`capture.py`), so the screenshots cannot drift from what the tool
prints.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import capture  # noqa: E402
import scenes as scenes_mod  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "media"
FONT_DIR = HERE / "fonts"
MARK_SVG = (REPO_ROOT / "assets" / "fn2-mark.svg").read_text(encoding="utf-8")

CHROME_CANDIDATES = ("chromium", "chromium-browser", "google-chrome",
                     "google-chrome-stable", "chrome")

CANVAS = "#0C0D0F"
BORDER_PX = 80  # device pixels at 2x, so 40 CSS px of breathing room
CELL = 9        # JetBrains Mono advance at 15px
MAX_COLS = 120

ANSI_RE = re.compile(r"\033\[([0-9;]*)m")


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------
def _font_face(family: str, filename: str, weight: str) -> str:
    data = base64.b64encode((FONT_DIR / filename).read_bytes()).decode("ascii")
    return (f"@font-face{{font-family:'{family}';font-style:normal;"
            f"font-weight:{weight};src:url(data:font/woff2;base64,{data}) "
            "format('woff2');}")


def fonts_css() -> str:
    return "".join([
        _font_face("JetBrains Mono", "JetBrainsMono-Regular.woff2", "400"),
        _font_face("JetBrains Mono", "JetBrainsMono-Medium.woff2", "500"),
        _font_face("JetBrains Mono", "JetBrainsMono-Bold.woff2", "700"),
        _font_face("Libre Franklin", "LibreFranklin.woff2", "100 900"),
    ])


def mark(size: int) -> str:
    svg = MARK_SVG.replace('width="100" height="100"',
                           f'width="{size}" height="{size}"')
    mark.counter = getattr(mark, "counter", 0) + 1
    return svg.replace("fn2mark", f"fn2mark{mark.counter}")


# The One Dark terminal palette: a real, widely used scheme, so the colours in
# the screenshots are the ones a reader would actually see.
BASE_CSS = """
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:%(canvas)s;}
body{display:inline-block;font-family:'JetBrains Mono',ui-monospace,monospace;
     -webkit-font-smoothing:antialiased;}
.win{position:relative;margin:0;border-radius:10px;width:max-content;
     background:#282C34;border:1px solid rgba(255,255,255,.10);overflow:hidden;}
/* macOS window chrome: vibrancy-grey bar, lights left, title centred. */
.bar{height:38px;display:flex;align-items:center;padding:0 14px;
     background:linear-gradient(180deg,#3A3E46,#31343B);
     border-bottom:1px solid rgba(0,0,0,.45);position:relative;}
.dots{display:flex;gap:8px;z-index:2}
.dot{width:12px;height:12px;border-radius:50%%;
     box-shadow:inset 0 0 0 .5px rgba(0,0,0,.28)}
.title{position:absolute;left:0;right:0;display:flex;gap:7px;
       align-items:center;justify-content:center;pointer-events:none;
       font-family:'Libre Franklin',system-ui,sans-serif;font-size:12.5px;
       font-weight:600;letter-spacing:.005em;color:#C8CCD4;
       text-shadow:0 1px 0 rgba(0,0,0,.35);}
.title svg{display:block;opacity:.9}
.body{padding:14px 18px 16px 18px;font-size:15px;line-height:23px;
      color:#ABB2BF;white-space:pre;}
.line{min-height:23px}
.cmd{color:#E6E9EF}
.host{color:#98C379}
.cwd{color:#61AFEF}
.sigil{color:#C678DD}
.cursor{background:#ABB2BF;color:#282C34}

/* ANSI, as emitted by fn2cli.style */
.a1{color:#F2F4F8;font-weight:700}
.a2{color:#6C7380}
.a31{color:#E06C75}
.a32{color:#98C379}
.a33{color:#E5C07B}
.a34{color:#61AFEF}
.a35{color:#C678DD}
.a36{color:#56B6C2}
"""

CHAT_CSS = """
.chat{padding:16px 18px 14px 18px;font-size:15px;line-height:23px;color:#ABB2BF}
.block{margin-bottom:14px;white-space:pre}
.ask{color:#E6E9EF}
.ask .caret{color:#6C7380}
.bullet{color:#98C379}
.say{color:#D2D8E2}
.tool .name{color:#E6E9EF;font-weight:500}
.tool .args{color:#8A919E}
.res{color:#7C8493}
.corner{color:#565D6B}
.prompt-box{margin-top:4px;border:1px solid #3E4451;border-radius:6px;
     padding:3px 12px;color:#6C7380;white-space:pre}
.prompt-box .caret{color:#98C379}
.foot{color:#4E5563;padding:6px 0 0 4px;font-size:14px}
"""


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------
def visible(text: str) -> str:
    return ANSI_RE.sub("", text)


def ansi_to_html(text: str) -> str:
    """One line of ANSI into spans. Escapes never straddle a newline."""
    out: List[str] = []
    depth = 0
    for index, part in enumerate(ANSI_RE.split(text)):
        if index % 2 == 0:
            out.append(html.escape(part))
            continue
        codes = [c for c in part.split(";") if c]
        if not codes or codes == ["0"]:
            out.append("</span>" * depth)
            depth = 0
        else:
            out.append('<span class="%s">' % " ".join("a" + c for c in codes))
            depth += 1
    out.append("</span>" * depth)
    return "".join(out)


def wrap_command(text: str, cols: int, indent: str) -> List[str]:
    """Wrap a long command the way a terminal or Claude Code shows it."""
    if len(text) <= cols:
        return [text]
    return textwrap.wrap(text, width=cols, subsequent_indent=indent,
                         break_long_words=False, break_on_hyphens=False) or [text]


def fit(minimum: int, lines: List[str]) -> int:
    longest = max((len(visible(line)) for line in lines), default=0)
    return max(minimum, min(longest + 2, MAX_COLS))


# ---------------------------------------------------------------------------
# window chrome
# ---------------------------------------------------------------------------
def _dots() -> str:
    colors = ("#FF5F57", "#FEBC2E", "#28C840")
    return ('<span class="dots">'
            + "".join(f'<span class="dot" style="background:{c}"></span>'
                      for c in colors) + "</span>")


def _titlebar(title: str, *, brand: bool = True) -> str:
    icon = mark(14) if brand else ""
    return (f'<div class="bar">{_dots()}'
            f'<span class="title">{icon}<span>{html.escape(title)}</span></span>'
            f'</div>')


PROMPT = ('<span class="host">you@mbp</span> <span class="cwd">~</span> '
          '<span class="sigil">%</span> ')
PROMPT_COLS = len("you@mbp ~ % ")


def terminal_html(scene: Dict[str, Any], captured: List[Dict[str, str]]) -> str:
    measured = [visible(line)
                for entry in captured for line in entry["output"].split("\n")]
    cols = fit(scene["cols"], measured)
    rows: List[str] = []
    for index, entry in enumerate(captured):
        if index:
            rows.append('<div class="line">&nbsp;</div>')
        pieces = wrap_command(entry["command"], cols - PROMPT_COLS, "    ")
        for i, piece in enumerate(pieces):
            lead = PROMPT if i == 0 else " " * PROMPT_COLS
            rows.append(f'<div class="line cmd">{lead}{html.escape(piece)}</div>')
        for line in entry["output"].split("\n"):
            rows.append(f'<div class="line">{ansi_to_html(line) or "&nbsp;"}</div>')
    rows.append(f'<div class="line">{PROMPT}<span class="cursor">&nbsp;</span></div>')
    body = f'<div class="body">{"".join(rows)}</div>'
    return (f'<div class="win" style="min-width:{cols * CELL + 40}px">'
            f'{_titlebar(scene["title"])}{body}</div>')


def chat_html(scene: Dict[str, Any], captured: List[Dict[str, str]]) -> str:
    measured = ["     " + visible(line)
                for entry in captured for line in entry["output"].split("\n")]
    cols = fit(scene["cols"], measured)
    blocks: List[str] = []
    for message in scene["messages"]:
        role = message["role"]
        if role == "user":
            lines = scenes_mod.wrap(message["text"], cols - 4)
            body = "\n  ".join(html.escape(line) for line in lines)
            blocks.append(f'<div class="block ask">'
                          f'<span class="caret">&gt;</span> {body}</div>')
        elif role == "assistant":
            lines = scenes_mod.wrap(message["text"], cols - 3)
            body = "\n  ".join(html.escape(line) for line in lines)
            blocks.append(f'<div class="block say">'
                          f'<span class="bullet">⏺</span> {body}</div>')
        else:
            entry = captured[message["capture"]]
            head_lines = wrap_command(f'Bash({entry["command"]})', cols - 2, "      ")
            head = f'<span class="bullet">⏺</span> '
            head += f'<span class="name">{html.escape(head_lines[0][:4])}</span>'
            head += '<span class="args">' + html.escape(head_lines[0][4:])
            for extra in head_lines[1:]:
                head += "\n  " + html.escape(extra)
            head += "</span>"
            rendered = []
            for i, line in enumerate(entry["output"].split("\n")):
                lead = ('  <span class="corner">⎿</span>  ' if i == 0 else "     ")
                rendered.append(lead + ansi_to_html(line))
            blocks.append(f'<div class="block tool">{head}\n'
                          '<span class="res">' + "\n".join(rendered) + "</span></div>")

    hint = scene.get("hint", "Try \"what changed in my watchlist today?\"")
    box = (f'<div class="prompt-box"><span class="caret">&gt;</span> '
           f'{html.escape(hint)}</div>'
           f'<div class="foot">? for shortcuts</div>')
    body = f'<div class="chat">{"".join(blocks)}{box}</div>'
    return (f'<div class="win" style="min-width:{cols * CELL + 36}px">'
            f'{_titlebar(scene["title"], brand=False)}{body}</div>')


def page(body: str, extra_css: str = "") -> str:
    css = fonts_css() + (BASE_CSS % {"canvas": CANVAS}) + CHAT_CSS + extra_css
    return f"<!doctype html><meta charset=utf-8><style>{css}</style>{body}"


# ---------------------------------------------------------------------------
# banner + social card
# ---------------------------------------------------------------------------
BRAND_CSS = """
.stage{width:%(w)spx;height:%(h)spx;background:
   radial-gradient(900px 380px at 8%% -30%%,rgba(255,120,20,.09),transparent 62%%),
   #0C0D0F;display:flex;flex-direction:column;justify-content:center;
   align-items:%(align)s;text-align:%(text)s;
   padding:%(pad)spx;position:relative;overflow:hidden;}
.stage:after{content:"";position:absolute;inset:0;
   background-image:linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),
                    linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px);
   background-size:46px 46px;
   mask-image:radial-gradient(72%% 72%% at 26%% 18%%,#000,transparent);}
.lockup{display:flex;align-items:center;gap:%(gap)spx;position:relative;z-index:1}
.word{font-family:'Libre Franklin',system-ui,sans-serif;font-weight:600;
      letter-spacing:-.02em;line-height:1;color:#EDF1F6;font-size:%(word)spx}
.word .kind{color:#7E8797;font-weight:500}
.tag{font-family:'Libre Franklin',system-ui,sans-serif;color:#98A1B1;
     font-size:%(tag)spx;line-height:1.45;margin-top:%(tagtop)spx;
     position:relative;z-index:1;max-width:%(tagw)spx}
.tag b{color:#DEE4EC;font-weight:600}
.repo{position:absolute;left:0;right:0;bottom:%(pad)spx;text-align:center;
      font-family:'JetBrains Mono',monospace;font-size:%(chip)spx;color:#5C6472;z-index:1}
"""


def banner_html(width: int, height: int, *, social: bool) -> str:
    tokens = {
        "w": width, "h": height,
        "pad": 58 if social else 44,
        "gap": 26 if social else 20,
        "word": 84 if social else 54,
        "tag": 27 if social else 19,
        "tagtop": 26 if social else 16,
        "tagw": 960 if social else 780,
        "chip": 17 if social else 14,
        "align": "center",
        "text": "center",
    }
    tagline = ("Start, watch, and schedule <b>FN2 AI research agents</b><br>"
               "right from Claude&nbsp;Code, Codex, or&nbsp;Pi.")
    repo = ('<div class="repo">github.com/fn2ai/fn2-skill</div>' if social else "")
    body = (f'<div class="stage">'
            f'<div class="lockup">{mark(94 if social else 62)}'
            f'<div class="word">FN2 AI <span class="kind">skill</span></div></div>'
            f'<div class="tag">{tagline}</div>{repo}</div>')
    return page(body, BRAND_CSS % tokens)


# ---------------------------------------------------------------------------
# chrome driver
# ---------------------------------------------------------------------------
def find_chrome() -> str:
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit("no Chromium/Chrome binary found; install one to rebuild the media")


def shoot(chrome: str, html_text: str, out: Path, *, width: int, height: int,
          trim: bool, resize: Optional[str] = None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "scene.html"
        src.write_text(html_text, encoding="utf-8")
        raw = Path(tmp) / "raw.png"
        subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
             "--force-device-scale-factor=2", f"--window-size={width},{height}",
             "--virtual-time-budget=4000", f"--screenshot={raw}", str(src)],
            check=True, capture_output=True,
        )
        args = ["convert", str(raw)]
        if trim:
            args += ["-trim", "+repage", "-bordercolor", CANVAS,
                     "-border", f"{BORDER_PX}x{BORDER_PX}"]
        if resize:
            args += ["-resize", resize]
        args += ["-strip", str(out)]
        subprocess.run(args, check=True, capture_output=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def estimate_height(scene: Dict[str, Any], captured: List[Dict[str, str]]) -> int:
    lines = 6
    for entry in captured:
        lines += len(entry["command"]) // 60 + 2
        lines += entry["output"].count("\n") + 2
    if scene["kind"] == "chat":
        lines += sum(len(scenes_mod.wrap(m.get("text", ""), 60)) + 2
                     for m in scene["messages"] if m["role"] != "tool")
    return 260 + lines * 23


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("only", nargs="*", help="scene names to rebuild (default: all)")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--home", default=None,
                        help="demo HOME whose path shows in `fn2 doctor` output")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    now = dt.datetime.now(dt.timezone.utc)

    with tempfile.TemporaryDirectory() as tmp_home:
        home = Path(args.home) if args.home else Path(tmp_home)
        home.mkdir(parents=True, exist_ok=True)

        for scene in scenes_mod.build():
            if args.only and scene["name"] not in args.only:
                continue
            commands = scene.get("capture") or scene.get("commands") or []
            captured = capture.run_session(commands, home=home, now=now)
            builder = chat_html if scene["kind"] == "chat" else terminal_html
            markup = page(builder(scene, captured))
            target = out_dir / f"{scene['name']}.png"
            # Viewport wide enough for the widest window; the trim crops back
            # to the content, so slack costs nothing.
            shoot(chrome, markup, target,
                  width=MAX_COLS * CELL + 260,
                  height=estimate_height(scene, captured),
                  trim=True)
            print(f"  {target.relative_to(REPO_ROOT)}")

    if not args.only or "banner" in args.only:
        target = out_dir / "banner.png"
        shoot(chrome, banner_html(1100, 260, social=False), target,
              width=1100, height=260, trim=False, resize="1100x260")
        print(f"  {target.relative_to(REPO_ROOT)}")

    if not args.only or "social-card" in args.only:
        target = out_dir / "social-card.png"
        shoot(chrome, banner_html(1280, 640, social=True), target,
              width=1280, height=640, trim=False, resize="1280x640")
        print(f"  {target.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
