import unittest

from operational_reconciled_dataset import selected_conditions


class ReconciledDatasetTests(unittest.TestCase):
    def test_whole_repository_condition_never_falls_back_to_original_success(self):
        bugs = [{"group_id": "a", "project": "affected"}, {"group_id": "b", "project": "affected"},
                {"group_id": "c", "project": "unaffected"}]
        plan = {"affected_projects": ["affected"], "groups": ["a", "b"], "eligibility_gate_changed": False}
        original = {"a": "original-success", "b": "original-failure", "c": "original-success"}
        compatibility = {"a": "new-failure", "b": "new-success"}
        self.assertEqual(selected_conditions(bugs, plan, original, compatibility),
                         {"a": "compatibility", "b": "compatibility", "c": "original"})
        del compatibility["a"]
        with self.assertRaisesRegex(ValueError, "whole affected"):
            selected_conditions(bugs, plan, original, compatibility)

    def test_changed_eligibility_gate_cannot_be_reconciled(self):
        bugs = [{"group_id": "a", "project": "affected"}]
        plan = {"affected_projects": ["affected"], "groups": ["a"], "eligibility_gate_changed": True}
        with self.assertRaises(ValueError):
            selected_conditions(bugs, plan, {"a": "before"}, {"a": "after"})


if __name__ == "__main__":
    unittest.main()
