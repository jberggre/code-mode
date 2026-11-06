"""The agent must act, not hand back a tutorial.

The reported failure: "I asked for a game of Snake and it told me how to make
one." That is a prompt problem plus a missing retry, so these tests pin both the
tool parsing and the nudge that sends an explaining reply back to work.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import agent  # noqa: E402
import server as core  # noqa: E402


def _cfg():
    cfg = dict(core.MODES["code"])
    cfg["system"] = core.MODES["code"]["system"]
    return cfg


class ToolParsingTests(unittest.TestCase):
    def test_classic_tool_block(self):
        call = agent._tool_json('<tool>{"name": "list_dir", "args": {}}</tool>')
        self.assertEqual(call["name"], "list_dir")

    def test_json_fence_is_accepted(self):
        # Small models often wrap the call in a fence even when told not to.
        call = agent._tool_json(
            'Writing it now.\n```json\n{"name": "write_file", '
            '"args": {"path": "a.py", "content": "x"}}\n```')
        self.assertEqual(call["name"], "write_file")
        self.assertEqual(call["args"]["path"], "a.py")

    def test_plain_prose_has_no_call(self):
        self.assertIsNone(agent._tool_json("Here is how you would make Snake."))


class NudgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = self.tmp.name
        self.real = core.stream_backend
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr, core, "stream_backend", self.real)

    def _run(self, replies, user_text):
        state = {"n": 0}

        def fake(backend, model, messages, cfg):
            index = min(state["n"], len(replies) - 1)
            state["n"] += 1
            yield replies[index]

        core.stream_backend = fake
        events = list(agent.stream_agent(
            {"kind": "ollama", "base": "http://127.0.0.1:1"}, "test-model",
            [{"role": "user", "content": user_text}], _cfg(), self.workspace))
        return events, state["n"]

    def test_explaining_reply_is_nudged_into_action(self):
        events, calls = self._run([
            "Here is how to make Snake:\n```python\nprint('snake')\n```",
            '<tool>{"name": "write_file", "args": {"path": "snake.py", "content": "print(1)"}}</tool>',
            "Wrote snake.py and it runs.",
        ], "make me a game of snake")
        self.assertTrue(os.path.exists(os.path.join(self.workspace, "snake.py")))
        self.assertGreaterEqual(calls, 3, "the model should be asked again after explaining")
        self.assertTrue(any("without acting" in (e.get("log") or "") for e in events))
        self.assertTrue(any("tool_start" in e for e in events))

    def test_a_short_dead_end_is_nudged_into_action(self):
        # Observed live: it answered "The game loop is not running." and stopped,
        # having written nothing, because a one-line reply was not "prose" and
        # the retry only fired for refusals and tutorials.
        events, calls = self._run([
            "The game loop is not running.",
            '<tool>{"name": "write_file", "args": {"path": "snake.html", "content": "<html></html>"}}</tool>',
            "Wrote snake.html.",
        ], "make me a game of snake i can play")
        self.assertGreaterEqual(calls, 3)
        self.assertTrue(any("answered without acting" in (e.get("log") or "") for e in events))

    def test_a_refusal_is_nudged_into_building(self):
        # The exact reply recorded from qwen2.5-coder:3b on this machine.
        events, calls = self._run([
            "I'm sorry, but I can't assist with that.",
            '<tool>{"name": "write_file", "args": {"path": "snake.html", "content": "<html></html>"}}</tool>',
            "Wrote snake.html.",
        ], "can u cde a gme of snake 4 me")
        self.assertTrue(os.path.exists(os.path.join(self.workspace, "snake.html")))
        self.assertGreaterEqual(calls, 3)
        self.assertTrue(any("refused instead of acting" in (e.get("log") or "") for e in events))

    def test_a_question_may_be_answered_without_tools(self):
        events, calls = self._run([
            "Because `parse()` returns None when the input is empty:\n```python\nreturn None\n```",
        ], "why does this error happen? explain it")
        self.assertEqual(calls, 1)
        self.assertFalse(any("without acting" in (e.get("log") or "") for e in events))


if __name__ == "__main__":
    unittest.main()
