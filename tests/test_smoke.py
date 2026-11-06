"""The browser check: reading the source is not the same as running it."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import smoke  # noqa: E402

GOOD = """<!doctype html><html><head><title>t</title></head><body>
<canvas id="c" width="200" height="200"></canvas><p id="score">0</p>
<script>
const g = document.getElementById('c').getContext('2d');
let n = 0;
document.addEventListener('keydown', e => { n++; });
setInterval(() => { g.fillRect(n % 200, 10, 10, 10); }, 100);
</script></body></html>"""

# The live failure: the head is never pushed back, so snake[0] is undefined on
# the next tick and every frame after it throws.
BROKEN = """<!doctype html><html><head><title>t</title></head><body>
<canvas id="c" width="200" height="200"></canvas><p id="score">0</p>
<script>
const g = document.getElementById('c').getContext('2d');
let snake = [{x: 10}];
document.addEventListener('keydown', e => {});
setInterval(() => { const head = [...snake[0]]; snake.shift();
  g.fillRect(head[0], head[1], 10, 10); }, 100);
</script></body></html>"""

FROZEN = """<!doctype html><html><head><title>t</title></head><body>
<canvas id="c" width="200" height="200"></canvas>
<script>
const g = document.getElementById('c').getContext('2d');
document.addEventListener('keydown', e => {});
setInterval(() => { g.fillStyle = '#fff'; g.fillRect(10, 10, 20, 20); }, 100);
</script></body></html>"""

BLANK = """<!doctype html><html><head><title>t</title></head><body>
<canvas id="c" width="200" height="200"></canvas><p id="score">0</p>
<script>
document.addEventListener('keydown', e => {});
setInterval(() => { /* nothing is drawn */ }, 100);
</script></body></html>"""


@unittest.skipUnless(smoke.browser(), "no Edge or Chrome on this machine")
class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _page(self, text):
        path = os.path.join(self.tmp.name, "page.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return self.tmp.name, "page.html"

    def test_a_running_page_passes(self):
        workspace, path = self._page(GOOD)
        self.assertEqual(smoke.check(workspace, path), [])

    def test_a_crashing_page_is_caught_with_the_real_error(self):
        workspace, path = self._page(BROKEN)
        defects = smoke.check(workspace, path)
        self.assertTrue(defects, "a crashing page must not pass")
        self.assertIn("throws in the browser", defects[0])
        self.assertIn("TypeError", defects[0])

    def test_a_page_that_never_draws_is_caught(self):
        workspace, path = self._page(BLANK)
        defects = smoke.check(workspace, path)
        self.assertTrue(any("draws nothing" in d for d in defects), defects)

    def test_a_page_that_draws_the_same_thing_forever_is_caught(self):
        # Static checks see a canvas, a loop and a listener. The canvas is frozen.
        workspace, path = self._page(FROZEN)
        defects = smoke.check(workspace, path)
        self.assertTrue(any("frozen" in d for d in defects), defects)

    def test_the_probe_is_not_written_into_the_workspace(self):
        workspace, path = self._page(GOOD)
        smoke.check(workspace, path)
        with open(os.path.join(workspace, path), encoding="utf-8") as fh:
            self.assertNotIn("__probe", fh.read())


if __name__ == "__main__":
    unittest.main()
