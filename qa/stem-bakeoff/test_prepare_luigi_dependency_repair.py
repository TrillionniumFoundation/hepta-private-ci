import copy
import unittest

from prepare_luigi_dependency_repair import exact_repair_lock, project_inputs


def fixture():
    groups, registry, rows = {}, [], []
    for i in range(33):
        group = f"bugsinpy/luigi/{i+1}"
        actions = [{"key": f"key-{i}-{j}", "source_id": f"source-{i}-{j}",
                    "runner": "pytest", "args": [f"test_a.py::test_{j}"]} for j in range(6 if i == 0 else 4)]
        groups[group] = {"project": "luigi", "role": "tuning", "actions": actions,
                         "source_revisions": {"base": "original-a", "candidate": "original-b"}}
        registry.append({"group_id": group, "repo": "luigi", "actions": actions})
        rows.extend({"source_id": a["source_id"], "group_id": group,
                     "text": "exact supplied source " + a["key"], "labels": {"action_usefulness": None}} for a in actions)
    groups["other/1"] = {"project": "other", "actions": []}
    return {"case_bindings": groups, "rows": rows, "proposal_registry": registry,
            "project_roles": {"luigi": "tuning", "other": "holdout"}, "all_labels_unobserved": True}


class LuigiRepairTests(unittest.TestCase):
    def test_exact_lock_preserves_every_old_version_and_only_two_additions(self):
        before = "pip==23.0.1\nsetuptools==44.1.1\nwheel==0.37.1\nSome_Name==1.0\n"
        after = before+"pyparsing==2.4.7\nSQLAlchemy==1.3.17\n"
        self.assertEqual(exact_repair_lock(before, after), {"pip": "23.0.1", "setuptools": "44.1.1",
            "wheel": "0.37.1", "some-name": "1.0", "pyparsing": "2.4.7", "sqlalchemy": "1.3.17"})
        for changed in (after.replace("Some_Name==1.0", "Some_Name==1.1"), after+"unapproved==1\n", before):
            with self.assertRaises(ValueError): exact_repair_lock(before, changed)

    def test_projection_preserves_full_project_actions_order_sources_and_revisions(self):
        original = fixture()
        before = copy.deepcopy(original)
        groups = [g for g in original["case_bindings"] if g.startswith("bugsinpy/luigi/")]
        result = project_inputs(original, groups)
        self.assertEqual(original, before)
        self.assertEqual(result["rows"], before["rows"])
        self.assertEqual(result["proposal_registry"], before["proposal_registry"])
        self.assertEqual(result["case_bindings"], {g: before["case_bindings"][g] for g in groups})
        self.assertEqual(sum(len(g["actions"]) for g in result["case_bindings"].values()), 134)

    def test_dropped_groups_or_action_registry_mutation_or_observed_label_rejected(self):
        original = fixture()
        groups = [g for g in original["case_bindings"] if g.startswith("bugsinpy/luigi/")]
        with self.assertRaises(ValueError): project_inputs(original, groups[:-1])
        for field in ("registry", "label"):
            broken = copy.deepcopy(original)
            if field == "registry":
                broken["proposal_registry"][0]["actions"] = []
            else:
                broken["rows"][0]["labels"]["action_usefulness"] = 0
            with self.assertRaises(ValueError): project_inputs(broken, groups)


if __name__ == "__main__":
    unittest.main()
