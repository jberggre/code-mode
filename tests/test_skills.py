"""Skills are opt-in: on a 3B the old mandate cost a whole round trip per task."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import skills  # noqa: E402


class PreambleTests(unittest.TestCase):
    def test_it_does_not_demand_an_announcement(self):
        # Before: "Announce which skill you are using" plus "load it if there is
        # even a small chance". The model replied "Using writing-plans to plan
        # the game of Snake." and wrote nothing for 40-90 seconds.
        text = skills.preamble()
        self.assertNotIn("Announce", text)
        self.assertNotIn("even a small\\n   chance", text)
        self.assertIn("read_skill", text)

    def test_the_check_first_rule_survives(self):
        text = skills.preamble()
        self.assertIn("never claim something works", text)
        self.assertIn("report a failure as a failure", text)


if __name__ == "__main__":
    unittest.main()
