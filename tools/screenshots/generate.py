#!/usr/bin/env python3
"""Regenerate everything in `docs/media/`.

    python3 tools/screenshots/generate.py            # all scenes
    python3 tools/screenshots/generate.py agents     # just one

Needs a Chromium/Chrome binary on PATH and ImageMagick's `convert` for the
final trim. Nothing here is required to use the skill — it only rebuilds the
documentation images. The terminal text is captured from the real CLI
(`capture.py`), so the screenshots cannot drift from what the tool prints.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import shutil
import subprocess
import sys
import tempfile
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

CANVAS = "#08090B"
BORDER_PX = 88  # device pixels at 2x -> 44 CSS px of breathing room


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
    # Unique gradient ids so several marks can share one document.
    mark.counter = getattr(mark, "counter", 0) + 1
    return svg.replace("fn2mark", f"fn2mark{mark.counter}")


BASE_CSS = """
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:%(canvas)s;}
body{display:inline-block;font-family:'JetBrains Mono',ui-monospace,monospace;
     -webkit-font-smoothing:antialiased;}
/* No drop shadow: the canvas is near-black, so a shadow only smears the
   trim box. Depth comes from the panel/canvas contrast and the header. */
/* max-content, not a computed pixel width: a few glyphs the mono font lacks
   (→, ★, ✓) fall back to a face with a different advance, so a width derived
   from character counts would clip them. The column count is only a floor. */
.win{position:relative;margin:0;border-radius:14px;width:max-content;
     background:#0D0F13;border:1px solid rgba(255,255,255,.09);
     overflow:hidden;}
