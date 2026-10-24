"""Sealed synthetic predictions exercise provenance and replay validation only."""

import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_action_inference import _input_digest
from cell_action_prepare import DEFAULT_PROTOCOL, code_hashes
from cell_learning_models import canonical
from prospective_analysis_artifacts import CapturedArtifacts, bounded_array, load_condition, validate_dataset, verify_alias_lineage
from prospective_analysis_plan import ARMS, BUDGETS, CONTROLS, SEEDS, sha
from test_prospective_analysis_plan import alias_fixture, fixture


def write(path, value):
    Path(path).write_bytes(canonical(value)+b"\n")


def seal(root):
    root = Path(root)
    write(root/"seal.json", {"schema": "fixture", "files": {p.relative_to(root).as_posix():
        {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size} for p in root.rglob("*")
        if p.is_file() and p != root/"seal.json"}})
    return sha((root/"seal.json").read_bytes())


def prediction_artifacts(root, plan, dataset, matrices, name, omitted=()):
    root, source = Path(root), plan["conditions"][name]
    prepared, inference = root/"prepared", root/"inference"
    prepared.mkdir(parents=True); inference.mkdir()
    feature = alias_fixture(root, plan, dataset, name)
    rows = {r["source_id"]: r for r in dataset["rows"]}
    public = [{key: rows[s][key] for key in ("source_id", "group_id", "text")} for s in source["holdout_source_ids"]]
    bindings = {"dataset_sha256": sha(canonical(dataset)), "feature_report_sha256": feature["feature_report_sha256"],
                "proposal_plan_sha256": plan["input_dataset_sha256"]}
    pp = {"feature_identity": source["feature_identity"], "width": source["width"], "input_bindings": bindings,
          "code_sha256": code_hashes(), "configuration": copy.deepcopy(DEFAULT_PROTOCOL)}
    frozen, runs = {"plan": pp, "runs": [], "unavailable": [], "all_choices_frozen_before_heldout_scoring": True,
                    "wall_ns": 1, "cpu_ns": 1}, []
    for seed in SEEDS:
        for budget in BUDGETS:
            if (seed, budget) in omitted:
                frozen["unavailable"].append({"seed": seed, "budget": budget, "reason": "fixture missing class support"})
                continue
            directory = f"seed-{seed}_n-{budget}"
            location = inference/directory
            location.mkdir()
            before = {"seed": seed, "budget": budget, "directory": directory, "selected_arm": "gated",
                      "selection_source": "independent_tuning_repositories_only", "arms": {}}
            run = {**before, "arms": {}}
            for arm in ARMS:
                head = arm in ("linear", "gated", "residual")
                kind = "prior" if arm == "prior_only" else "head" if head else "baseline"
                spec = {"kind": kind, "trainable_parameters": 4 if head else 0}
                if kind == "prior": spec["prior"] = [.6, .4]
                else: spec.update(calibration={"prior_positive": .4}, predictor_sha256="c"*64)
                before["arms"][arm] = spec
                p1 = np.asarray([.9 if s.endswith("1") else .1 for s in source["holdout_source_ids"]]) if arm in ("gated", "residual") else np.full(len(public), .4)
                probabilities = np.column_stack((1-p1, p1))
                logits, eligible = np.log(probabilities), np.full(len(public), arm != "exact", dtype=bool)
                def save(filename, z, p, admitted=True):
                    arrays = {"logits": z, "probabilities": p}
                    if admitted: arrays["eligible"] = eligible
                    np.savez_compressed(location/filename, **arrays)
                    return sha((location/filename).read_bytes())
                receipt = {"prediction_file": arm+".npz", "prediction_sha256": save(arm+".npz", logits, probabilities),
                    "rows": len(public), "eligible_rows": int(eligible.sum()), "calibration": spec.get("calibration"),
                    "prediction_cost": {"wall_ns": 1, "cpu_ns": 1}, "trainable_parameters": spec["trainable_parameters"]}
                if head:
                    receipt.update(tensor_sha256="c"*64, controls={}, fresh_process={
                        "output_sha256": save(arm+"-fresh.npz", logits, probabilities, False),
                        "bitwise_equal_logits_and_probabilities": True, "test_labels_provided_to_child": False, "child_cpu_ns": 1})
                    for control in CONTROLS:
                        cp = np.tile([.6, .4], (len(public), 1)) if control == "parameters_off" else probabilities[:, ::-1]
                        filename = arm+"-"+control+".npz"
                        receipt["controls"][control] = {"prediction_file": filename,
                            "prediction_sha256": save(filename, np.log(cp), cp), "rows": len(public),
                            "eligible_rows": int(eligible.sum()), "calibration_refitted": False,
                            "retained_calibration_predictor_sha256": "c"*64, "prediction_cost": {"wall_ns": 1, "cpu_ns": 1}}
                run["arms"][arm] = receipt
            frozen["runs"].append(before); runs.append(run)
    write(prepared/"frozen.json", frozen)
    prepared_sha = seal(prepared)
    ip = {"input_bindings": bindings, "feature_identity": pp["feature_identity"], "prepared_seal_sha256": prepared_sha,
        "labels_or_outcomes_received": False, "metrics_computed": False, "fitting_performed": False,
        "prediction_role": "prospective_external_candidates", "input_sha256": _input_digest(matrices[name], public)}
    np.save(inference/"features.npy", matrices[name], allow_pickle=False)
    report = {"plan": ip, "runs": runs, "source_ids": source["holdout_source_ids"],
        "group_ids": [r["group_id"] for r in public], "unavailable": frozen["unavailable"],
        "wall_ns": 1, "cpu_ns": 1, "fresh_process_child_cpu_ns": 27}
    write(inference/"report.json", report)
    return {"name": name, "feature_identity": pp["feature_identity"], "status": "complete", **feature, "input_bindings": bindings,
        "prepared_dir": str(prepared), "preparation_seal_sha256": prepared_sha,
        "preparation_report_sha256": sha((prepared/"frozen.json").read_bytes()), "inference_dir": str(inference),
        "inference_report_sha256": sha((inference/"report.json").read_bytes()), "inference_seal_sha256": seal(inference)}


class AnalysisArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        _, self.plan, self.dataset, matrices = fixture()
        self.name = "identifier_overlap3"
        self.record = prediction_artifacts(self.root/"condition", self.plan, self.dataset, matrices, self.name)

    def tearDown(self):
        self.temporary.cleanup()

    def load(self, captured=None):
        rows, _ = validate_dataset(self.dataset, self.plan)
        return load_condition(captured or CapturedArtifacts(), self.record, self.plan["conditions"][self.name],
                              rows, sha(canonical(self.dataset)))

    def change_report(self, change):
        root = Path(self.record["inference_dir"])
        report = json.loads((root/"report.json").read_bytes())
        change(report, root)
        write(root/"report.json", report)
        self.record.update(inference_report_sha256=sha((root/"report.json").read_bytes()), inference_seal_sha256=seal(root))

    def test_complete_controls_fresh_bytes_and_unknown_sources_are_retained(self):
        captured = CapturedArtifacts()
        result = self.load(captured)
        self.assertEqual(len(result["runs"]), 9)
        self.assertEqual(len(result["source_ids"]), 95)
        self.assertIn("group-4-source-0", result["source_ids"])
        self.assertEqual(len(result["runs"][(7, 8)]["variants"]), 15)
        captured.verify()

    def test_consistently_resealed_wrong_order_or_control_refit_is_rejected(self):
        self.change_report(lambda report, _: report["source_ids"].reverse())
        with self.assertRaisesRegex(ValueError, "source contract"): self.load()
        self.change_report(lambda report, _: report["source_ids"].reverse())
        self.change_report(lambda report, _: report["runs"][0]["arms"]["gated"]["controls"]["parameters_off"].update(calibration_refitted=True))
        with self.assertRaisesRegex(ValueError, "refitted"): self.load()

    def test_consistently_resealed_fresh_mismatch_is_rejected(self):
        def change(report, root):
            run = report["runs"][0]
            path = root/run["directory"]/"gated-fresh.npz"
            with np.load(path) as archive: z, p = archive["logits"], archive["probabilities"]
            z[0, 0] += .01
            np.savez_compressed(path, logits=z, probabilities=p)
            run["arms"]["gated"]["fresh_process"]["output_sha256"] = sha(path.read_bytes())
        self.change_report(change)
        with self.assertRaisesRegex(ValueError, "parity"): self.load()

    def test_late_artifact_or_extra_file_mutation_is_not_adopted(self):
        captured = CapturedArtifacts()
        self.load(captured)
        root = Path(self.record["inference_dir"])
        (root/"extra.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "extra"): captured.verify()
        (root/"extra.json").unlink()
        (root/"report.json").write_bytes((root/"report.json").read_bytes()+b" ")
        with self.assertRaisesRegex(ValueError, "pin differs"): captured.verify()

    def test_changed_source_or_invented_unknown_target_is_rejected(self):
        changed = copy.deepcopy(self.dataset)
        changed["rows"][0]["source_version"] = {"revision": "different"}
        with self.assertRaisesRegex(ValueError, "source order/content"): validate_dataset(changed, self.plan)
        changed = copy.deepcopy(self.dataset)
        changed["rows"][0]["labels"]["task"] = True
        with self.assertRaisesRegex(ValueError, "binary-or-unknown"): validate_dataset(changed, self.plan)

    def test_enormous_declared_array_is_rejected_before_any_allocation(self):
        stream = io.BytesIO()
        np.lib.format.write_array_header_1_0(stream, {"descr": "<f8", "fortran_order": False, "shape": (10**12, 2)})
        with self.assertRaisesRegex(ValueError, "before allocation"):
            bounded_array(stream.getvalue(), (95, 2), "f")

    def test_different_training_archive_cannot_alias_matching_holdout_features(self):
        captured = CapturedArtifacts()
        verify_alias_lineage(captured, self.record, self.plan["conditions"][self.name], self.plan, sha(canonical(self.dataset)))
        root = Path(self.record["feature_directory"])
        report = json.loads((root/"report.json").read_bytes())
        with np.load(root/"features.npz") as archive: values = archive["features"]
        values[0, 0] += 1  # TRAIN only; every query feature remains unchanged.
        np.savez_compressed(root/"features.npz", features=values)
        report.update(feature_archive_sha256=sha((root/"features.npz").read_bytes()), feature_tensor_sha256=sha(values.tobytes()))
        write(root/"report.json", report)
        self.record["feature_report_sha256"] = sha((root/"report.json").read_bytes())
        self.record["input_bindings"]["feature_report_sha256"] = self.record["feature_report_sha256"]
        with self.assertRaisesRegex(ValueError, "whole-feature archive"):
            verify_alias_lineage(CapturedArtifacts(), self.record, self.plan["conditions"][self.name], self.plan, sha(canonical(self.dataset)))


if __name__ == "__main__":
    unittest.main()
