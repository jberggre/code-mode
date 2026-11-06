import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from server import pick_model  # noqa: E402


class PickModelTests(unittest.TestCase):
    def setUp(self):
        self.ollama = {"kind": "ollama", "label": "Ollama",
                       "models": ["llama3:8b", "qwen2.5-coder:3b"]}
        self.lmstudio = {"kind": "lmstudio", "label": "LM Studio",
                         "models": ["deepseek-coder:6.7b"]}

    def test_exact_preference_wins(self):
        backend, name = pick_model([self.ollama, self.lmstudio], "llama3:8b")
        self.assertEqual((backend["kind"], name), ("ollama", "llama3:8b"))

    def test_falls_back_to_a_coder_model(self):
        backend, name = pick_model([self.ollama, self.lmstudio], "")
        self.assertEqual(name, "qwen2.5-coder:3b")
        self.assertEqual(backend["kind"], "ollama")

    def test_unknown_preference_does_not_block_selection(self):
        _, name = pick_model([self.ollama], "not-installed:1b")
        self.assertEqual(name, "qwen2.5-coder:3b")

    def test_no_models_anywhere(self):
        self.assertEqual(pick_model([], ""), (None, ""))
        self.assertEqual(pick_model([{"kind": "ollama", "models": []}], "x"), (None, ""))

    def test_first_model_when_nothing_matches_coder(self):
        backend = {"kind": "lmstudio", "models": ["mistral:7b"]}
        self.assertEqual(pick_model([backend], ""), (backend, "mistral:7b"))


if __name__ == "__main__":
    unittest.main()
