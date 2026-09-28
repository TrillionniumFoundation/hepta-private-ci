import unittest

from run_mutations import mutate_once, observed_kill


class MutationRunnerTests(unittest.TestCase):
    def test_anchor_is_exact_and_unambiguous(self):
        recipe = {"name": "fixture", "old": "CHECK", "new": "MUTANT"}
        self.assertEqual(mutate_once("before CHECK after", recipe), "before MUTANT after")
        for source in ["missing", "CHECK CHECK"]:
            with self.assertRaises(ValueError):
                mutate_once(source, recipe)

    def test_only_observed_wrong_semantics_count_as_killed(self):
        killed = {"exit_code": 0, "report": {"outcome": "accepted"}, "passed": False, "status": "failed"}
        self.assertTrue(observed_kill(killed))
        for invalid in [{}, dict(killed, exit_code=101), dict(killed, status="infrastructure_invalid"),
                        dict(killed, report={"outcome": "rejected"}), dict(killed, passed=True)]:
            self.assertFalse(observed_kill(invalid))


if __name__ == "__main__":
    unittest.main()
