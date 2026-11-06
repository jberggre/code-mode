"""Dictation plumbing without a microphone.

The real engine needs audio hardware, so these use a fake child process: what is
tested is that phrases reach the composer as they arrive, that stopping is clean,
and that an engine failure is reported instead of swallowed.
"""

import io
import os
import sys
import unittest

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
