"""Does the thing the model said it built actually work?

A 3B model will happily write

    <canvas id="snakeCanvas"></canvas>
    <script src="app/client.js"></script>

next to a `client.js` that contains `// Game logic goes here`, then report "the
game is running successfully". Nothing in the old loop looked, so the user got a
blank rectangle and no way to play.

This module is the part that looks. It does not try to be a browser: it checks
the failures that actually happened on this machine - a stub instead of code, a
<script src> pointing at a path that is not there, a canvas nothing listens to,
a loop that never moves the snake - and returns defects phrased so a small model
can act on them. An empty list means "no known defect", not "proven to work".
"""

from __future__ import annotations

import ast
import os
import re

# Stubs seen in real output from qwen2.5-coder:3b on this machine.
STUB_RE = re.compile(
    r"(game logic goes here|logic goes here|your code here|code goes here|"
    r"\bTODO\b|not implemented|coming soon|rest of (the )?(code|logic))",
    re.I,
)
# "// Initialize snake logic here", "// Draw snake on canvas here": the observed
# stubs all end a comment in "here".
PLACEHOLDER_COMMENT_RE = re.compile(r"//[^\n]*\bhere\b|/\*.*?\bhere\b.*?\*/", re.S | re.I)
EMPTY_FUNC_RE = re.compile(
    r"(?:function\s*\w*\s*\([^)]*\)|\([^)]*\)\s*=>|[\w$.]+\s*=>)\s*\{\s*\}")
