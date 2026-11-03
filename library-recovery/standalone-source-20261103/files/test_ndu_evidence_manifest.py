#!/usr/bin/env python3
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ndu_evidence_manifest import (
    EvidenceManifestError,
    _digest,
    _manifest_digest,
    build_shadow_manifest,
    qualification_status,
    validate_manifest,
)


class EvidenceManifestTests(unittest.TestCase):
    def _observed_manifest(self):
        manifest = build_shadow_manifest(17)
        code_digest = manifest["experiment"]["code_digest"]
        trajectories = []
        for index in range(3):
            trajectories.append({
                "trajectory_id": f"live-{index}", "source_kind": "live_observed", "observed": True,
                "history_replay": False, "dataset_digest": _digest(f"dataset-{index}"),
                "environment_digest": _digest(f"environment-{index}"), "runner_code_digest": code_digest,
                "trajectory_digest": _digest(f"trajectory-{index}"),
            })
        manifest["experiment"]["synthetic"] = False
        manifest["trajectory_provenance"] = trajectories
        manifest["future_windows"] = [
            {"window_id": "future-0", "start_step": 0, "end_step": 10, "dataset_digest": _digest("future-data-0"), "snapshot_digest": _digest("snapshot-0"), "trajectory_ids": ["live-0"], "observed": True, "history_replay": False},
            {"window_id": "future-1", "start_step": 10, "end_step": 20, "dataset_digest": _digest("future-data-1"), "snapshot_digest": _digest("snapshot-1"), "trajectory_ids": ["live-1"], "observed": True, "history_replay": False},
        ]
        manifest["independent_snapshots"] = [
            {"snapshot_id": f"snap-{i}", "snapshot_digest": _digest(f"snap-digest-{i}"), "training_run_id": f"train-{i}", "parent_snapshot_digest": "b" * 64, "observed": True, "history_replay": False}
            for i in range(3)
        ]
        manifest["evaluations"]["future_utility"] = {"candidate_lcb": 0.8, "baseline_ucb": 0.7}
        manifest["evaluations"]["old_task"]["value"] = 0.01
        manifest["evaluations"]["ood"]["value"] = 0.001
        manifest["evaluations"]["calibration"]["value"] = 0.02
        manifest["evaluations"]["safety"]["passed"] = True
        manifest["evaluations"]["privacy"]["passed"] = True
        manifest["summary"].update({"future_windows": 2, "independent_snapshots": 3, "trajectory_count": 3, "observed_trajectory_count": 3, "synthetic_only": False})
        manifest["integrity"]["source"] = "external_experiment_runner"
        manifest["integrity"]["manifest_digest"] = _manifest_digest(manifest)
        return manifest

    def test_shadow_manifest_is_structurally_valid_but_never_qualifies(self):
        manifest = build_shadow_manifest(17)
        self.assertEqual(validate_manifest(manifest)["schema_version"], 1)
        status = qualification_status(manifest)
        self.assertTrue(status["valid"])
        self.assertFalse(status["eligible"])
        self.assertIn("synthetic_shadow_manifest", status["reason"])
        self.assertEqual(manifest["summary"]["future_windows"], 0)

    def test_digest_or_summary_tampering_fails_closed(self):
        manifest = build_shadow_manifest(17)
        altered = copy.deepcopy(manifest)
        altered["summary"]["trajectory_count"] = 99
        with self.assertRaises(EvidenceManifestError):
            validate_manifest(altered)
        altered = copy.deepcopy(manifest)
        altered["integrity"]["manifest_digest"] = "a" * 64
        with self.assertRaises(EvidenceManifestError):
            validate_manifest(altered)

    def test_replay_and_synthetic_observed_claims_are_rejected(self):
        manifest = build_shadow_manifest(17)
        altered = copy.deepcopy(manifest)
        altered["trajectory_provenance"][0]["history_replay"] = True
        altered["integrity"]["manifest_digest"] = "a" * 64
        with self.assertRaises(EvidenceManifestError):
            validate_manifest(altered)
        altered = build_shadow_manifest(17)
        altered["trajectory_provenance"][0]["observed"] = True
        altered["integrity"]["manifest_digest"] = "a" * 64
        with self.assertRaises(EvidenceManifestError):
            validate_manifest(altered)

    def test_unknown_window_trajectory_and_duplicate_snapshot_runs_reject(self):
        manifest = build_shadow_manifest(17)
        altered = copy.deepcopy(manifest)
        altered["future_windows"] = [{"window_id": "w1", "start_step": 0, "end_step": 1,
            "dataset_digest": "a" * 64, "snapshot_digest": "b" * 64,
            "trajectory_ids": ["missing"], "observed": True, "history_replay": False}]
        altered["summary"]["future_windows"] = 1
        altered["integrity"]["manifest_digest"] = "a" * 64
        with self.assertRaises(EvidenceManifestError):
            validate_manifest(altered)

    def test_observed_manifest_requires_independent_runs_and_can_be_structurally_eligible(self):
        manifest = self._observed_manifest()
        self.assertTrue(validate_manifest(manifest))
        status = qualification_status(manifest)
        self.assertTrue(status["valid"])
        self.assertTrue(status["eligible"])
        duplicate = copy.deepcopy(manifest)
        duplicate["independent_snapshots"][1]["training_run_id"] = duplicate["independent_snapshots"][0]["training_run_id"]
        duplicate["integrity"]["manifest_digest"] = _manifest_digest(duplicate)
        with self.assertRaises(EvidenceManifestError):
            validate_manifest(duplicate)

    def test_cli_writes_deterministic_shadow_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "manifest.json"
            proc = subprocess.run([sys.executable, "ndu_evidence_manifest.py", "--seed", "17", "--output", str(output)], check=True, capture_output=True, text=True)
            report = json.loads(proc.stdout)
            self.assertEqual(report["status"], "VALID_SHADOW_FIXTURE")
            self.assertFalse(report["qualification"]["eligible"])
            self.assertEqual(report, json.loads(output.read_text()))


if __name__ == "__main__":
    unittest.main()
