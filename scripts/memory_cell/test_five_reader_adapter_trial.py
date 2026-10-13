"""Replay planning tests, all inputs are fixtures and no model is called."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import five_causal_experiments as c
from five_reader_adapter_trial import selected_inputs, relative_directory, CONDITIONS


class ReplayPlanTests(unittest.TestCase):
    def rows(self):
        return [{"question_id": q, "condition": condition, "request": {"fixture": True}}
                for q in ("a", "b") for condition in CONDITIONS]

    def test_selection_is_identity_based_and_keeps_unavailable(self):
        rows = self.rows(); first = min(("a", "b"), key=c.digest)
        for row in rows:
            if row["question_id"] == first: row["request"] = None
        selected = selected_inputs(rows)
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(r["question_id"] == first and r["request"] is None for r in selected))

    def test_order_and_input_are_preserved_without_target_access(self):
        rows = self.rows(); before = deepcopy(rows)
        chosen = selected_inputs(list(reversed(rows)))
        self.assertEqual([r["condition"] for r in chosen], list(CONDITIONS))
        self.assertEqual(rows, before)
        self.assertTrue(all("answer" not in row for row in chosen))

    def test_incomplete_or_duplicate_selected_conditions_are_rejected(self):
        first = min(("a", "b"), key=c.digest)
        rows = [r for r in self.rows() if r["question_id"] == first]
        for invalid in ([], rows[:1], rows + rows[:1]):
            with self.assertRaises(c.Invalid): selected_inputs(invalid)

    def test_relative_material_path_stays_below_declared_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/"material").mkdir()
            self.assertEqual(relative_directory(root, "material"), root/"material")
            for invalid in ("../material", "/tmp", "", "missing"):
                with self.assertRaises(c.Invalid): relative_directory(root, invalid)

    def test_symlink_directory_is_not_an_ordinary_material_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/"material").mkdir()
            (root/"linked").symlink_to(root/"material")
            with self.assertRaises(c.Invalid): relative_directory(root, "linked")


if __name__ == "__main__":
    unittest.main()
