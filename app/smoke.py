"""Run the finished page in a real browser and read back what actually happened.

The static checker accepted a page that emptied its own `snake` array on the
first tick: the head was never pushed back, so the next frame threw
"TypeError: snake[0] is not iterable" and the canvas stayed blank. The source
looked complete. Reading code cannot prove it runs.

Windows ships Edge, so the page can be executed headless and offline: a probe
injected before the page's own script records JS errors, draw calls and input
listeners, then writes the result into the DOM that `--dump-dom` prints back.

If no browser is found this returns [] (unverified) rather than inventing a
failure - a missing checker must not look like a broken page.
"""

from __future__ import annotations

import html as htmlmod
import json
import os
import re
import shutil
import subprocess
import tempfile

BUDGET_MS = 1100
CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)

# Injected before the page's own script so it wraps addEventListener first and
# therefore sees the game's listeners being registered.
PROBE = """<script>
(function () {
  var log = {errors: [], draws: 0, inputs: 0};
  window.addEventListener('error', function (e) {
    log.errors.push(String((e && e.message) || e));
  });
  var fill = CanvasRenderingContext2D.prototype.fillRect;
  CanvasRenderingContext2D.prototype.fillRect = function () {
    log.draws++;
    return fill.apply(this, arguments);
  };
  var listen = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type) {
    if (/^(keydown|keyup|pointerdown|touchstart)$/.test(String(type))) log.inputs++;
    return listen.apply(this, arguments);
  };
  setTimeout(function () {
    var canvas = document.querySelector('canvas');
    var out = document.createElement('pre');
    out.id = '__probe';
    out.textContent = JSON.stringify({
      errors: log.errors.slice(0, 3),
      draws: log.draws,
      inputs: log.inputs,
      canvas: canvas ? [canvas.width, canvas.height] : null,
      score: (document.getElementById('score') || {}).textContent || null
    });
    document.body.appendChild(out);
  }, %d);
})();
</script>""" % (BUDGET_MS - 300)

PROBE_RE = re.compile(r'id="__probe"[^>]*>(.*?)</pre>', re.S)


def browser() -> str:
    for path in CANDIDATES:
        if os.path.isfile(path):
            return path
    for name in ("msedge", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def _instrument(page: str) -> str:
    """Put the probe before the page's first script, keeping the page intact."""
    lowered = page.lower()
    for anchor in ("<head>", "<html>", "<!doctype"):
        at = lowered.find(anchor)
        if at >= 0:
            end = at + len(anchor)
            return page[:end] + PROBE + page[end:]
    return PROBE + page


def _extract(dom: str):
    match = PROBE_RE.search(dom or "")
    if not match:
        return None
    try:
        return json.loads(htmlmod.unescape(match.group(1)))
    except ValueError:
        return None


def _run(exe: str, url: str, profile: str, flag: str):
    return subprocess.run(
        [exe, flag, "--disable-gpu", "--disable-extensions", "--no-first-run",
         "--no-default-browser-check", "--hide-scrollbars",
         "--user-data-dir=" + profile, "--virtual-time-budget=%d" % BUDGET_MS,
         "--dump-dom", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=45)


def check(workspace: str, path: str) -> list:
    """Defects seen by actually loading the page, [] when it runs or is unproven."""
    exe = browser()
    if not exe:
        return []
    full = os.path.join(workspace, path)
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            page = fh.read()
    except OSError:
        return ["%s could not be read for a browser check." % path]

    temp = tempfile.mkdtemp(prefix="codemode-smoke-")
    profile = os.path.join(temp, "profile")
    target = os.path.join(temp, os.path.basename(path) or "page.html")
    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(_instrument(page))
        url = "file:///" + target.replace("\\", "/")
        try:
            done = _run(exe, url, profile, "--headless=new")
        except subprocess.TimeoutExpired:
            return []
        data = _extract(done.stdout)
        if data is None:
            try:
                done = _run(exe, url, profile + "-2", "--headless")
            except subprocess.TimeoutExpired:
                return []
            data = _extract(done.stdout)
        if data is None:
            return []

        defects = []
        errors = [str(e) for e in data.get("errors") or [] if e]
        if errors:
            defects.append(
                "%s throws in the browser the moment it runs: %s Fix the script - "
                "as it stands the page never gets going." % (path, errors[0][:180]))
        if data.get("canvas") and not data.get("draws"):
            defects.append(
                "%s draws nothing: a second after loading, the canvas has had no "
                "drawing calls, so the player sees an empty box." % path)
        if data.get("canvas") and not data.get("inputs"):
            defects.append(
                "%s never registers keyboard or touch input, so nothing the player "
                "presses can steer." % path)
        return defects
    finally:
        shutil.rmtree(temp, ignore_errors=True)