.bar{height:44px;display:flex;align-items:center;padding:0 16px;
     background:linear-gradient(180deg,#171A20,#12151A);
     border-bottom:1px solid rgba(255,255,255,.06);position:relative;}
.dots{display:flex;gap:8px}
.dot{width:12px;height:12px;border-radius:50%%}
.title{position:absolute;left:0;right:0;display:flex;gap:8px;
       align-items:center;justify-content:center;pointer-events:none;
       font-family:'Libre Franklin',system-ui,sans-serif;font-size:12.5px;
       font-weight:500;letter-spacing:.01em;color:#8B93A2;}
.title svg{display:block;opacity:.95}
.accent{height:2px;background:linear-gradient(90deg,#FF3F00,#FF8E00 55%%,#FFCA00);
        opacity:.85}
.body{padding:18px 22px 22px 22px;font-size:15px;line-height:24px;
      color:#C3CAD6;white-space:pre;}
.line{min-height:24px}
.cmd{color:#F2F5F9;font-weight:500}
.prompt{color:#FF8E00;font-weight:700}
.dim{color:#6E7787}
.gap{height:24px}
"""

CHAT_CSS = """
.chat{padding:20px 22px 24px 22px;font-size:15px;line-height:24px;color:#C3CAD6}
.ask{border:1px solid rgba(255,255,255,.10);border-radius:8px;
     padding:9px 14px;margin-bottom:18px;background:#0A0C10;color:#E9EDF3;
     white-space:pre}
.ask .caret{color:#FF8E00;font-weight:700}
.block{margin-bottom:16px;white-space:pre}
.bullet{color:#FF8E00}
.say{color:#D5DBE5}
.tool{color:#9AA3B2}
.toolname{color:#E9EDF3;font-weight:500}
.res{color:#7F8899}
.corner{color:#4E5665}
"""


# ---------------------------------------------------------------------------
# html builders
# ---------------------------------------------------------------------------
def _dots() -> str:
    colors = ("#FF5F57", "#FEBC2E", "#28C840")
    return ('<span class="dots">'
            + "".join(f'<span class="dot" style="background:{c}"></span>' for c in colors)
            + "</span>")


def _titlebar(title: str) -> str:
    return (f'<div class="bar">{_dots()}'
            f'<span class="title">{mark(15)}<span>{html.escape(title)}</span></span>'
            f'</div><div class="accent"></div>')


MAX_COLS = 118


def hard_wrap(line: str, cols: int) -> List[str]:
    """Wrap the way a terminal does: at the column, not at a word boundary."""
    if len(line) <= cols:
        return [line]
    return [line[i:i + cols] for i in range(0, len(line), cols)] or [""]


def fit(minimum: int, lines: List[str]) -> int:
    longest = max((len(line) for line in lines), default=0)
    return max(minimum, min(longest + 2, MAX_COLS))


def _cmd_lines(shown: str, cols: int) -> str:
    out = []
    first = True
    for part in shown.split("\n"):
        for piece in hard_wrap(part, cols - 2):
            prefix = '<span class="prompt">❯</span> ' if first else ""
            out.append(f'<div class="line cmd">{prefix}{html.escape(piece)}</div>')
            first = False
    return "".join(out)


def terminal_html(scene: Dict[str, Any], captured: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for entry in captured:
        lines += [c + "  " for c in entry["command"].split("\n")]
        lines += entry["output"].split("\n")
    cols = fit(scene["cols"], lines)
    width = cols * 9 + 44
    rows: List[str] = []
    for index, entry in enumerate(captured):
        if index:
            rows.append('<div class="gap"></div>')
        rows.append(_cmd_lines(entry["command"], cols))
        for line in entry["output"].split("\n"):
            for piece in hard_wrap(line, cols):
                rows.append(f'<div class="line">{html.escape(piece) or "&nbsp;"}</div>')
    body = f'<div class="body">{"".join(rows)}</div>'
    return (f'<div class="win" style="min-width:{width}px">'
            f'{_titlebar(scene["title"])}{body}</div>')


def chat_html(scene: Dict[str, Any], captured: List[Dict[str, str]]) -> str:
    measured: List[str] = []
    for entry in captured:
        measured += ["⏺ Bash(" + c + ")" for c in entry["command"].split("\n")]
        measured += ["     " + line for line in entry["output"].split("\n")]
    cols = fit(scene["cols"], measured)
    width = cols * 9 + 44
    blocks: List[str] = []
    for message in scene["messages"]:
        role = message["role"]
        if role == "user":
            lines = scenes_mod.wrap(message["text"], cols - 6)
            text = "\n".join(lines)
            blocks.append(f'<div class="ask"><span class="caret">&gt;</span> '
                          f'{html.escape(text)}</div>')
        elif role == "assistant":
            lines = scenes_mod.wrap(message["text"], cols - 3)
            body = "\n   ".join(html.escape(line) for line in lines)
            blocks.append(f'<div class="block say">'
                          f'<span class="bullet">⏺</span> {body}</div>')
        else:
            entry = captured[message["capture"]]
            command = html.escape(entry["command"])
            head = (f'<span class="bullet">⏺</span> '
                    f'<span class="toolname">Bash</span>'
                    f'<span class="tool">({command})</span>')
            out_lines: List[str] = []
            for line in entry["output"].split("\n"):
                out_lines += hard_wrap(line, cols - 5)
            rendered = []
            for i, line in enumerate(out_lines):
                lead = ('  <span class="corner">⎿</span>  ' if i == 0
                        else '     ')
                rendered.append(lead + html.escape(line))
            blocks.append(f'<div class="block tool">{head}\n'
                          f'<span class="res">' + "\n".join(rendered) + "</span></div>")
    body = f'<div class="chat">{"".join(blocks)}</div>'
    return (f'<div class="win" style="min-width:{width}px">'
            f'{_titlebar(scene["title"])}{body}</div>')


def page(body: str, extra_css: str = "") -> str:
    css = fonts_css() + (BASE_CSS % {"canvas": CANVAS}) + CHAT_CSS + extra_css
    return f"<!doctype html><meta charset=utf-8><style>{css}</style>{body}"


# ---------------------------------------------------------------------------
# banner + social card
# ---------------------------------------------------------------------------
BRAND_CSS = """
.stage{width:%(w)spx;height:%(h)spx;background:
   radial-gradient(1100px 460px at 12%% -20%%,rgba(255,110,0,.20),transparent 60%%),
   radial-gradient(900px 420px at 100%% 120%%,rgba(255,180,0,.10),transparent 60%%),
   #08090B;display:flex;flex-direction:column;justify-content:center;
   align-items:%(align)s;text-align:%(text)s;
   padding:%(pad)spx;position:relative;overflow:hidden;}
.stage:after{content:"";position:absolute;inset:0;
   background-image:linear-gradient(rgba(255,255,255,.022) 1px,transparent 1px),
                    linear-gradient(90deg,rgba(255,255,255,.022) 1px,transparent 1px);
   background-size:44px 44px;mask-image:radial-gradient(70%% 70%% at 30%% 20%%,#000,transparent);}
.lockup{display:flex;align-items:center;gap:%(gap)spx;position:relative;z-index:1}
.word{font-family:'Libre Franklin',system-ui,sans-serif;font-weight:600;
      letter-spacing:-.018em;line-height:1;color:#EEF2F7;font-size:%(word)spx}
.word .tld{color:#828B9B;font-weight:500}
.word .kind{color:transparent;background:linear-gradient(90deg,#FF5A00,#FFB300);
            -webkit-background-clip:text;background-clip:text;font-weight:600}
.tag{font-family:'Libre Franklin',system-ui,sans-serif;color:#98A1B1;
     font-size:%(tag)spx;line-height:1.45;margin-top:%(tagtop)spx;position:relative;z-index:1;
     max-width:%(tagw)spx}
.tag b{color:#DCE3EC;font-weight:600}
.chips{display:flex;gap:10px;margin-top:%(chiptop)spx;position:relative;z-index:1;
       flex-wrap:wrap;justify-content:%(align)s}
.chip{font-family:'JetBrains Mono',monospace;font-size:%(chip)spx;color:#C6CDD9;
      border:1px solid rgba(255,255,255,.10);background:rgba(255,255,255,.035);
      border-radius:999px;padding:7px 14px}
.chip .k{color:#FF9A2E}
.repo{position:absolute;left:0;right:0;bottom:%(pad)spx;text-align:center;
      font-family:'JetBrains Mono',monospace;font-size:%(chip)spx;color:#6C7585;z-index:1}
"""


def banner_html(width: int, height: int, *, social: bool) -> str:
    tokens = {
        "w": width, "h": height,
        "pad": 56 if social else 48,
        "gap": 26 if social else 20,
        "word": 86 if social else 54,
        "tag": 27 if social else 19,
        "tagtop": 28 if social else 16,
        "tagw": 940 if social else 760,
        "chip": 17 if social else 14,
        "chiptop": 36 if social else 22,
        "align": "center" if social else "flex-start",
        "text": "center" if social else "left",
    }
    chips = "".join(
        f'<span class="chip"><span class="k">{k}</span> {v}</span>'
        for k, v in (("start", "\"track unusual options flow\""),
                     ("--when", "\"before market open\""),
                     ("result", "read it in your terminal"))
    )
    tagline = ("Start, watch, and schedule <b>fn2.ai research agents</b><br>"
               "right from Claude&nbsp;Code, Codex, or&nbsp;Pi.")
    repo = ('<div class="repo">github.com/fn2ai/fn2-skill</div>' if social else "")
    body = (f'<div class="stage">'
            f'<div class="lockup">{mark(96 if social else 64)}'
            f'<div class="word">FN2<span class="tld">.AI</span> '
            f'<span class="kind">skill</span></div></div>'
            f'<div class="tag">{tagline}</div>'
            f'<div class="chips">{chips}</div>{repo}</div>')
    return page(body, BRAND_CSS % tokens)


# ---------------------------------------------------------------------------
# chrome driver
# ---------------------------------------------------------------------------
def find_chrome() -> str:
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit("no Chromium/Chrome binary found — install one to rebuild the media")


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
    lines = 0
    for entry in captured:
        lines += entry["command"].count("\n") + 1
        lines += entry["output"].count("\n") + 2
    if scene["kind"] == "chat":
        lines += sum(len(scenes_mod.wrap(m.get("text", ""), scene["cols"])) + 2
                     for m in scene["messages"] if m["role"] != "tool")
    return 200 + lines * 24


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
            # Viewport wide enough for the widest possible window; the trim
            # crops back to the content, so slack costs nothing.
            shoot(chrome, markup, target,
                  width=MAX_COLS * 9 + 260,
                  height=estimate_height(scene, captured),
                  trim=True)
            print(f"  {target.relative_to(REPO_ROOT)}")

    if not args.only or "banner" in args.only:
        target = out_dir / "banner.png"
        shoot(chrome, banner_html(1200, 300, social=False), target,
              width=1200, height=300, trim=False, resize="1200x300")
        print(f"  {target.relative_to(REPO_ROOT)}")

    if not args.only or "social-card" in args.only:
        target = out_dir / "social-card.png"
        shoot(chrome, banner_html(1280, 640, social=True), target,
              width=1280, height=640, trim=False, resize="1280x640")
        print(f"  {target.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
