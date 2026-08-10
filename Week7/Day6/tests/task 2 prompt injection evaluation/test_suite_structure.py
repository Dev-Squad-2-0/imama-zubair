import unittest

from prompt_injection_suite import SCENARIOS, REQUIRED_GROUPS


class PromptInjectionSuiteStructureTests(unittest.TestCase):
    def test_has_exactly_six_attacks(self):
        self.assertEqual(len(SCENARIOS), 6)

    def test_ids_are_unique(self):
        ids = [s.id for s in SCENARIOS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_required_groups_are_covered(self):
        groups = {s.group for s in SCENARIOS}
        self.assertEqual(groups, REQUIRED_GROUPS)

    def test_required_assignment_examples_are_present(self):
        text = "\n".join(
            "\n".join(s.turns).lower()
            for s in SCENARIOS
        )
        self.assertIn("ignore", text)
        self.assertIn("system prompt", text)
        self.assertIn("fake appointments", text)
        self.assertIn("internal company data", text)

    def test_every_scenario_has_turns(self):
        for scenario in SCENARIOS:
            self.assertTrue(scenario.turns, scenario.id)


if __name__ == "__main__":
    unittest.main()
