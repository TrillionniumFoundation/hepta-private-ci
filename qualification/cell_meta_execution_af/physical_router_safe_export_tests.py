"""Synthetic, adversarial tests of the redacted Granite evidence boundary."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from qualification.cell_meta_execution_af import physical_router_safe_export as subject

SENTINEL = "DO_NOT_PUBLISH_RAW_SAMPLE_TEXT_OR_TENSORS_54616"


def os_summary() -> dict:
    return {"schema": "hepta.cell-meta-isolated-kernel-resource-joined.v1",
            "authority_posture": "DENY_ALL", "production_admission": "BLOCKED",
            "exact_15_isolated_processes": 15,
            "original_source_row_count_not_tripled": 224,
            "resource_samples_are_three_correlated_seeds": True,
            "includes_python_import_and_replay_cost": True,
            "resource_or_model_winner_certified": False,
            "original_host_or_model_signatures_authenticated": False,
            "causal_reuse_or_total_compute_parity_proved": False,
            "independent_future_ndu_outcomes_observed": False,
            "energy_or_gpu_observed": False,
            "real_target_device_qualified": False,
            "median_kernel_cpu_seconds_by_arm": {k: 2.5 for k in subject.OS_ARMS},
            "median_peak_rss_bytes_by_arm": {k: 314_572_800 for k in subject.OS_ARMS},
            "raw_process_trace_that_must_not_export": SENTINEL}



def fivearm_summary(seed: int) -> dict:
    rows = []
    for name in subject.OS_ARMS:
        rows.append({"arm": name, "split_proposed": name in (
            "fixed_router", "learned_router", "adaptive_split"),
            "retrospective_scores": {
                "future_1": metrics(), "future_2": metrics()},
            "cost_observation": {
                "additional_stage2_training_head_rows": 0 if name == subject.OS_ARMS[0] else 512,
                "additional_stage2_optimizer_updates": 0 if name == subject.OS_ARMS[0] else 5,
                "evaluated_head_rows": 256,
                "train_router_rows": 0 if name == subject.OS_ARMS[0] else 128,
                "diagnostic_head_rows_in_existing_arm": 0},
            "raw_tensor": SENTINEL})
    return {"schema": "hepta.cell-meta-five-arm-retrospective.v1",
            "seed": seed, "source_kind": "external_unverified",
            "source_rule": "external", "shared_stem_sha256": "a" * 64,
            "retrospective_not_prospective": True,
            "same_source_calibration_not_ood": True,
            "research_only_no_independent_external_outcomes": True,
            "single_common_frozen_stage1_parent": True,
            "training_budget_unequal_across_five_arms": True,
            "complete_lifecycle_compute_matched": False,
            "statistical_winner_certified": False,
            "ndu_selection_authorized": False,
            "original_worker_model_origin_signed": False,
            "physical_cell_split_permitted": False,
            "production_admission": "BLOCKED", "authority_posture": "DENY_ALL",
            "arms": rows}


def metrics() -> dict:
    return {"accuracy": 0.5, "brier": 0.25, "nll": 0.69, "source_text": SENTINEL}


def summary(hard: bool) -> dict:
    arms = []
    for seed in subject.SEEDS:
        for arm in subject.ARMS:
            row = {"seed": seed, "arm": arm, "split_proposed": arm != "no_change",
                   "retrospective_test_1": metrics(),
                   "retrospective_test_2": metrics(),
                   "untrusted_raw_prediction": SENTINEL}
            if hard:
                row.update({"train_head_rows": 192, "eval_head_rows": 256,
                            "diagnostic_head_rows": 8, "train_router_rows": 32,
                            "sampled_routes": 32})
            else:
                row["head_forward_rows"] = 512
            arms.append(row)
    if hard:
        return {"schema": "hepta.cell-meta-hard-trained-physcpu-descriptive.v1",
                "production_admission": "BLOCKED", "authority_posture": "DENY_ALL",
                "retrospective_public_test_not_future": True,
                "ood_true_tested": False, "matched_total_compute": False,
                "independent_NDU_verified": False,
                "original_model_origin_independently_signed": False,
                "arms": arms}
    return {"schema": "hepta.cell-meta-granite-descriptive-only.v1",
            "registered_public_model": subject.MODEL_NAME,
            "production_admission": "BLOCKED", "authority_posture": "DENY_ALL",
            "future_window_prospective": False,
            "real_ood_verified": False, "total_compute_matched": False,
            "ndu_selection_authorized": False,
            "independent_model_origin_authenticated": False,
            "arms": arms}


def staged_directory(path: Path) -> None:
    for name in subject.EXPECTED:
        payload = (SENTINEL + "_" + name + "\n").encode()
        if name == "original-source-sha256.txt":
            payload = (subject.SOURCE_SHA + "\n").encode()
        elif name == "model-files-source-hash.txt":
            model_bytes = (SENTINEL + "_model-files.json\n").encode()
            payload = (hashlib.sha256(model_bytes).hexdigest() + "\n").encode()
        elif name == "descriptive-retrospective-summary.json":
            payload = json.dumps(summary(hard=False)).encode()
        elif name == "hardtop1-descriptive-retrospective-summary.json":
            payload = json.dumps(summary(hard=True)).encode()
        elif name == "os-meter-joined.json":
            payload = json.dumps(os_summary()).encode()
        elif name.endswith("-fivearm-report.json"):
            payload = json.dumps(fivearm_summary(int(name.split("-", 1)[0]))).encode()
        (path / name).write_bytes(payload)


class SafeGraniteArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name) / "evidence"
        self.root.mkdir()
        # Only synthetic test inputs: patch the expected exact digests to this
        # fixture's bytes. Real CLI execution always uses immutable originals.
        sample_bytes = lambda name: (SENTINEL + "_" + name + "\n").encode()
        patchers = [
            mock.patch.object(subject, "SOURCE_SHA",
                hashlib.sha256(sample_bytes("source-panel.json")).hexdigest()),
            mock.patch.object(subject, "SOURCE_PARQUET_SHA", {
                name: hashlib.sha256(sample_bytes(name)).hexdigest()
                for name in subject.SOURCE_PARQUET_SHA
            }),
        ]
        for patch in patchers:
            patch.start()
            self.addCleanup(patch.stop)
        staged_directory(self.root)

    def modify_summary(self, hard: bool, mutate) -> None:
        name = ("hardtop1-descriptive-retrospective-summary.json" if hard
                else "descriptive-retrospective-summary.json")
        path = self.root / name
        value = json.loads(path.read_text())
        mutate(value)
        path.write_text(json.dumps(value))

    def test_complete_structural_case_only_never_grants_model_authority(self):
        output = subject.produce(self.root)
        self.assertEqual(output["status"], "COMPLETE_DESCRIPTIVE_ONLY")
        self.assertEqual(output["reason_codes"], [])
        self.assertEqual(len(output["files"]), len(subject.EXPECTED))
        self.assertEqual(len(output["aggregate"]["four_arm_soft_research"]), 12)
        self.assertEqual(len(output["aggregate"]["four_arm_hard_top1_research"]), 12)
        self.assertEqual(len(output["aggregate"]["five_arm_os_medians"]["by_arm"]), 5)
        self.assertEqual(len(output["aggregate"]["five_arm_retrospective_research"]), 15)
        self.assertEqual(output["production_admission"], "BLOCKED")
        self.assertEqual(output["authority_posture"], "DENY_ALL")
        self.assertFalse(output["host_custody_authenticated"])
        self.assertFalse(output["prospective_future_windows_verified"])
        self.assertFalse(output["pretrained_origin_independently_authenticated"])

    def test_no_raw_text_q24_or_weights_ever_in_export(self):
        exported = json.dumps(subject.produce(self.root))
        self.assertNotIn(SENTINEL, exported)
        self.assertNotIn("untrusted_raw_prediction", exported)
        self.assertNotIn("source_text", exported)
        self.assertNotIn("feature_q24", exported)
        self.assertNotIn("data_le_hex", exported)

    def test_missing_dataset_stops_descriptive_completion(self):
        (self.root / "source-panel.json").unlink()
        output = subject.produce(self.root)
        self.assertEqual(output["status"], "BLOCKED")
        self.assertEqual(output["aggregate"], {})
        self.assertIn("source-panel.json", output["missing"])

    def test_missing_one_seed_hard_trained_evidence_stops_completion(self):
        (self.root / "53-hard-train-report.json").unlink()
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_unrecognized_extra_filename_denied_without_leaking_its_name(self):
        name = "private-secret-DO_NOT_PUBLISH_RAW_FILE_NAME.txt"
        (self.root / name).write_text(SENTINEL)
        obj = subject.produce(self.root)
        self.assertIn("unregistered_evidence_filename", obj["reason_codes"])
        self.assertNotIn(name, json.dumps(obj))
        self.assertNotIn(SENTINEL, json.dumps(obj))

    def test_symlink_to_secret_denied_without_read(self):
        path = self.root / "41-trial-panel.json"
        secret = self.root.parent / "outside-secret.txt"
        secret.write_text(SENTINEL)
        path.unlink()
        path.symlink_to(secret)
        obj = subject.produce(self.root)
        self.assertEqual(obj["status"], "BLOCKED")
        self.assertNotIn(SENTINEL, json.dumps(obj))

    def test_fifo_is_rejected_nonblocking(self):
        path = self.root / "41-trial-report.json"
        path.unlink()
        os.mkfifo(path)
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_source_identity_drift_blocks(self):
        (self.root / "original-source-sha256.txt").write_text("f" * 64 + "\n")
        obj = subject.produce(self.root)
        self.assertEqual(obj["status"], "BLOCKED")
        self.assertEqual(obj["aggregate"], {})

    def test_false_future_claims_block(self):
        self.modify_summary(False, lambda o: o.__setitem__("future_window_prospective", True))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_false_hard_ndu_claims_block(self):
        self.modify_summary(True, lambda o: o.__setitem__("independent_NDU_verified", True))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_changed_public_panel_bytes_even_with_unchanged_claim_block(self):
        (self.root / "source-panel.json").write_bytes(b"changed upstream source panel")
        output = subject.produce(self.root)
        self.assertEqual(output["status"], "BLOCKED")
        self.assertEqual(output["aggregate"], {})

    def test_changed_pinned_parquet_bytes_even_with_unchanged_claim_block(self):
        for name in subject.SOURCE_PARQUET_SHA:
            with self.subTest(name=name):
                original = (self.root / name).read_bytes()
                (self.root / name).write_bytes(original + b"tamper")
                self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")
                (self.root / name).write_bytes(original)

    def test_changed_model_inventory_bytes_with_unchanged_pointer_block(self):
        (self.root / "model-files.json").write_bytes(b"falsified pretrained file list")
        output = subject.produce(self.root)
        self.assertEqual(output["status"], "BLOCKED")
        self.assertEqual(output["aggregate"], {})

    def test_changed_model_inventory_pointer_only_block(self):
        (self.root / "model-files-source-hash.txt").write_bytes(("b" * 64 + "\n").encode())
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_wrong_model_name_blocks(self):
        self.modify_summary(False, lambda o: o.__setitem__("registered_public_model", "other/model"))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_duplicate_arm_pair_blocks(self):
        self.modify_summary(False, lambda o: o["arms"].__setitem__(1, copy.deepcopy(o["arms"][0])))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_nonfinite_metric_blocks(self):
        self.modify_summary(True, lambda o: o["arms"][0]["retrospective_test_1"].__setitem__("brier", float("nan")))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_boolean_pretending_to_be_numeric_blocks(self):
        self.modify_summary(True, lambda o: o["arms"][0].__setitem__("train_head_rows", True))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_forged_fivearm_model_origin_denied(self):
        path = self.root / "41-fivearm-report.json"
        value = json.loads(path.read_text())
        value["original_worker_model_origin_signed"] = True
        path.write_text(json.dumps(value))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_forged_fivearm_encoder_across_seeds_denied(self):
        path = self.root / "53-fivearm-report.json"
        value = json.loads(path.read_text())
        value["shared_stem_sha256"] = "b" * 64
        path.write_text(json.dumps(value))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_forged_frozen_optimizer_updates_denied(self):
        path = self.root / "47-fivearm-report.json"
        value = json.loads(path.read_text())
        value["arms"][0]["cost_observation"]["additional_stage2_optimizer_updates"] = 1
        path.write_text(json.dumps(value))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_forged_os_energy_or_production_resource_winner_denied(self):
        p = self.root / "os-meter-joined.json"
        v = json.loads(p.read_text())
        v["energy_or_gpu_observed"] = True
        v["resource_or_model_winner_certified"] = True
        p.write_text(json.dumps(v))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_nonsensical_os_resource_cost_denied(self):
        p = self.root / "os-meter-joined.json"
        v = json.loads(p.read_text())
        v["median_peak_rss_bytes_by_arm"][subject.OS_ARMS[0]] = -1
        p.write_text(json.dumps(v))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_duplicate_json_member_blocks(self):
        path = self.root / "descriptive-retrospective-summary.json"
        original = path.read_text()
        path.write_text('{"schema":"x",' + original[1:])
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_oversized_file_blocks(self):
        path = self.root / "41-trial-report.json"
        with path.open("wb") as output:
            output.truncate(subject.MAX_FILE_BYTES + 1)
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_unrecognized_directory_denied(self):
        (self.root / "nested").mkdir()
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_output_is_create_only_and_unchanged_on_repeat(self):
        output_path = Path(self.dir.name) / "public-receipt.json"
        args = ["--root", str(self.root), "--out", str(output_path)]
        self.assertEqual(subject.main(args), 0)
        original = output_path.read_bytes()
        self.assertEqual(subject.main(args), 2)
        self.assertEqual(output_path.read_bytes(), original)
        self.assertNotIn(SENTINEL.encode(), original)

    def test_failed_job_exports_minimal_blocked_receipt(self):
        output_path = Path(self.dir.name) / "public-receipt.json"
        (self.root / "41-os-meter.json").unlink()
        result = subject.main(["--root", str(self.root), "--out", str(output_path)])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output_path.read_bytes())["status"], "BLOCKED")

    def test_missing_directory_fails_without_fabricated_evidence(self):
        p = self.root.parent / "absent"
        self.assertEqual(subject.produce(p)["status"], "BLOCKED")
        self.assertEqual(subject.produce(p)["files"], [])

    def test_workflow_can_publish_only_one_redacted_receipt(self):
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/hepta-cell-meta-granite-real.yml"
        body = workflow.read_text(encoding="utf-8")
        section = body.split("- name: Publish ONLY redacted receipt, no raw source/features/Head weights", 1)
        self.assertEqual(len(section), 2)
        self.assertEqual(section[1].count("actions/upload-artifact@v4"), 1)
        self.assertIn("path: ${{ runner.temp }}/hepta-meta-redacted/granite-redacted-receipt.json", section[1])
        self.assertNotIn("*-trial", section[1])
        self.assertNotIn("*-hard", section[1])
        self.assertNotIn("granite-q24-features.json", section[1])
        self.assertNotIn("hepta-meta-real/", section[1])

    def test_export_does_not_read_from_symlink_root(self):
        symlink = self.root.parent / "symlink-root"
        symlink.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(subject.produce(symlink)["status"], "BLOCKED")

    def test_metric_bounds_denied(self):
        self.modify_summary(False, lambda o: o["arms"][0]["retrospective_test_1"].__setitem__("accuracy", 9.0))
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")

    def test_malformed_empty_required_file_denied(self):
        (self.root / "model-files.json").write_bytes(b"")
        self.assertEqual(subject.produce(self.root)["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
