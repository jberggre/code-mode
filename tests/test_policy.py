"""The rules that stop the agent from wrecking the thing it runs inside.

The recorded failure: asked for a game of Snake, qwen2.5-coder:3b read
app/server.py for reference and wrote its game loop over it - the app's own
HTTP layer replaced by 15 lines - then reported success. The request never named
that file, so `policy` now refuses it, and any overwrite that is allowed keeps
the old bytes.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import policy  # noqa: E402
import tools  # noqa: E402


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = self.tmp.name
        os.makedirs(os.path.join(self.workspace, "app"), exist_ok=True)
        self.core = os.path.join(self.workspace, "app", "server.py")
        with open(self.core, "w", encoding="utf-8") as fh:
            fh.write("HTTP = True\n")

    def test_game_request_cannot_overwrite_app_source(self):
        allowed, why = policy.check_write(self.workspace, "app/server.py",
                                          "can u cde a gme of snake 4 me")
        self.assertFalse(allowed)
        self.assertIn("belongs to CodeMode", why)
        # The refusal has to point somewhere useful, not just say no.
        self.assertIn("workspace root", why)

    def test_a_fixing_request_that_names_the_file_is_allowed(self):
        allowed, why = policy.check_write(self.workspace, "app/server.py",
                                          "the port is wrong in app/server.py")
        self.assertTrue(allowed, why)

    def test_bare_file_name_counts_but_a_similar_name_does_not(self):
        self.assertTrue(policy.check_write(
            self.workspace, "app/server.py", "server.py keeps dying")[0])
        self.assertFalse(policy.check_write(
            self.workspace, "app/server.py", "my-server.py is broken")[0])

    def test_new_files_at_the_root_are_always_fine(self):
        allowed, why = policy.check_write(self.workspace, "snake.html", "make me snake")
        self.assertTrue(allowed, why)

    def test_sealed_directories_are_refused_even_when_named(self):
        for path in (".git/config", ".codemode/undo/x.bak"):
            allowed, _ = policy.check_write(self.workspace, path, "edit %s" % path)
            self.assertFalse(allowed, path)

    def test_escaping_the_workspace_is_refused(self):
        for path in ("../outside.txt", "C:/Windows/System32/x.txt"):
            allowed, why = policy.check_write(self.workspace, path, "write it")
            self.assertFalse(allowed, path)
            self.assertIn("outside the workspace", why)


class ReversibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = self.tmp.name

    def test_overwriting_keeps_the_previous_bytes(self):
        with open(os.path.join(self.workspace, "notes.md"), "w", encoding="utf-8") as fh:
            fh.write("original\n")
        result = tools.write_file(self.workspace, "notes.md", "replacement\n")
        self.assertTrue(result.startswith("wrote 12 bytes"), result)
        self.assertIn(".codemode/undo/", result)
        kept = result.split("old copy is at ")[1].split(")")[0]
        with open(os.path.join(self.workspace, kept), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "original\n")

    def test_a_refused_write_leaves_the_file_alone(self):
        os.makedirs(os.path.join(self.workspace, "app"))
        target = os.path.join(self.workspace, "app", "ui.py")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("IMPORTANT = 1\n")
        result = tools.write_file(self.workspace, "app/ui.py", "print('game')\n")
        self.assertTrue(result.startswith("refused"), result)
        with open(target, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "IMPORTANT = 1\n")


class CommandTests(unittest.TestCase):
    def test_destructive_commands_are_refused_with_a_reason(self):
        cases = {
            "git reset --hard HEAD": "git history",
            "Remove-Item .\\app -Recurse -Force": "recursive",
            "powercfg /setactive SCHEME_MIN": "power plan",
            "shutdown /s /t 0": "shutting down",
            "Stop-Service ArmouryCrateService": "protected service",
            "Set-ExecutionPolicy Unrestricted": "execution policy",
            "git worktree add ../copy": "second checkout",
        }
        for command, reason in cases.items():
            refusal = policy.check_command(command, "C:/work")
            self.assertTrue(refusal.startswith("refused"), command)
            self.assertIn(reason, refusal, command)

    def test_ordinary_commands_are_allowed(self):
        for command in ("python -m unittest discover -s tests",
                        "Start-Process .\\snake.html",
                        "Get-ChildItem .",
                        "node --version"):
            self.assertEqual(policy.check_command(command, "C:/work"), "", command)

    def test_a_command_reaching_outside_the_workspace_is_refused(self):
        refusal = policy.check_command("Set-Content C:\\Windows\\System32\\drivers\\etc\\hosts x",
                                       "C:/work")
        self.assertTrue(refusal.startswith("refused"), refusal)


if __name__ == "__main__":
    unittest.main()