CONTEXT_RE = re.compile(r"(getContext|createElement\s*\(\s*['\"]canvas)", re.I)
ELEMENT_REF_RE = re.compile(r"getElementById\s*\(\s*['\"]([^'\"]+)['\"]", re.I)
ID_RE = re.compile(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", re.I)
DOM_DRAW_RE = re.compile(
    r"(fillRect|clearRect|fillStyle|strokeStyle|innerHTML|textContent|innerText)", re.I)
RAF_RE = re.compile(r"requestAnimationFrame", re.I)
# Anything that makes a requestAnimationFrame loop advance at a sane speed.
THROTTLE_RE = re.compile(
    r"(setInterval|setTimeout|Date\.now|performance\.now|lastTime|lastFrame|deltaTime)", re.I)
SCORE_RE = re.compile(r"\bscore\b", re.I)
SCORE_SHOW_RE = re.compile(
    r"(textContent|innerText|innerHTML|fillText)\s*(\(|=)[^;\n]{0,80}score", re.I)

REF_RE = re.compile(r"""<(script|link|img)\b[^>]*?\b(?:src|href)\s*=\s*["']([^"']+)["']""", re.I)
CANVAS_RE = re.compile(r"<canvas\b", re.I)
LOOP_RE = re.compile(r"(requestAnimationFrame|setInterval|setTimeout)", re.I)
INPUT_RE = re.compile(r"(addEventListener\s*\(\s*['\"](keydown|keyup|touchstart|pointerdown)|onkeydown|onkeyup|ontouchstart)", re.I)
SCRIPT_TAG_RE = re.compile(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.S | re.I)

# Below this, an HTML file cannot be a finished game however you read it.
MIN_HTML = 700
MIN_CODE = 120


def _rel(path: str) -> str:
    return path.replace(os.sep, "/")


def _strip_comments(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"//[^\n]*", "", js)


def _script_bodies(text: str) -> list:
    """Inline script sources, without the tags that load a separate file."""
    return [body for attrs, body in SCRIPT_TAG_RE.findall(text)
            if "src=" not in attrs.lower()]


def check_script(path: str, script: str) -> list:
    """A stub wearing the shape of a program: functions with nothing in them."""
    defects = []
    code = _strip_comments(script)
    if not code.strip():
        return ["%s has an inline <script> that is only comments." % path]

    empty = EMPTY_FUNC_RE.findall(code)
    if empty:
        names = ", ".join(" ".join(e.split())[:44] for e in empty[:3])
        defects.append(
            "%s defines %d function%s with an empty body (%s), so calling them does "
            "nothing. Fill them with the real game code."
            % (path, len(empty), "" if len(empty) == 1 else "s", names))

    if LOOP_RE.search(code) and not CONTEXT_RE.search(code) and not DOM_DRAW_RE.search(code):
        defects.append("%s runs a loop but never gets a drawing context "
                       "(getContext('2d')) and never paints, so the screen stays blank."
                       % path)

    if CANVAS_RE.search(code) or CONTEXT_RE.search(code):
        if RAF_RE.search(code) and not THROTTLE_RE.search(code):
            defects.append(
                "%s moves the snake once per animation frame - about sixty squares a "
                "second on a 400px board, so it hits the wall before the player can "
                "react. Pace it: setInterval(step, 120), or skip frames against a "
                "Date.now() timestamp." % path)
        if SCORE_RE.search(code) and not SCORE_SHOW_RE.search(code):
            defects.append(
                "%s counts a score but never shows it. Write it into an element "
                "(e.g. document.getElementById('score').textContent = score) and "
                "put that element in the page." % path)
    return defects


def _stub_line(text: str):
    match = STUB_RE.search(text)
    if not match:
        return None
    for line in text.splitlines():
        if STUB_RE.search(line):
            return line.strip()[:90]
    return match.group(0)


def check_html(workspace: str, path: str, text: str) -> list:
    """Defects that would stop this page from being a playable game."""
    defects = []
    folder = os.path.dirname(os.path.join(workspace, path))

    if len(text) < MIN_HTML:
        defects.append(
            "%s is only %d bytes. That is a stub, not a finished page: write it "
            "again in full - the markup, the CSS and the whole game script."
            % (path, len(text)))

    stub_lines = [line.strip()[:90] for line in text.splitlines()
                  if PLACEHOLDER_COMMENT_RE.search(line) or STUB_RE.search(line)]
    if stub_lines:
        defects.append("%s still contains %d placeholder line%s, starting with %r. "
                       "Replace each one with the real code."
                       % (path, len(stub_lines),
                          "" if len(stub_lines) == 1 else "s", stub_lines[0]))

    for tag, ref in REF_RE.findall(text):
        if re.match(r"(https?:|data:|//|#|mailto:)", ref, re.I):
            continue
        target = os.path.abspath(os.path.join(folder, ref))
        if not (target == os.path.abspath(workspace)
                or target.startswith(os.path.abspath(workspace) + os.sep)):
            defects.append("%s loads %r, which is outside the workspace." % (path, ref))
        elif not os.path.isfile(target):
            defects.append(
                "%s loads %r but no such file exists next to it. Either create "
                "that file or inline the code in a <script> block."
                % (path, ref))
        elif os.path.getsize(target) < MIN_CODE:
            defects.append("%s loads %r, which is only %d bytes - empty or a stub."
                           % (path, ref, os.path.getsize(target)))

    bodies = _script_bodies(text)
    for body in bodies:
        if body.strip() and len(body) < MIN_CODE:
            defects.append("the inline <script> in %s is only %d bytes of code."
                           % (path, len(body.strip())))
    script = "\n".join(bodies)
    if script.strip():
        defects.extend(check_script(path, script))
    code = _strip_comments(script)
    has_loop = bool(LOOP_RE.search(code))
    has_input = bool(INPUT_RE.search(code))

    # A script that looks up an element must mean one that exists on the page:
    # the same bug as a dead <script src>, one level in.
    ids = set(ID_RE.findall(text))
    for ref in ELEMENT_REF_RE.findall(code):
        if ref not in ids and "createElement" not in code:
            defects.append("%s looks up element #%s, which is not in the page."
                           % (path, ref))

    if CANVAS_RE.search(text):
        if not has_loop:
            defects.append("%s draws a canvas but never runs a loop "
                           "(requestAnimationFrame or setInterval), so nothing moves." % path)
        if not has_input:
            defects.append("%s has a canvas but no keyboard or pointer listener, so "
                           "the player cannot control the snake." % path)
    if has_loop and not has_input:
        defects.append("%s never listens for input, so the player cannot steer." % path)
    return defects


def check_python(workspace: str, path: str, text: str) -> list:
    full = os.path.join(workspace, path)
    try:
        ast.parse(text, filename=full)
    except SyntaxError as exc:
        return ["%s does not parse: line %s: %s. Fix it and write the file again."
                % (path, exc.lineno, exc.msg)]
    stub = _stub_line(text)
    if stub:
        return ["%s still contains a placeholder: %r. Replace it with real code."
                % (path, stub)]
    return []


def check_file(workspace: str, path: str) -> list:
    """Defects for one file the model said it wrote. [] when nothing is wrong."""
    full = os.path.join(workspace, path)
    if not os.path.isfile(full):
        return ["%s was never written: the path does not exist." % path]
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        return ["%s could not be read back: %s" % (path, exc)]
    if not text.strip():
        return ["%s is empty." % path]

    lower = path.lower()
    if lower.endswith((".html", ".htm")):
        return check_html(workspace, path, text)
    if lower.endswith(".py"):
        return check_python(workspace, path, text)
    return []


def check_turn(workspace: str, paths) -> list:
    """Defects across every file written this turn, in a stable order."""
    defects = []
    seen = set()
    for path in paths:
        key = _rel(path)
        if key in seen:
            continue
        seen.add(key)
        defects.extend(check_file(workspace, path))
    return defects


def playable(workspace: str, path: str) -> bool:
    """True for an HTML artifact with no known defect - worth opening for the user."""
    return path.lower().endswith((".html", ".htm")) and not check_file(workspace, path)
