"""Metadata fixtures exercise whole-project selection without benchmark commands."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from operational_cohort_plan import canonical, digest
from prospective_action_inputs import TASK, sha_file
from prospective_action_run import CODE_FILES
from prospective_outcome_selection import derived_config, freeze_selection, load_selection


def write(path, value):
    Path(path).write_bytes(canonical(value)+b"\n")
    return sha_file(path)


def condition(root, inputs, plan, labels):
    root.mkdir()
    plan_sha = write(root/"execution-plan.json", plan)
    cases = {}
    for group, binding in inputs["case_bindings"].items():
        location = root/(binding["project"]+"-"+str(binding["bug_id"]))
        location.mkdir()
        (location/"stdout.log").write_bytes(b"")
        key = binding["actions"][0]["key"]
        base = "infrastructure_error" if labels[group] is None else "test_failure" if labels[group] else "pass"
        result = {"case_sha256": binding["sha256"], "execution_plan_sha256": plan_sha,
            "group_id": group, "project": binding["project"], "bug_id": binding["bug_id"], "split": binding["role"],
            "proposed_action_keys": [key], "pairs": {key: {"base": {"outcome": base, "wall_ns": 5},
                "candidate": {"outcome": "pass", "wall_ns": 7}}}, "action_launch_counts": {key: 2},
            "physical_command_executions": 2, "complete_command_observations": 2, "observer_call_attempts": 2,
            "observer_attempts_without_launch_receipt": 0, "errors": [],
            "files": {"stdout.log": {"sha256": digest(b""), "bytes": 0}}}
        cases[group] = write(location/"result.json", result)
    summary = {"execution_plan_sha256": plan_sha, "case_results": cases, "proposed_groups": len(cases),
        "completed_groups": len(cases), "proposed_physical_command_slots": 2*len(cases),
        "physical_command_executions": 2*len(cases), "complete_command_observations": 2*len(cases),
        "observer_call_attempts": 2*len(cases), "observer_attempts_without_launch_receipt": 0,
        "all_frozen_files_unchanged": True, "all_runtime_files_unchanged": True,
        "outcome_dependent_stopping": False, "no_model_fit_or_score": True,
        "wall_ns": 100, "parent_process_cpu_ns": 50, "all_reaped_children_cpu_ns": 100}
    return plan_sha, write(root/"summary.json", summary)


def fixture(root):
    cases, rows, registry = {}, [], []
    for project, bug, role in (("luigi", 1, "tuning"), ("luigi", 2, "tuning"), ("scrapy", 1, "train")):
        group, source = f"bugsinpy/{project}/{bug}", f"source-{project}-{bug}"
        case_path = root/(project+str(bug)+".json")
        case_sha = write(case_path, {"source": group, "revisions": {"base": "a"*40, "candidate": "b"*40}})
        action = {"key": source+"-command", "source_id": source, "runner": "pytest", "args": ["test.py::test_one"]}
        cases[group] = {"path": str(case_path), "sha256": case_sha, "project": project, "bug_id": bug,
                       "role": role, "source_revisions": {"base": "a"*40, "candidate": "b"*40}, "actions": [action]}
        rows.append({"source_id": source, "group_id": group, "repo": project, "split": role,
                     "text": "source-only "+source, "source_version": {"case": case_sha}, "labels": {TASK: None}})
        registry.append({"group_id": group, "repo": project, "split": role, "actions": [action]})
    original = {"case_bindings": cases, "rows": rows, "proposal_registry": registry, "selected_tasks": [TASK],
        "all_labels_unobserved": True, "project_roles": {"luigi": "tuning", "scrapy": "train"}, "governing_protocol_sha256": "d"*64}
    projected = {**copy.deepcopy(original), "case_bindings": {k: v for k, v in cases.items() if v["project"] == "luigi"},
        "rows": rows[:2], "proposal_registry": registry[:2], "project_roles": {"luigi": "tuning"}}
    inputs, projection = root/"inputs", root/"projected"
    inputs.mkdir(); projection.mkdir()
    input_sha, projected_sha = write(inputs/"inputs.json", original), write(projection/"inputs.json", projected)
    write(inputs/"manifest.json", {"inputs_sha256": input_sha})
    write(projection/"manifest.json", {"inputs_sha256": projected_sha})
    base, environment = root/"base-runtime", root/"new-environment"
    base.mkdir(); environment.mkdir()
    (base/"python").write_bytes(b"ordinary synthetic executable bytes")
    (environment/"python").symlink_to(base/"python")
    inventories = {}
    for name, directory in (("base", base), ("environment", environment)):
        inventory = root/(name+"-files.json")
        pin = write(inventory, [{"path": "python", "sha256": sha_file(directory/"python"), "bytes": (directory/"python").stat().st_size}])
        inventories[name] = {"root": str(directory), "manifest": str(inventory), "sha256": pin}
    config = {"profiles": {"new": {"python": str(environment/"python"), "python_sha256": sha_file(base/"python"),
        "plain_pytest": True, "source_paths": []}},
        "group_profiles": {g: "new" for g in projected["case_bindings"]}, "source_stores": {"luigi": str(root/"luigi.git")},
        "inventories": inventories, "file_pins": {str(base/"python"): sha_file(base/"python")}}
    config_sha = write(root/"runtime-config.json", config)
    old_plan = {"inputs_sha256": input_sha, "runtime_config": {"source_stores": {"luigi": str(root/"luigi.git"), "scrapy": str(root/"scrapy.git")},
        "profiles": {"old": copy.deepcopy(config["profiles"]["new"])}, "group_profiles": {g: "old" for g in cases}},
        "workers": 2, "limits": {"cpu_seconds": 40, "wall_timeout_seconds": 45},
        "code_sha256": {name: sha_file(Path(__file__).with_name(name)) for name in CODE_FILES},
        "same_test_tree_on_both_implementations": True, "all_frozen_actions_executed": True, "outcome_dependent_stopping": False}
    old_sha, summary_sha = condition(root/"original", original, old_plan, {group: 1 for group in cases})
    args = {"original_inputs": inputs/"inputs.json", "original_executions": root/"original",
        "projected_inputs": projection/"inputs.json", "runtime_config": root/"runtime-config.json",
        "replacement_output": root/"replacement", "output": root/"selection", "inputs_sha256": input_sha,
        "original_plan_sha256": old_sha, "original_summary_sha256": summary_sha,
        "projected_inputs_sha256": projected_sha, "runtime_config_sha256": config_sha}
    return args, original, projected, old_plan


class OutcomeSelectionTests(unittest.TestCase):
    def test_entire_project_and_symlinked_interpreter_are_bound_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, original, projected, _ = fixture(root)
            before = args["runtime_config"].read_bytes()
            plan = freeze_selection(**args)
            pin = sha_file(root/"selection/plan.json")
            loaded, _, _, config, _ = load_selection(root/"selection/plan.json", pin)
            self.assertEqual(loaded, plan)
            self.assertEqual(set(plan["replacement"]["groups"]), set(projected["case_bindings"]))
            self.assertEqual(config["file_pins"][str(root/"selection/plan.json")], pin)
            self.assertEqual(args["runtime_config"].read_bytes(), before)
            self.assertFalse((root/"replacement").exists())
            (root/"base-runtime/python").write_bytes(b"changed interpreter")
            with self.assertRaises(ValueError): load_selection(root/"selection/plan.json", pin)

    def test_partial_project_changed_predictor_or_early_execution_is_rejected(self):
        for attack in ("partial", "source", "early", "adapter", "search_path"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                args, _, projected, _ = fixture(root)
                if attack == "partial": projected["case_bindings"].pop(next(iter(projected["case_bindings"])))
                elif attack == "source": projected["rows"][0]["source_version"] = {"different": True}
                elif attack == "early": args["replacement_output"].mkdir()
                else:
                    config = json.loads(args["runtime_config"].read_bytes())
                    config["profiles"]["new"]["plain_pytest" if attack == "adapter" else "source_paths"] = False if attack == "adapter" else ["different"]
                    args["runtime_config_sha256"] = write(args["runtime_config"], config)
                args["projected_inputs_sha256"] = write(args["projected_inputs"], projected)
                write(args["projected_inputs"].with_name("manifest.json"), {"inputs_sha256": args["projected_inputs_sha256"]})
                with self.assertRaises(ValueError): freeze_selection(**args)
                self.assertFalse((root/"selection/receipt.json").exists())

    def test_consistently_resealed_case_level_selection_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, _, _, _ = fixture(root)
            plan = freeze_selection(**args)
            plan["group_condition"]["bugsinpy/luigi/1"] = "original"
            pin = write(root/"selection/plan.json", plan)
            write(root/"selection/execution-runtime-config.json", derived_config(json.loads(args["runtime_config"].read_bytes()), root/"selection/plan.json", pin))
            with self.assertRaisesRegex(ValueError, "partial-project"):
                load_selection(root/"selection/plan.json", pin)


if __name__ == "__main__":
    unittest.main()
