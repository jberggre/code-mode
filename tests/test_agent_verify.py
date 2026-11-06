"""A stub is sent back to the model, not reported as a finished game.

Recorded on this machine: the 3B wrote a 179-byte page with a dead <script src>
and `// Game logic goes here`, stopped, and said "the game is running
successfully". These tests pin the check that now runs before that answer is
allowed to stand, and the open-the-result step when it does pass.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import agent  # noqa: E402
import server as core  # noqa: E402

STUB = ("<html><head><title>Snake Game</title></head><body><h1>Snake Game</h1>"
        "<canvas id='snakeCanvas' width='400' height='400'></canvas>"
        "<script src='app/client.js'></script></body></html>")

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
function draw() {
  x.fillStyle = '#111'; x.fillRect(0,0,400,400);
  x.fillStyle = '#0f0'; snake.forEach(s => x.fillRect(s.x*10, s.y*10, 9, 9));
  document.getElementById('score').textContent = score;
}
setInterval(() => { draw(); }, 120);
</script></body></html>
"""


def _write(path, content):
    return "<tool>%s</tool>" % json.dumps(
        {"name": "write_file", "args": {"path": path, "content": content}})


class RepairLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.real_stream = core.stream_backend
        self.addCleanup(setattr, core, "stream_backend", self.real_stream)
        self.opened = []
        self.real_open = agent.toolbox.show_artifact

        def fake_open(workspace, path):
            self.opened.append(path)
            return "opened %s" % path

        agent.toolbox.show_artifact = fake_open
        self.addCleanup(setattr, agent.toolbox, "show_artifact", self.real_open)

    def _run(self, replies, user_text="make me a game of snake i can play"):
        state = {"n": 0}

        def fake(backend, model, messages, cfg):
            index = min(state["n"], len(replies) - 1)
            state["n"] += 1
            yield replies[index]

        core.stream_backend = fake
        return list(agent.stream_agent(
            {"kind": "ollama", "base": "http://127.0.0.1:1"}, "test-model",
            [{"role": "user", "content": user_text}],
            dict(core.MODES["code"]), self.workspace))

    def test_a_stub_goes_back_and_the_fix_is_opened(self):
        events = self._run([
            _write("snake.html", STUB),
            "The game is running successfully. Navigate to snake.html.",
            _write("snake.html", GOOD),
            "snake.html is ready.",
        ])
        logs = " ".join(e.get("log") or "" for e in events)
        self.assertIn("checked the result", logs)
        self.assertIn("sending it back", logs)
        # The stub must be replaced, and the repaired page opened for the user.
        with open(os.path.join(self.workspace, "snake.html"), encoding="utf-8") as fh:
            self.assertIn("addEventListener", fh.read())
        self.assertEqual(self.opened, ["snake.html"])

    def test_the_repair_message_names_the_real_defect(self):
        seen = []
        real = agent.toolbox.execute

        def spy(name, args, workspace, allow_shell=True, request=""):
            return real(name, args, workspace, allow_shell, request)

        state = {"n": 0}

        def fake(backend, model, messages, cfg):
            state["n"] += 1
            seen.append(messages)
            if state["n"] == 1:
                yield _write("snake.html", STUB)
            else:
                yield "Done."

        core.stream_backend = fake
        agent.toolbox.execute = spy
        self.addCleanup(setattr, agent.toolbox, "execute", real)
        list(agent.stream_agent(
            {"kind": "ollama", "base": "http://127.0.0.1:1"}, "test-model",
            [{"role": "user", "content": "make me a game of snake"}],
            dict(core.MODES["code"]), self.workspace))
        repair = [m["content"] for m in seen[-1] if m["role"] == "user"][-1]
        self.assertIn("problems", repair)
        self.assertIn("no such file exists", repair)

    def test_a_broken_result_is_never_opened(self):
        events = self._run([_write("snake.html", STUB), "It works, play it."])
        self.assertEqual(self.opened, [])
        self.assertTrue(any("still broken" in (e.get("log") or "") for e in events))

    def test_it_cannot_write_over_the_app_it_runs_in(self):
        os.makedirs(os.path.join(self.workspace, "app"))
        target = os.path.join(self.workspace, "app", "server.py")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("HTTP = True\n")
        events = self._run([_write("app/server.py", "print('snake')\n"), "Done."])
        with open(target, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "HTTP = True\n")
        self.assertTrue(any("refused" in (e.get("tool_result") or "") for e in events))

    def test_a_finished_page_stops_the_turn(self):
        # Observed live: after writing the page it kept going, `git worktree add`
        # five times in a row. A page that passes is the end of the turn.
        events = self._run([_write("snake.html", GOOD),
                            "and now I will keep working on it"])
        self.assertEqual(self.opened, ["snake.html"])
        self.assertEqual(len([e for e in events if "tool_start" in e]), 1)
        self.assertTrue(any("stopping here" in (e.get("log") or "") for e in events))


if __name__ == "__main__":
    unittest.main()
