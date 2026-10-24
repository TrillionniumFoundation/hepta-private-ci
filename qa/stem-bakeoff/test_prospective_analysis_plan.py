"""Synthetic inputs for immutable analysis planning; no real outcomes are opened."""

import copy
import unittest
from pathlib import Path

import numpy as np

from cell_learning_models import canonical
from prospective_analysis_plan import CONDITIONS, fixed_contrasts, make_plan, sha


def fixture():
    rows, cases = [], {}
    for number in range(51):
        split = ("train", "tuning", "calibration")[number] if number < 3 else "holdout"
        group = "group-"+str(number)
        project = "development-"+str(number) if number < 3 else "external-"+str((number-3)//10)
        actions = []
        for action in range(2):
            source = group+"-source-"+str(action)
            rows.append({"source_id": source, "group_id": group, "repo": project, "split": split,
                "text": "supplied source "+source, "source_version": {"revision": "frozen"}, "labels": {"task": None}})
            actions.append({"key": source+"-command", "source_id": source, "runner": "pytest", "args": [source]})
        cases[group] = {"project": project, "role": split, "actions": actions}
    inputs = {"rows": rows, "case_bindings": cases, "selected_tasks": ["task"],
              "all_labels_unobserved": True, "governing_protocol_sha256": "1"*64}
    records, matrices = {}, {}
    for index, name in enumerate(CONDITIONS):
        width = 3 if name == "identifier_overlap3" else 770
        available = [r for r in rows if not (name == "identifier_overlap3" and r["source_id"] == "group-3-source-1")]
        heldout = [r for r in available if r["split"] == "holdout"]
        x = np.zeros((len(heldout), width), np.float32)
        x[:, 0] = [0.8 if r["source_id"].endswith("1") else 0.2 for r in heldout]
        x[:, 1] = 1
        matrices[name] = x
        records[name] = {"feature_identity": str(index+2)*64, "width": width,
            "feature_report_path": "/fixture/"+name+"/report.json", "feature_report_sha256": "4"*64,
            "feature_archive_sha256": "5"*64, "feature_available_source_ids": [r["source_id"] for r in available],
            "holdout_source_ids": [r["source_id"] for r in heldout], "holdout_feature_tensor_sha256": sha(x.tobytes())}
    raw = dict(zip(records["identifier_overlap3"]["holdout_source_ids"], map(float, matrices["identifier_overlap3"][:, 0])))
    plan = make_plan(inputs, sha(canonical(inputs)), records, raw)
    dataset = {"input_dataset_sha256": plan["input_dataset_sha256"], "governing_protocol_sha256": "1"*64,
        "selected_tasks": ["task"], "all_proposed_actions_retained": True, "post_outcome_candidate_selection": False,
        "rows": copy.deepcopy(rows), "proposal_registry": copy.deepcopy(plan["proposal_shape"])}
    lookup = {r["source_id"]: r for r in dataset["rows"]}
    for group in dataset["proposal_registry"]:
        for action in group["actions"]:
            label = None if group["group_id"] == "group-4" else int(action["source_id"].endswith("1"))
            action.update(label=label, recorded_pair_wall_ns=1000, physical_command_executions=2)
            lookup[action["source_id"]]["labels"] = {"task": label}
    return inputs, plan, dataset, matrices


def alias_fixture(root, plan, dataset, name):
    """Opaque sealed numeric origin for analysis integration, without any fitting."""
    root, planned = Path(root), plan["conditions"][name]
    parent, alias = root/"parent-feature", root/"labelled-feature"
    parent.mkdir(parents=True); alias.mkdir()
    def write(path, value): path.write_bytes(canonical(value))
    source_ids = [row["source_id"] for row in plan["rows"]]
    values = np.zeros((len(source_ids), planned["width"]), np.float32)
    np.savez_compressed(parent/"features.npz", features=values)
    write(parent/"feature-availability.json", {"source_ids": source_ids,
        "available": [s in planned["feature_available_source_ids"] for s in source_ids]})
    write(parent/"source-bindings.json", plan["rows"])
    report = {"plan": {"dataset_sha256": plan["input_dataset_sha256"], "source_ids": source_ids},
        "condition": name, "feature_identity": planned["feature_identity"], "feature_shape": list(values.shape),
        "feature_archive_sha256": sha((parent/"features.npz").read_bytes()), "feature_tensor_sha256": sha(values.tobytes()),
        "feature_availability_sha256": sha((parent/"feature-availability.json").read_bytes()),
        "source_bindings_sha256": sha((parent/"source-bindings.json").read_bytes()),
        "source_record_digests": [r["source_digest"] for r in plan["rows"]]}
    write(parent/"report.json", report)
    write(parent/"manifest.json", {p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size} for p in parent.iterdir()})
    planned.update(feature_report_path=str(parent/"report.json"), feature_report_sha256=sha((parent/"report.json").read_bytes()),
        feature_manifest_sha256=sha((parent/"manifest.json").read_bytes()), feature_archive_sha256=report["feature_archive_sha256"])
    binding = {"parent_report_sha256": planned["feature_report_sha256"], "parent_manifest_sha256": planned["feature_manifest_sha256"],
        "parent_dataset_sha256": plan["input_dataset_sha256"], "labelled_dataset_sha256": sha(canonical(dataset)),
        "permitted_row_changes": ["labels", "outcome_provenance"], "numeric_payloads_byte_identical": True,
        "feature_availability_unchanged": True, "all_source_versions_text_spans_order_identical": True}
    report = copy.deepcopy(report)
    report.update(label_binding=binding, encoder_forward_calls=0, gradient_updates=0)
    report["plan"].update(dataset_sha256=sha(canonical(dataset)), label_attachment=binding)
    write(alias/"report.json", report); write(alias/"label-binding.json", binding)
    for name in ("features.npz", "feature-availability.json", "source-bindings.json"):
        (alias/name).write_bytes((parent/name).read_bytes())
    return {"feature_directory": str(alias), "feature_report_sha256": sha((alias/"report.json").read_bytes())}


