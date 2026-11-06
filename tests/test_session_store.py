import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import session_store  # noqa: E402


class SessionStoreTests(unittest.TestCase):
    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = session_store.load_session(os.path.join(tmp, "nope.json"))
        self.assertEqual(data, {"mode": "code", "model": "", "messages": []})

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "chat-session.json")
            payload = {
                "mode": "chat",
                "model": "qwen2.5-coder:3b",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ],
            }
            self.assertTrue(session_store.save_session(payload, path))
            self.assertEqual(session_store.load_session(path), payload)

    def test_corrupt_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "chat-session.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            self.assertEqual(session_store.load_session(path)["messages"], [])

    def test_unknown_roles_and_empty_content_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "chat-session.json")
            self.assertTrue(session_store.save_session(
                {"mode": "code", "model": "",
                 "messages": [
                     {"role": "system", "content": "prompt"},
                     {"role": "user", "content": "   "},
                     {"role": "user", "content": 42},
                     {"role": "user", "content": "keep me"},
                 ]}, path))
            messages = session_store.load_session(path)["messages"]
        self.assertEqual(messages, [{"role": "user", "content": "keep me"}])

    def test_save_creates_missing_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deep", "chat-session.json")
            self.assertTrue(session_store.save_session(
                {"mode": "code", "model": "", "messages": []}, path))
            self.assertTrue(os.path.isfile(path))

    def test_bad_mode_falls_back_to_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "chat-session.json")
            self.assertTrue(session_store.save_session(
                {"mode": "nonsense", "model": "m", "messages": []}, path))
            self.assertEqual(session_store.load_session(path)["mode"], "code")


if __name__ == "__main__":
    unittest.main()
