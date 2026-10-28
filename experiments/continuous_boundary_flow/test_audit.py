"""Behavioral audit tests with hand-computed rewards and corrupt evidence."""

import gzip
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from experiments.continuous_boundary_flow.audit import (
    AuditError,
    audit_episode,
    audit_run,
    calibration_scores,
    paired_summary,
    q24_product,
    window_utility,
)


class AuditPrimitiveTests(unittest.TestCase):
    def setUp(self):
        self.spec = {
            "discount": 0.0,
            "dt": 1.0,
            "production_rate": 2.0,
            "failure_cost": 3.0,
            "maintenance_cost": 0.5,
        }

    def test_realized_repair_failure_and_survival_ledger(self):
        survive = window_utility(self.spec, 0, "wait", 1.0, False, None)
        failed = window_utility(self.spec, 1, "repair", 0.25, True, 0.25)
        stopped = window_utility(self.spec, 2, "stop", 0.0, False, None)
        self.assertEqual(
            survive,
            {
                "gross_utility": 2.0,
                "production": 2.0,
                "failure_cost": 0.0,
                "maintenance_cost": 0.0,
            },
        )
        self.assertEqual(
            failed,
            {
                "gross_utility": -3.0,
                "production": 0.5,
                "failure_cost": 3.0,
                "maintenance_cost": 0.5,
            },
        )
        self.assertEqual(
            stopped,
            {
                "gross_utility": 0.0,
                "production": 0.0,
                "failure_cost": 0.0,
                "maintenance_cost": 0.0,
            },
        )

    def test_failure_is_discounted_at_first_passage(self):
        self.spec["discount"] = math.log(2)
        result = window_utility(self.spec, 1, "wait", 0.5, True, 0.5)
        expected_production = (1 - 1 / math.sqrt(2)) / math.log(2)
        expected_failure = 1.5 / math.sqrt(2)
        self.assertAlmostEqual(
            result["gross_utility"], expected_production - expected_failure
        )

    def test_impossible_or_nonfinite_primitives_are_rejected(self):
        cases = [
            ("wait", 0.5, False, None),
            ("repair", 0.5, True, 0.8),
            ("stop", 0.1, False, None),
            ("wait", float("nan"), False, None),
        ]
        for action, duration, failed, tau in cases:
            with (
                self.subTest(action=action, duration=duration),
                self.assertRaises(AuditError),
            ):
                window_utility(self.spec, 0, action, duration, failed, tau)

    def test_risk_scoring_has_a_hand_computed_answer(self):
        result = calibration_scores([0.0, 0.25, 0.75, 1.0], [0, 1, 1, 0])
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["brier"], 0.40625)
        self.assertEqual(result["ece"], 0.5)
        self.assertEqual(sum(row["count"] for row in result["bins"]), 4)
        for probabilities, labels in [
            ([1.1], [0]),
            ([0.1], [2]),
            ([float("nan")], [1]),
        ]:
            with self.assertRaises(AuditError):
                calibration_scores(probabilities, labels)

    def test_seed_intervals_do_not_promote_noisy_mean_to_success(self):
        positive = paired_summary([2.0] * 8)
        noisy = paired_summary([-10.0, 10.2] * 4)
        uncorrected = paired_summary([-10.0, 10.2] * 4, family_size=1)
        self.assertEqual(positive["simultaneous_interval"], [2.0, 2.0])
        self.assertTrue(positive["positive_utility_established"])
        self.assertFalse(noisy["positive_utility_established"])
        self.assertEqual(noisy["n_independent_seeds"], 8)
        self.assertLess(
            noisy["simultaneous_interval"][0], uncorrected["simultaneous_interval"][0]
        )
        self.assertEqual(
            noisy["bootstrap_95_descriptive"],
            paired_summary([-10.0, 10.2] * 4)["bootstrap_95_descriptive"],
        )


class AuditBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def fixture(self):
        arms = ["learned_margin", "value_call", "value_dual"]
        frozen = {
            "arms": arms,
            "seeds": list(range(8)),
            "splits": {"test_id": 1, "test_ood": 1},
            "split_weights": {"test_id": 0.5, "test_ood": 0.5},
            "primary_pairs": [
                {"name": "boundary", "treatment": arms[1], "control": arms[0]},
                {"name": "dual", "treatment": arms[2], "control": arms[1]},
                {"name": "flow", "treatment": arms[2], "control": arms[0]},
            ],
            "phase_ids": {
                "training": ["train-1"],
                "development": ["dev-1"],
                "confirmation": ["test-1"],
            },
            "message_price_per_byte": 1e-6,
            "minimum_effect": 0.005,
        }
        (self.root / "protocol.json").write_text(json.dumps(frozen))
        manifest = {
            **frozen,
            "schema": "hepta.continuous-boundary.study.v1",
            "checkpoints": [],
            "records": [],
            "protocol_sha256": self.sha("protocol.json"),
        }
        for arm in arms:
            for seed in range(8):
                path = f"checkpoint-{arm}-{seed}.json"
                profile_path = f"profile-{arm}-{seed}.json"
                profile = {
                    "risk_ceiling_q24": 2**24,
                    "kernel": {"width": 20},
                    "head_weights_q24": [[0] * 20 for _ in range(3)],
                    "head_bias_q24": [1, 0, 0],
                }
                (self.root / profile_path).write_text(json.dumps(profile))
                (self.root / path).write_text(
                    json.dumps(
                        {
                            "arm": arm,
                            "seed": seed,
                            "profile_path": profile_path,
                            "profile_sha256": self.sha(profile_path),
                        }
                    )
                )
                checkpoint_hash = self.sha(path)
                manifest["checkpoints"].append(
                    {
                        "arm": arm,
                        "train_seed": seed,
                        "path": path,
                        "sha256": checkpoint_hash,
                    }
                )
                for split in frozen["splits"]:
                    row = {
                        "arm": arm,
                        "train_seed": seed,
                        "split": split,
                        "episode_id": f"{split}-0",
                        "eval_seed": 1000 + seed,
                        "checkpoint_sha256": checkpoint_hash,
                        "spec": {
                            "horizon": 1,
                            "discount": 0,
                            "dt": 1,
                            "production_rate": 2,
                            "failure_cost": 3,
                            "maintenance_cost": 0.5,
                        },
                        "reported_utility": 2,
                        "reported_net_utility": 2 - 160e-6,
                        "stability_failure": False,
                        "steps": [
                            {
                                "elapsed": 0,
                                "action": "wait",
                                "state_idx": 1,
                                "x": 1.0,
                                "active_time": 1,
                                "failed": False,
                                "tau_hit": None,
                                "predicted_risk": 0.25,
                                "source_kernel_calls": 1,
                                "native_ndu_calls": 1,
                                "semantic_message_bytes": 160,
                                "wire_request_bytes": 300,
                                "wire_response_bytes": 400,
                                "model_state_updates": 20,
                                "solver_evals": 0,
                                "activation_q24": [0] * 20,
                                "scores_q24": [1, 0, 0],
                                "raw_features": {
                                    "raw_q24": [0] * 17,
                                    "continuous": {
                                        "margin_q24": 0,
                                        "risk_q24": 0,
                                        "flow_q24": 0,
                                    },
                                },
                            }
                        ],
                    }
                    path = f"records-{arm}-{seed}-{split}.jsonl.gz"
                    (self.root / path).write_bytes(
                        gzip.compress((json.dumps(row) + "\n").encode(), mtime=0)
                    )
                    manifest["records"].append(
                        {"path": path, "sha256": self.sha(path), "count": 1}
                    )
        cost = {
            "phase": "evaluation",
            "arm": "shared",
            "wall_seconds": 0.1,
            "python_cpu_seconds": 0.02,
            "completed_child_cpu_seconds": 0.04,
            "cost_scope": "Synthetic fixture's measured-cost fields, not a benchmark",
        }
        (self.root / "costs.jsonl").write_text(json.dumps(cost) + "\n")
        manifest["costs_sha256"] = self.sha("costs.jsonl")
        self.save_manifest(manifest)
        return manifest

    def sha(self, relative):
        return hashlib.sha256((self.root / relative).read_bytes()).hexdigest()

    def save_manifest(self, manifest):
        (self.root / "manifest.json").write_text(json.dumps(manifest))

    def change_rows(self, manifest, change):
        entry = manifest["records"][0]
        rows = [
            json.loads(line)
            for line in gzip.decompress((self.root / entry["path"]).read_bytes())
            .decode()
            .splitlines()
        ]
        rows = change(rows)
        payload = "".join(json.dumps(row) + "\n" for row in rows).encode()
        (self.root / entry["path"]).write_bytes(gzip.compress(payload, mtime=0))
        entry.update({"sha256": self.sha(entry["path"]), "count": len(rows)})
        self.save_manifest(manifest)

    def test_complete_bundle_uses_primitives_and_seed_unit(self):
        self.fixture()
        (self.root / "summary.json").write_text(
            json.dumps({"utility": 1e20, "benefit_gate_passed": True})
        )
        result = audit_run(self.root)
        self.assertTrue(result["integrity_passed"])
        self.assertEqual(result["raw_episode_count"], 48)
        self.assertEqual(result["arm_metrics"]["value_dual"]["gross_utility"], 2)
        self.assertAlmostEqual(
            result["arm_metrics"]["value_dual"]["net_utility"], 1.99984
        )
        self.assertEqual(
            result["arm_metrics"]["value_dual"]["brier_equal_episode"], 0.0625
        )
        self.assertTrue(result["costs"]["hash_bound"])
        self.assertTrue(
            all(
                p["n_independent_seeds"] == 8 and not p["benefit_gate_passed"]
                for p in result["primary_comparisons"]
            )
        )

    def test_independent_physics_and_frozen_head_checks(self):
        manifest = self.fixture()
        entry = manifest["records"][0]
        row = json.loads(gzip.decompress((self.root / entry["path"]).read_bytes()))
        step = row["steps"][0]
        risk, hit = math.erfc(1 / math.sqrt(2)), math.erfc(1 / math.sqrt(0.5))
        row["spec"].update({"mu": 0.0, "sigma": 1.0})
        step.update(
            {
                "failed": True,
                "active_time": 0.25,
                "tau_hit": 0.25,
                "x_after_action": 1.0,
                "predicted_risk": risk,
                "uniforms": [0.5, 0.5, 0.1, hit / risk, 0.5, 0.5],
            }
        )
        row.update({"reported_utility": -2.5, "reported_net_utility": -2.50016})
        self.assertEqual(
            audit_episode(row, 1e-6)["physical_first_hit_steps_verified"], 1
        )
        step.update({"active_time": 0.3, "tau_hit": 0.3})
        row.update({"reported_utility": -2.4, "reported_net_utility": -2.40016})
        with self.assertRaises(AuditError):
            audit_episode(row, 1e-6)
        self.assertEqual([q24_product(a, 2**23) for a in [1, 3, -3]], [0, 2, -2])
        step.update({"active_time": 0.25, "tau_hit": 0.25})
        row.update({"reported_utility": -2.5, "reported_net_utility": -2.50016})
        altered = {
            "head_weights_q24": [[0] * 20 for _ in range(3)],
            "head_bias_q24": [2, 0, 0],
        }
        with self.assertRaises(AuditError):
            audit_episode(row, 1e-6, altered)

    def test_mutated_rehashed_raw_evidence_is_rejected(self):
        def reward(rows):
            rows[0]["reported_utility"] += 1
            return rows

        def native_action(rows):
            rows[0]["steps"][0]["scores_q24"] = [0, 1, 0]
            return rows

        def paired_environment(rows):
            rows[0]["eval_seed"] += 99
            return rows

        for label, mutation in [
            ("reward", reward),
            ("duplicate", lambda x: x + x),
            ("omission", lambda x: []),
            ("native action", native_action),
            ("paired inputs", paired_environment),
        ]:
            with self.subTest(label=label):
                manifest = self.fixture()
                self.change_rows(manifest, mutation)
                with self.assertRaises(AuditError):
                    audit_run(self.root)

    def test_checkpoint_cost_and_gate_tampering_is_rejected(self):
        for kind in ("checkpoint", "profile", "cost", "gate", "phase overlap"):
            with self.subTest(kind=kind):
                manifest = self.fixture()
                if kind == "checkpoint":
                    (self.root / manifest["checkpoints"][0]["path"]).write_text(
                        "tampered"
                    )
                elif kind == "profile":
                    checkpoint = json.loads(
                        (self.root / manifest["checkpoints"][0]["path"]).read_text()
                    )
                    (self.root / checkpoint["profile_path"]).write_text("tampered")
                elif kind == "cost":
                    (self.root / "costs.jsonl").write_text("tampered")
                elif kind == "gate":
                    manifest["minimum_effect"] = 0
                    self.save_manifest(manifest)
                else:
                    manifest["phase_ids"]["confirmation"] = ["train-1"]
                    frozen = json.loads((self.root / "protocol.json").read_text())
                    frozen["phase_ids"] = manifest["phase_ids"]
                    (self.root / "protocol.json").write_text(json.dumps(frozen))
                    manifest["protocol_sha256"] = self.sha("protocol.json")
                    self.save_manifest(manifest)
                with self.assertRaises(AuditError):
                    audit_run(self.root)


if __name__ == "__main__":
    unittest.main()
