"""Leakage, label-rule and duplicate-boundary tests using explicit fixtures."""

import copy
import unittest

from prepare_repair_cohorts import patch_targets, predictor_text, prepare, task_definitions


def records(count=20):
    result = []
    for index in range(count):
        added = f"return call_{index}(item)" if index % 2 else f"item_{index} = 'value'"
        result.append({"instance_id": f"repo-{index}", "repo": "owner/repo", "base_commit": "a" * 40,
            "version": "1", "created_at": f"2020-01-{index + 1:02}T00:00:00Z",
            "problem_statement": f"The reported symptom in event {index} is unexpected.",
            "patch": f"diff --git a/file.py b/file.py\n--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old_{index}()\n+{added}\n",
            "hints_text": "GOLD_SENTINEL", "FAIL_TO_PASS": "GOLD_SENTINEL"})
    return result


ACQUISITION = {"repository": "fixture", "revision": "a" * 40}


class RepairCohortTests(unittest.TestCase):
    def test_rule_direction_and_changed_lines_only(self):
        patch = "diff --git a/return.py b/return.py\n--- a/return.py\n+++ b/return.py\n@@ -1,2 +1,2 @@\n-return x\n+if good: call(x)\n import package\n"
        labels, measure, _ = patch_targets(patch, task_definitions())
        self.assertEqual(labels["removed_return"], 1)
        self.assertEqual(labels["added_return"], 0)
        self.assertEqual(labels["added_conditional"], 1)
        self.assertEqual(labels["either_import"], 0)
        self.assertEqual(measure["changed_lines"], 2)

    def test_no_patch_or_hints_enter_text_and_utf8_receipts(self):
        original = records()
        changed = copy.deepcopy(original)
        for row in changed:
            row["patch"] = row["patch"].replace("return", "yield")
        first, _, audit = prepare(original, ACQUISITION, min_per_class=2)
        second, _, _ = prepare(changed, ACQUISITION, min_per_class=2)
        self.assertEqual([r["text"] for r in first["rows"]], [r["text"] for r in second["rows"]])
        self.assertTrue(all("GOLD_SENTINEL" not in r["text"] for r in first["rows"]))
        text, receipt = predictor_text("owner/repo", "汉" * 300, 256)
        self.assertLessEqual(len(text.encode()), 256)
        self.assertTrue(receipt["truncated"])
        self.assertEqual(audit["retained_distinct_groups"], 20)

    def test_duplicate_group_crossing_boundary_is_fully_excluded(self):
        source = records()
        source[-1]["problem_statement"] = source[0]["problem_statement"].upper()
        data, _, audit = prepare(source, ACQUISITION, min_per_class=2)
        ids = {row["source_id"] for row in data["rows"]}
        self.assertNotIn("repo-0", ids)
        self.assertNotIn("repo-19", ids)
        self.assertEqual(len(audit["crossing_groups_excluded"]), 1)

    def test_selection_is_train_only_and_capacity_is_fixed(self):
        source = records()
        first, _, _ = prepare(source, ACQUISITION, min_per_class=2, max_tasks=3)
        for row in source[12:]:
            row["patch"] = row["patch"].replace("return", "yield")
        second, _, _ = prepare(source, ACQUISITION, min_per_class=2, max_tasks=3)
        self.assertEqual(first["selected_tasks"], second["selected_tasks"])
        self.assertEqual(len(first["selected_tasks"]), 3)
        self.assertTrue(any(t["status"] == "not_selected_by_fixed_capacity" for t in first["task_status"]))

    def test_within_split_duplicate_selects_earliest_before_support(self):
        source = records()
        source[1]["problem_statement"] = source[0]["problem_statement"]
        data, _, audit = prepare(source, ACQUISITION, min_per_class=2)
        self.assertEqual(audit["retained_split_counts"]["train"], 11)
        self.assertTrue(audit["duplicate_representatives"][0]["mixed_targets"])
        self.assertNotIn("repo-1", {r["source_id"] for r in data["rows"]})


if __name__ == "__main__":
    unittest.main()
