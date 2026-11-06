"""Dictation plumbing without a microphone.

The real engine needs audio hardware, so these use a fake child process: what is
tested is that phrases reach the composer as they arrive, that stopping is clean,
and that an engine failure is reported instead of swallowed.
"""

import io
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import speech  # noqa: E402


class FakeProc:
    def __init__(self, lines, stderr="", code=0):
        self.stdout = io.StringIO("".join(line + "\n" for line in lines))
        self.stderr = io.StringIO(stderr)
        self.code = code
        self.terminated = False

    def wait(self):
        return self.code

    def terminate(self):
        self.terminated = True


class ProbeTests(unittest.TestCase):
    """A failed probe once read as "Windows has no speech" and hid a working mic."""

    def setUp(self):
        speech._CACHE.update(languages=None, answered=False)

    def test_query_loads_the_assembly_that_defines_the_type(self):
        # Without Add-Type the type does not exist, so stdout is empty and the
        # application wrongly concludes that speech is not installed.
        self.assertIn("Add-Type -AssemblyName System.Speech", speech.QUERY)
        self.assertIn("InstalledRecognizers", speech.QUERY)

    def _run(self, stdout):
        done = subprocess.CompletedProcess(["powershell"], 0, stdout, "")
        with mock.patch.object(speech.subprocess, "run", return_value=done):
            return speech.installed_languages(refresh=True)

    def test_languages_are_parsed(self):
        self.assertEqual(self._run("LANG:en-US\r\nLANG:fr-FR\r\nEND\r\n"),
                         ["en-US", "fr-FR"])

    def test_a_real_answer_of_none_is_an_empty_list(self):
        self.assertEqual(self._run("END\r\n"), [])

    def test_an_unanswered_probe_is_not_an_empty_list(self):
        self.assertIsNone(self._run("ERR:assembly\r\n"))
        self.assertIsNone(self._run(""))

    def test_a_broken_probe_is_not_an_empty_list(self):
        with mock.patch.object(speech.subprocess, "run",
                               side_effect=OSError("no powershell")):
            self.assertIsNone(speech.installed_languages(refresh=True))


class DictationTests(unittest.TestCase):
    def test_phrases_arrive_and_stop_is_clean(self):
        heard, errors = [], []
        proc = FakeProc(["add a null check", "before the parse"])
        talker = speech.Dictation(heard.append, errors.append, popen=lambda: proc)
        self.assertTrue(talker.start())
        talker._reader.join(2)
        talker.stop()
        self.assertEqual(heard, ["add a null check", "before the parse"])
        self.assertEqual(errors, [])

    def test_ready_marker_is_not_speech(self):
        heard = []
        proc = FakeProc(["READY", "add a null check"])
        talker = speech.Dictation(heard.append, lambda _e: None, popen=lambda: proc)
        talker.start()
        talker._reader.join(2)
        self.assertEqual(heard, ["add a null check"])

    def test_engine_failure_is_reported(self):
        heard, errors = [], []
        proc = FakeProc([], stderr="mic/speech error: no audio device", code=1)
        talker = speech.Dictation(heard.append, errors.append, popen=lambda: proc)
        talker.start()
        talker._reader.join(2)
        self.assertEqual(heard, [])
        self.assertTrue(errors and "no audio device" in errors[-1])

    def test_start_reports_a_missing_powershell(self):
        errors = []

        def broken():
            raise OSError("powershell not found")

        talker = speech.Dictation(lambda _t: None, errors.append, popen=broken)
        self.assertFalse(talker.start())
        self.assertTrue(errors and "powershell" in errors[0])


if __name__ == "__main__":
    unittest.main()
