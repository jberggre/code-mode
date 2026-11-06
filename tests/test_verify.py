"""The check that runs before the agent is allowed to say "it works".

Every stub below is a real shape from this machine's model output: a 179-byte
page whose <script src> pointed at a path that does not exist, a JS file whose
only comment was "// Game logic goes here", and a claim of success over both.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import verify  # noqa: E402

GOOD = """<!doctype html><html><head><title>Snake</title><style>
body{margin:0;background:#111;color:#fff}#score{font:16px monospace}
</style></head><body><p id="score">0</p><canvas id="c" width="400" height="400"></canvas>
<script>
const c = document.getElementById('c'), x = c.getContext('2d');
let snake = [{x:10,y:10}], dir = {x:1,y:0}, food = {x:15,y:15}, score = 0;
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowUp') dir = {x:0,y:-1};
  if (e.key === 'ArrowDown') dir = {x:0,y:1};
  if (e.key === 'ArrowLeft') dir = {x:-1,y:0};
  if (e.key === 'ArrowRight') dir = {x:1,y:0};
});
function step() {
  const head = {x: snake[0].x + dir.x, y: snake[0].y + dir.y};
  snake.unshift(head);
  if (head.x === food.x && head.y === food.y) { score++; document.getElementById('score').textContent = score; }
  else { snake.pop(); }
}
function draw() { x.fillStyle = '#111'; x.fillRect(0,0,400,400); }
setInterval(() => { step(); draw(); }, 120);
</script></body></html>
"""


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = self.tmp.name

    def _write(self, path, text):
        full = os.path.join(self.workspace, path)
        os.makedirs(os.path.dirname(full) or self.workspace, exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_a_finished_game_passes(self):
        self.assertEqual(verify.check_file(self.workspace, self._write("snake.html", GOOD)), [])
        self.assertTrue(verify.playable(self.workspace, "snake.html"))

    def test_the_recorded_stub_is_caught(self):
        # 179 bytes, a dead relative path, and a placeholder in the script.
        stub = ("<html><head><title>Snake Game</title></head><body><h1>Snake Game</h1>"
                "<canvas id='snakeCanvas' width='400' height='400'></canvas>"
                "<script src='app/client.js'></script></body></html>")
        self._write("app/client.html", stub)
        defects = verify.check_file(self.workspace, "app/client.html")
        joined = " ".join(defects)
        self.assertIn("stub, not a finished page", joined)
        self.assertIn("no such file exists", joined)

    def test_placeholder_code_is_caught(self):
        page = GOOD.replace("function draw() { x.fillStyle = '#111'; x.fillRect(0,0,400,400); }",
                            "// Game logic goes here")
        defects = verify.check_html(self.workspace, "a.html", page)
        self.assertTrue(any("placeholder" in d for d in defects), defects)

    def test_a_canvas_nobody_listens_to_is_caught(self):
        page = GOOD.replace("document.addEventListener('keydown'", "function unused(e)")
        defects = verify.check_html(self.workspace, "b.html", page)
        self.assertTrue(any("cannot control" in d for d in defects), defects)

    def test_a_canvas_that_never_moves_is_caught(self):
        page = GOOD.replace("setInterval(() => { step(); draw(); }, 120);", "")
        defects = verify.check_html(self.workspace, "c.html", page)
        self.assertTrue(any("nothing moves" in d for d in defects), defects)

    def test_broken_python_is_caught_with_a_line_number(self):
        self._write("bad.py", "def go(:\n    pass\n")
        defects = verify.check_file(self.workspace, "bad.py")
        self.assertIn("does not parse", defects[0])
        self.assertIn("line 1", defects[0])

    def test_a_missing_file_is_reported_not_ignored(self):
        self.assertEqual(verify.check_turn(self.workspace, ["ghost.html"]),
                         ["ghost.html was never written: the path does not exist."])

    def test_the_717_byte_placeholder_page_is_caught(self):
        # Written by qwen2.5-coder:3b for "make me a game of snake i can play":
        # four functions, every body a comment, no canvas at all. It passed the
        # first version of this checker, which is why the checker got stricter.
        page = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Snake Game</title>
<style>body { display: flex; height: 100vh; margin: 0; background-color: #000; }</style>
</head><body>
<script>
function initSnake() {
  // Initialize snake logic here
}

function updateSnake() {
  // Update snake position here
}

function drawSnake() {
  // Draw snake on canvas here
}

function gameLoop() {
  updateSnake();
drawSnake();
requestAnimationFrame(gameLoop);
}

initSnake();
gameLoop();
</script></body></html>
"""
        self.assertGreater(len(page), 300)
        defects = verify.check_html(self.workspace, "snake.html", page)
        joined = " ".join(defects)
        self.assertIn("placeholder", joined)
        self.assertIn("empty body", joined)
        self.assertIn("screen stays blank", joined)
        self.assertIn("cannot steer", joined)
        self.assertFalse(verify.playable(self.workspace, "snake.html"))

    def test_a_canvas_that_is_never_drawn_to_is_caught(self):
        page = GOOD.replace("const c = document.getElementById('c'), x = c.getContext('2d');",
                            "const c = document.getElementById('c');")
        page = page.replace("x.fillStyle = '#111'; x.fillRect(0,0,400,400);", "")
        page = page.replace("function draw() {  }", "function draw() { }")
        defects = verify.check_script("d.html", page)
        self.assertTrue(any("empty body" in d for d in defects), defects)

    def test_a_loop_that_steps_every_frame_is_caught(self):
        # The 1689-byte page from the live run: correct logic, requestAnimationFrame
        # with no throttle - sixty squares a second is over before you can steer.
        page = GOOD.replace(
            "setInterval(() => { step(); draw(); }, 120);",
            "requestAnimationFrame(function loop() { step(); draw(); requestAnimationFrame(loop); });")
        defects = verify.check_script("f.html", page)
        self.assertTrue(any("sixty squares" in d for d in defects), defects)

    def test_a_score_nobody_can_see_is_caught(self):
        page = GOOD.replace("document.getElementById('score').textContent = score;", "")
        defects = verify.check_script("g.html", page)
        self.assertTrue(any("never shows it" in d for d in defects), defects)

    def test_a_lookup_for_an_element_that_is_not_there_is_caught(self):
        page = GOOD.replace('id="score"', 'id="points"')
        defects = verify.check_html(self.workspace, "e.html", page)
        self.assertTrue(any("#score" in d and "not in the page" in d for d in defects),
                        defects)

    def test_a_cut_off_page_is_caught(self):
        page = GOOD.replace("</script></body></html>", "")
        defects = verify.check_html(self.workspace, "h.html", page)
        self.assertTrue(any("never closes it" in d for d in defects), defects)

    def test_unbalanced_brackets_are_caught(self):
        # What a model that ran out of reply tokens leaves behind.
        page = GOOD.replace("setInterval(() => { step(); draw(); }, 120);",
                            "setInterval(() => { step(); draw();")
        defects = verify.check_html(self.workspace, "i.html", page)
        self.assertTrue(any("unclosed bracket" in d for d in defects), defects)


if __name__ == "__main__":
    unittest.main()
