import copy
import unittest

from operational_dataset import availability, pair_key, rows_for_case, validate_splits


def fixture():
    control = {"id": "c", "runner": "unittest", "args": ["a.T.test_c"],
               "view": {"text": "def test_c(): assert 1 == 1", "source_files": {}}}
    primary = {"id": "p", "runner": "unittest", "args": ["a.T.test_p"],
               "view": {"text": "def test_p(): assert f() == 2", "source_files": {}}, "comparators": [control]}
    case = {"bug": {"group_id": "g", "project": "repo", "split": "train",
                    "revisions": {"base": "b" * 40, "candidate": "c" * 40}},
        "implementation": {"production_paths": ["m.py"], "contexts": {"base": "def f(): return 1", "candidate": "def f(): return 2"},
            "diff": "-return 1\n+return 2", "source_files": {"base": {}, "candidate": {}}}, "commands": [primary]}
    result = {"harness_error": None, "selected_primary": "p", "selected_control": "c", "case_sha256": "case",
        "fixed_test_tree_sha256": "tree", "execution_plan_sha256": "plan", "pairs": {
            pair_key(primary): {"base": {"outcome": "test_failure"}, "candidate": {"outcome": "pass"}},
            pair_key(control): {"base": {"outcome": "pass"}, "candidate": {"outcome": "pass"}}}}
    return case, result


class OperationalDatasetTests(unittest.TestCase):
    def test_labels_use_actual_observations_and_keep_revision_identity_out_of_text(self):
        case, result = fixture()
        rows, unavailable = rows_for_case(case, result, 100000)
        self.assertEqual((len(rows), unavailable), (3, {}))
        self.assertEqual([r["labels"] for r in rows[:2]], [{"regression_outcome": 0}, {"regression_outcome": 1}])
        self.assertTrue(all(len(r["labels"]) == 1 and r["group_id"] == "g" for r in rows))
        self.assertTrue(all("b" * 40 not in r["text"] and "c" * 40 not in r["text"] for r in rows))
        self.assertFalse(availability(rows)["regression_outcome"]["budgets"]["8"]["available"])
        result["pairs"][pair_key(case["commands"][0])]["candidate"]["outcome"] = "test_failure"
        with self.assertRaisesRegex(ValueError, "lacks observed"):
            rows_for_case(case, result, 100000)

    def test_unknown_and_uninformative_actions_are_not_zero_labels(self):
        case, result = fixture()
        result["selected_control"] = None
        rows, unavailable = rows_for_case(case, result, 100000)
        self.assertEqual(len(rows), 2)
        self.assertIn("diagnostic_test_selection", unavailable)
        self.assertTrue(all("diagnostic_test_selection" not in r["labels"] for r in rows))
        result["selected_primary"] = None
        self.assertEqual(rows_for_case(case, result, 100000)[0], [])

    def test_group_repository_and_exact_code_clone_splits_fail_closed(self):
        case, result = fixture()
        rows, _ = rows_for_case(case, result, 100000)
        other = copy.deepcopy(rows[0])
        other.update(source_id="another", split="holdout")
        with self.assertRaises(ValueError):
            validate_splits(rows + [other], [case])
        source = {"m.py": {"sha256": "same-code", "bytes": 20}}
        case["implementation"]["source_files"]["base"] = source
        copied = copy.deepcopy(case)
        copied["bug"].update(project="other", group_id="other-group", split="holdout")
        with self.assertRaisesRegex(ValueError, "code clone"):
            validate_splits(rows, [case, copied])


if __name__ == "__main__":
    unittest.main()
