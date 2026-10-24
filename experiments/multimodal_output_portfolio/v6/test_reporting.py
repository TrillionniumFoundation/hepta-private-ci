"""Adversarial evidence checks, independent of model/critic implementation."""

from copy import deepcopy
import hashlib
import itertools
from pathlib import Path
import tempfile
import unittest

from .reporting import POLICIES, TRAININGS, WEIGHTS, canonical_sha256, owner_tsv
from .reporting import summarize, upper_tail90


def seal(row):
    row["receipt_sha256"] = canonical_sha256({key: value for key, value in row.items()
                                            if key != "receipt_sha256"})
    return row


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        text_path, image_path = root / "caption.txt", root / "image.png"
        text_path.write_text("left 1 right 2 relation less", encoding="utf-8")
        # Hash/transport fixture only; perceptual/codec tests belong to observer.
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nraw-hash-fixture")
        paths = {"text": str(text_path), "image": str(image_path)}
        hashes = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                  for name, path in paths.items()}
        metric = {"weights": dict(WEIGHTS), "utility": "1 - 2 * joint_loss"}
        self.protocol = {
            "seeds": [17, 29], "trainings": list(TRAININGS), "policies": list(POLICIES),
            "budgets": [10], "metric": metric, "metric_sha256": canonical_sha256(metric),
            "cases": {split: [{"case_id": f"{split}:case", "source_ids": [f"{split}:left", f"{split}:right"],
                                "corruption": "occlusion"}] for split in ("future", "retention")},
        }
        self.rows = []
        for seed, training, policy, split in itertools.product([17, 29], TRAININGS, POLICIES, ("future", "retention")):
            loss = .1 if policy == "risk_aware_recursive" else .2
            if seed == 29 and policy == "risk_aware_recursive":
                loss = .4  # An adverse seed must survive every rollup.
            metrics = {name: loss for name in WEIGHTS}
            metrics.update(joint_loss=loss, utility=1 - 2 * loss, caption_valid=True)
            case = self.protocol["cases"][split][0]
            self.rows.append(seal({
                "seed": seed, "training": training, "policy": policy, "split": split,
                "case_id": case["case_id"], "budget": 10, "source_ids": case["source_ids"],
                "corruption": "occlusion", "metrics": metrics,
                "cost": {"wall_ns": 1000, "cpu_ns": 1200, "encode_ns": 100,
                         "controller_ns": 200, "execute_ns": 200, "decode_ns": 100,
                         "observer_ns": 100, "modeled_work": 5.25, "search_units": 2., "execution_units": 2.},
                "actions": ["refine_image", "stop"], "snapshot_sha256": canonical_sha256([seed, training]),
                "forecast_sha256": canonical_sha256([seed, training, "forecast"]),
                "output_hashes": hashes, "output_paths": paths,
            }))

    def test_fractional_tail_keeps_the_boundary_mass(self):
        self.assertAlmostEqual(upper_tail90([1., .9] + [.1] * 9), (1 + .1 * .9) / 1.1)
        self.assertEqual(upper_tail90([.1, .4, .2]), .4)
        with self.assertRaises(ValueError):
            upper_tail90([float("nan")])

    def test_full_census_preserves_adverse_seed_and_correlated_sample_counts(self):
        result = summarize(self.rows, self.protocol)
        self.assertEqual(result["rows"], 56)
        self.assertEqual(result["independent_training_seeds"], 2)
        self.assertEqual(result["original_source_cases"], 2)
        adverse = result["factorial"][0]["per_seed"][1]["contrasts"]["mean_loss"]["inference_at_ndu"]
        self.assertAlmostEqual(adverse, .2)
        contrast = result["strong_paired_contrasts"][0]
        self.assertAlmostEqual(contrast["mean_paired_loss_difference"], .05)
        self.assertEqual(contrast["independent_source_cases"], 1)
        self.assertEqual(contrast["conditional_hoeffding_interval_95"], [-1., 1.])

    def test_missing_or_duplicated_arm_is_rejected(self):
        for rows in (self.rows[:-1], self.rows + [self.rows[0]]):
            with self.assertRaises(ValueError):
                summarize(rows, self.protocol)

    def test_adverse_corruption_is_visible_separately_from_the_mean(self):
        protocol, rows = deepcopy(self.protocol), deepcopy(self.rows)
        case = {"case_id": "future:wrong-hint", "source_ids": ["new:left", "new:right"],
                "corruption": "wrong_hint"}
        protocol["cases"]["future"].append(case)
        for row in list(rows):
            if row["split"] == "future":
                adverse = deepcopy(row)
                adverse.update(case)
                adverse["metrics"] = {**{name: 1. for name in WEIGHTS},
                                      "joint_loss": 1., "utility": -1., "caption_valid": False}
                rows.append(seal(adverse))
        result = summarize(rows, protocol)
        strata = [item for item in result["corruption_aggregates"] if item["corruption"] == "wrong_hint"]
        self.assertEqual(len(strata), 14)
        self.assertTrue(all(item["seed_mean"]["mean_loss"] == 1. for item in strata))
        self.assertTrue(all(item["independent_source_cases"] == 1 for item in strata))

    def test_relabelled_pixel_identity_cannot_cross_source_cases(self):
        protocol = deepcopy(self.protocol)
        digest = "a" * 64
        protocol["cases"]["future"][0]["source_ids"][0] = f"mnist:train:1:{digest}"
        protocol["cases"]["retention"][0]["source_ids"][0] = f"mnist:test:99:{digest}"
        with self.assertRaisesRegex(ValueError, "Original source reused"):
            summarize(self.rows, protocol)

    def test_distinct_frozen_observer_artifacts_are_required_when_declared(self):
        protocol = {**self.protocol, "require_distinct_observers": True}
        with self.assertRaises(ValueError):
            summarize(self.rows, protocol)
        rows = deepcopy(self.rows)
        for row in rows:
            row.update(observer_sha256="c" * 64, reward_observer_sha256="d" * 64)
            seal(row)
        summary = summarize(rows, protocol)
        self.assertEqual(summary["observer_binding"], {
            "artifact_identities_supplied": True, "external_observer_authenticated": False,
            "audit_artifact_sha256": "c" * 64, "reward_artifact_sha256": "d" * 64,
            "distinct_artifact_identities": True,
        })
        rows[-1]["observer_sha256"] = "e" * 64
        seal(rows[-1])
        with self.assertRaisesRegex(ValueError, "Observer artifacts changed"):
            summarize(rows, protocol)
        rows[-1]["observer_sha256"] = "d" * 64
        seal(rows[-1])
        with self.assertRaisesRegex(ValueError, "must differ"):
            summarize(rows, protocol)

    def test_receipt_model_and_metric_changes_are_rejected(self):
        mutations = (("snapshot_sha256", "b" * 64), ("source_ids", ["wrong:left", "wrong:right"]))
        for key, value in mutations:
            rows = deepcopy(self.rows)
            rows[-1][key] = value
            seal(rows[-1])
            with self.assertRaises(ValueError):
                summarize(rows, self.protocol)
        rows = deepcopy(self.rows)
        rows[0]["metrics"]["joint_loss"] = .9
        seal(rows[0])
        with self.assertRaisesRegex(ValueError, "metric or utility"):
            summarize(rows, self.protocol)

    def test_changed_original_bytes_and_hidden_work_are_rejected(self):
        rows = deepcopy(self.rows)
        rows[0]["cost"]["modeled_work"] = 1.
        seal(rows[0])
        with self.assertRaisesRegex(ValueError, "work omitted"):
            summarize(rows, self.protocol)
        Path(self.rows[0]["output_paths"]["text"]).write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Original output bytes"):
            summarize(self.rows, self.protocol)

    def test_missing_malformed_or_changed_forecast_identity_is_rejected(self):
        for mode in ("missing", "malformed", "changed"):
            rows = deepcopy(self.rows)
            if mode == "missing":
                del rows[-1]["forecast_sha256"]
            else:
                rows[-1]["forecast_sha256"] = "not-a-digest" if mode == "malformed" else "b" * 64
            seal(rows[-1])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                summarize(rows, self.protocol)

    def test_native_export_keeps_risk_unknown_conservative_and_cost_separate(self):
        rows = [row for row in self.rows if row["seed"] == 17 and row["training"] == "supervised" and row["split"] == "future"]
        export = owner_tsv(rows, "a" * 64, "b" * 64, self.protocol["metric_sha256"], 10, 10000)
        lines = export["tsv"].splitlines()
        self.assertEqual(len(lines), 10)
        self.assertEqual(len(lines[1].split("\t")), 11)
        self.assertEqual(hashlib.sha256(lines[1].encode()).hexdigest(), export["scope_sha256"])
        for line in lines[3:]:
            fields = line.split("\t")
            self.assertEqual(len(fields), 10)
            self.assertEqual(fields[5:8], [str(1 << 32), "6", "1000"])
        with self.assertRaisesRegex(ValueError, "one episode and snapshot"):
            owner_tsv(self.rows, "a" * 64, "b" * 64, self.protocol["metric_sha256"], 10, 10000)


if __name__ == "__main__":
    unittest.main()
