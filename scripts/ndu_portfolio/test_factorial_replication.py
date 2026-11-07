"""Adversarial checks for training pseudoreplication and global receipt locks."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from .example_factorial import example
from . import factorial as f
from .factorial_replication import (
    audit_replication,
    design_digest,
    planning_power,
    select_replicated,
    main,
)


def fixture():
    """Synthetic arithmetic only; no model or training process is executed here."""
    original, rows, _ = example()
    original["bootstrap_samples"] = 10000
    fits = {}
    for index in range(4):
        key = f"fit-{index}"
        protocol, episodes = copy.deepcopy(original), copy.deepcopy(rows)
        for name, profile in protocol["profiles"].items():
            regime, arm = name.split(":")
            profile["initial_content_digest"] = f.canonical_digest(
                [key, profile["core"], "initial"]
            )
            profile["model_digest"] = f.canonical_digest([key, regime, profile["core"]])
            profile["policy_digest"] = f.canonical_digest([key, regime, arm])
        for row in episodes:
            row["fit_id"] = key
            row["run_id"] = key + "/" + row["run_id"]
            row["attempt_ids"] = [key + "/" + attempt for attempt in row["attempt_ids"]]
            profile = protocol["profiles"][f"{row['regime']}:{row['arm']}"]
            for field in ("model_digest", "policy_digest"):
                row[field] = profile[field]
            if row["arm"] == "D" and "/new/" in row["task_id"]:
                row["external_score"] += 0.1 * (index - 1.5)
        fits[key] = {
            "protocol": protocol,
            "rows": episodes,
            "execution": {
                "run_id": key + "/training",
                "receipt_digest": f.canonical_digest([key, "receipt"]),
                "training_seed": 100 + index,
                "started_at": "2026-11-01T01:00:00Z",
                "finished_at": "2026-11-01T12:00:00Z",
                "attempt_ids": [key + "/training/attempt-0"],
                "failed_attempts": 0,
                "protocol_digest": f.protocol_digest(protocol),
            },
        }
    plan = {
        "schema": "ndu-factorial-replication-v1",
        "registered_at": "2026-10-31T00:00:00Z",
        "design_digest": design_digest(original),
        "fits": [
            {"fit_id": key, "training_seed": value["execution"]["training_seed"]}
            for key, value in fits.items()
        ],
        "power": {
            "effect_above_margin": 0.15,
            "target_power": 0.8,
            "fit_variance": 0.001,
            "source_variance": 0.001,
            "interaction_variance": 0.001,
            "variance_evidence_digest": f.canonical_digest("synthetic pilot"),
        },
    }
    return plan, fits


def lock(plan, fits):
    validation = {
        key: {
            **fit,
            "rows": [row for row in fit["rows"] if row["split"] == "validation"],
        }
        for key, fit in fits.items()
    }
    return select_replicated(plan, validation, "2026-11-03T00:00:00Z")


class TrainingReplication(unittest.TestCase):
    def setUp(self):
        self.plan, self.fits = fixture()
        self.selection = lock(self.plan, self.fits)

    def audit(self):
        return audit_replication(self.plan, self.fits, self.selection)

    def reseal(self):
        self.plan["design_digest"] = design_digest(self.fits["fit-0"]["protocol"])
        for fit in self.fits.values():
            fit["execution"]["protocol_digest"] = f.protocol_digest(fit["protocol"])
        self.selection = lock(self.plan, self.fits)

    def test_complete_matrix_is_arithmetic_not_verified_training(self):
        out = self.audit()
        self.assertEqual(
            (
                out["declared_training_fits"],
                out["episode_seeds_per_fit"],
                out["episode_count"],
            ),
            (4, 2, 10240),
        )
        self.assertEqual(len(out["contrasts"]), 20)
        self.assertAlmostEqual(out["contrasts"]["joint:D-B"]["estimate"], 0.29)
        self.assertFalse(out["independent_training_runs_verified"])
        self.assertFalse(out["adoption_authorized"])
        self.assertEqual(out["scientific_gates"], {"all": "HOLD"})

    def test_self_declared_real_cannot_authenticate_receipts(self):
        for fit in self.fits.values():
            fit["protocol"]["evidence_kind"] = "real"
        self.reseal()
        out = self.audit()
        self.assertEqual(out["native_receipt_verification"], "NOT_IMPLEMENTED")
        self.assertTrue(
            all(value["gate"] == "HOLD" for value in out["contrasts"].values())
        )
        self.assertFalse(out["multiplicity"]["finite_sample_coverage_guaranteed"])

    def test_missing_fit_or_episode_is_not_dropped(self):
        del self.fits["fit-3"]
        with self.assertRaisesRegex(f.InvalidEvidence, "incomplete declared fit"):
            self.audit()
        self.plan, self.fits = fixture()
        self.fits["fit-3"]["rows"].pop()
        with self.assertRaisesRegex(
            f.InvalidEvidence, "incomplete preregistered matrix"
        ):
            self.audit()

    def test_duplicate_training_receipt_seed_and_attempt_rejected(self):
        for field in ("receipt_digest", "run_id", "attempt_ids"):
            with self.subTest(field=field):
                fits = copy.deepcopy(self.fits)
                fits["fit-1"]["execution"][field] = fits["fit-0"]["execution"][field]
                with self.assertRaisesRegex(f.InvalidEvidence, "reused"):
                    audit_replication(self.plan, fits, self.selection)
        self.plan["fits"][1]["training_seed"] = self.plan["fits"][0]["training_seed"]
        with self.assertRaisesRegex(f.InvalidEvidence, "reused"):
            self.audit()

    def test_fit_identity_and_fit_specific_model_are_enforced(self):
        for field, value in (("fit_id", "fit-0"), ("model_digest", "f" * 64)):
            with self.subTest(field=field):
                fits = copy.deepcopy(self.fits)
                fits["fit-1"]["rows"][-1][field] = value
                with self.assertRaisesRegex(f.InvalidEvidence, "mismatch"):
                    audit_replication(self.plan, fits, self.selection)

    def test_cross_fit_episode_reuse_rejected(self):
        self.fits["fit-1"]["rows"][0]["run_id"] = self.fits["fit-0"]["rows"][0][
            "run_id"
        ]
        with self.assertRaisesRegex(f.InvalidEvidence, "across fits"):
            self.audit()

    def test_training_cannot_finish_after_evaluation(self):
        self.fits["fit-0"]["execution"]["finished_at"] = "2026-11-02T12:00:00Z"
        with self.assertRaisesRegex(f.InvalidEvidence, "finish before evaluation"):
            self.audit()

    def test_training_and_search_receipts_cannot_change_after_global_lock(self):
        for category, field in (
            ("training_actual", "train_compute"),
            ("research_costs", "search"),
        ):
            fits = copy.deepcopy(self.fits)
            fits["fit-0"]["protocol"]["profiles"]["joint:D"][category][field] += 1
            with self.assertRaisesRegex(f.InvalidEvidence, "replication lock differs"):
                audit_replication(self.plan, fits, self.selection)
        before = copy.deepcopy(self.selection)
        self.fits["fit-0"]["execution"]["started_at"] = "2026-11-01T02:00:00Z"
        self.assertEqual(self.selection, before)
        with self.assertRaisesRegex(f.InvalidEvidence, "replication lock differs"):
            self.audit()

    def test_unknown_costs_propagate_and_evaluation_costs_can_be_completed(self):
        profile = self.fits["fit-0"]["protocol"]["profiles"]["joint:D"]
        profile["research_costs"]["evaluation"] = None
        out = self.audit()
        self.assertIsNone(out["study_research_total"])
        self.assertTrue(out["unknowns"])
        profile["research_costs"]["evaluation"] = 100
        self.fits["fit-0"]["rows"][-1]["costs"]["sync"] = None
        out = self.audit()
        self.assertIsNone(
            out["inference_cost_ledger"]["all_observed_episodes"]["total"]
        )
        self.assertTrue(
            all(
                c["conditional_gate_on_verified_receipts"] == "HOLD"
                for c in out["contrasts"].values()
            )
        )

    def test_audit_report_is_detached_from_input_costs_and_selection(self):
        report = self.audit()
        frozen = copy.deepcopy(report)
        self.fits["fit-0"]["protocol"]["profiles"]["joint:D"]["research_costs"][
            "evaluation"
        ] = 123456
        self.fits["fit-0"]["rows"][-1]["costs"]["sync"] = None
        self.selection["fits"]["fit-0"]["choices"]["joint"]["complete"] = "A"
        self.assertEqual(report, frozen)

    def test_derived_cost_overflow_rejected_and_cli_replaces_stale_report(self):
        for scope in ("research", "deployment"):
            with self.subTest(scope=scope):
                self.plan, self.fits = fixture()
                for fit in self.fits.values():
                    if scope == "research":
                        for profile in fit["protocol"]["profiles"].values():
                            profile["research_costs"]["evaluation"] = 1e308
                    else:
                        # Each episode is finite and within budget; only the
                        # campaign ledger overflows. Zero cost weight keeps
                        # contrast arithmetic finite so this tests the ledger.
                        fit["protocol"]["cost_weight"] = 0
                        for profile in fit["protocol"]["profiles"].values():
                            profile["budget"]["episode_cost"] = 1e308
                        for row in fit["rows"]:
                            row["costs"] = {name: 1e306 for name in f.COSTS}
                self.reseal()
                with self.assertRaisesRegex(
                    f.InvalidEvidence, "nonfinite derived audit value"
                ):
                    self.audit()
                raw = json.dumps(
                    {"plan": self.plan, "fits": self.fits}, allow_nan=False
                ).encode()
                with tempfile.TemporaryDirectory() as directory:
                    source, selected, output = [
                        Path(directory) / name
                        for name in ("bundle.json", "selection.json", "report.json")
                    ]
                    source.write_bytes(raw)
                    selected.write_text(json.dumps(self.selection, allow_nan=False))
                    output.write_text('{"old_report": true}')
                    with patch(
                        "sys.argv",
                        [
                            "replication",
                            "--bundle",
                            str(source),
                            "--selection",
                            str(selected),
                            "--output",
                            str(output),
                        ],
                    ):
                        with self.assertRaises(SystemExit) as raised:
                            main()
                    self.assertEqual(raised.exception.code, 2)
                    result = json.loads(output.read_text())
                    self.assertIn("nonfinite derived audit value", result["error"])
                    self.assertNotIn("old_report", result)
                    self.assertEqual(
                        result["input_bundle"],
                        {
                            "path": str(source.resolve()),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw),
                        },
                    )
                    self.assertEqual(source.read_bytes(), raw)
                    self.assertFalse(result["matrix_complete"])
                    self.assertEqual(result["scientific_gates"], {"all": "HOLD"})

    def test_more_identical_episode_seeds_do_not_reduce_fit_uncertainty(self):
        first = self.audit()["contrasts"]["joint:D-B"]
        for fit in self.fits.values():
            fit["protocol"]["seeds"].append(99)
            for row in list(fit["rows"]):
                if row["seed"] == 11:
                    duplicate = copy.deepcopy(row)
                    duplicate.update(
                        seed=99,
                        run_id=row["run_id"] + "/seed99",
                        attempt_ids=[row["run_id"] + "/seed99/attempt"],
                    )
                    fit["rows"].append(duplicate)
        self.reseal()
        second = self.audit()["contrasts"]["joint:D-B"]
        np.testing.assert_allclose(first["ci"], second["ci"], atol=1e-14, rtol=0)
        self.assertGreater(first["ci"][1] - first["ci"][0], 0.1)
        self.assertEqual(second["declared_fits"], 4)

    def test_failed_training_attempts_and_budget_overruns_remain_evidence(self):
        fit = self.fits["fit-0"]
        fit["execution"]["attempt_ids"].append("fit-0/training/retry")
        fit["execution"]["failed_attempts"] = 1
        fit["protocol"]["profiles"]["joint:D"]["training_actual"]["train_compute"] = (
            1000
        )
        self.reseal()
        out = self.audit()
        self.assertEqual(out["failed_training_attempts"], 1)
        self.assertTrue(out["findings"])

    def test_power_has_training_variance_floor_and_bounded_execution(self):
        small = planning_power(self.plan["power"], 4, 20, 0.05)
        large = planning_power(self.plan["power"], 4, 1000000, 0.05)
        self.assertGreater(
            large["variance_of_mean"], self.plan["power"]["fit_variance"] / 4
        )
        self.assertLess(large["variance_of_mean"], small["variance_of_mean"])
        for fit in self.fits.values():
            fit["protocol"]["bootstrap_samples"] = 10**12
        self.plan["design_digest"] = design_digest(self.fits["fit-0"]["protocol"])
        for fit in self.fits.values():
            fit["execution"]["protocol_digest"] = f.protocol_digest(fit["protocol"])
        with self.assertRaisesRegex(f.InvalidEvidence, "bounded work profile"):
            self.audit()

    def test_failed_fit_cli_preserves_and_binds_the_original_cost_bundle(self):
        self.fits["fit-0"]["execution"]["failed_attempts"] = 1
        for fit in self.fits.values():
            fit["rows"] = [row for row in fit["rows"] if row["split"] == "validation"]
        raw = json.dumps({"plan": self.plan, "fits": self.fits}).encode()
        with tempfile.TemporaryDirectory() as directory:
            source, output = (
                Path(directory) / "bundle.json",
                Path(directory) / "error.json",
            )
            source.write_bytes(raw)
            with patch(
                "sys.argv",
                [
                    "replication",
                    "--bundle",
                    str(source),
                    "--select",
                    "--locked-at",
                    "2026-11-03T00:00:00Z",
                    "--output",
                    str(output),
                ],
            ):
                with self.assertRaises(SystemExit) as raised:
                    main()
            self.assertEqual(raised.exception.code, 2)
            result = json.loads(output.read_text())
            self.assertIn("no completed training attempt", result["error"])
            self.assertEqual(
                result["input_bundle"],
                {
                    "path": str(source.resolve()),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                },
            )
            self.assertEqual(source.read_bytes(), raw)
            self.assertFalse(result["matrix_complete"])
            alias = Path(directory) / "alias.json"
            alias.hardlink_to(source)
            with (
                patch(
                    "sys.argv",
                    [
                        "replication",
                        "--bundle",
                        str(source),
                        "--select",
                        "--output",
                        str(alias),
                    ],
                ),
                patch("sys.stderr"),
            ):
                with self.assertRaises(SystemExit):
                    main()
            self.assertEqual(source.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