class AnalysisPlanTests(unittest.TestCase):
    def test_all63_contrasts_are_fixed_without_seed_or_method_selection(self):
        inputs, plan, _, _ = fixture()
        self.assertEqual(len(plan["expected_holdout_group_ids"]), 48)
        self.assertEqual(len(plan["contrasts"]), 63)
        self.assertEqual(len({sha(canonical(v)) for v in plan["contrasts"]}), 63)
        self.assertEqual(sum(v["right"][0] is None for v in plan["contrasts"]), 18)
        self.assertEqual(plan["contrasts"], fixed_contrasts())
        self.assertFalse(plan["outcomes_or_predictions_used"])
        self.assertTrue(all(r["labels"] == {"task": None} for r in inputs["rows"]))

    def test_observed_labels_or_dropped_groups_cannot_become_source_only_plan(self):
        inputs, plan, _, _ = fixture()
        observed = copy.deepcopy(inputs)
        observed["rows"][0]["labels"]["task"] = 1
        for wrong in (observed, {**inputs, "case_bindings": dict(list(inputs["case_bindings"].items())[:-1])}):
            with self.assertRaises(ValueError):
                make_plan(wrong, "a"*64, plan["conditions"], plan["raw_jaccard"])

    def test_feature_unavailability_does_not_reduce_group_denominator(self):
        _, plan, _, _ = fixture()
        scalar, native = (plan["conditions"][name] for name in ("identifier_overlap3", "granite_clean_field770"))
        self.assertEqual(len(scalar["holdout_source_ids"]), 95)
        self.assertEqual(len(native["holdout_source_ids"]), 96)
        self.assertEqual(len(plan["expected_holdout_group_ids"]), 48)

    def test_feature_reordering_or_raw_control_missing_sources_are_rejected(self):
        inputs, plan, _, _ = fixture()
        changed = copy.deepcopy(plan["conditions"])
        changed["identifier_hash770"]["holdout_source_ids"].reverse()
        with self.assertRaises(ValueError): make_plan(inputs, "a"*64, changed, plan["raw_jaccard"])
        with self.assertRaises(ValueError): make_plan(inputs, "a"*64, plan["conditions"], {})


if __name__ == "__main__":
    unittest.main()
