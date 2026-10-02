"""Causal joins and physical completeness, not evaluation authorization."""

import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from public_cpu_training import quantized_payload, train
from public_cpu_training_execution import score
from public_cpu_training_supply import PHYSICAL, join
from public_healthver_supply_tests import fixture
from hepta_prepare_public_healthver_supply import prepare_supply


def inputs():
    approved, graph, membership, cut, original = fixture()
    supply = prepare_supply(approved, graph, membership, cut, original)
    physical = []
    for row in supply["membership"]:
        physical.append(
            {
                "schema": "hepta.fixed-nomic-public-development-pair.v1",
                "purpose": "PublicDevelopmentMeasurementOnlyV1",
                "batch_id": "fixture-batch",
                "pair_id": row["pair_id"],
                "source_row_sha256": row["feature_digest"],
                "features_q24": [1] * 512,
            }
            | PHYSICAL
        )
    batch = {
        "purpose": "PublicDevelopmentMeasurementOnlyV1",
        "batch_id": "fixture-batch",
        "holdout_consumed": False,
        "learning_evidence_signed": False,
        "production_activation": False,
        "measurements": physical,
    }
    return supply["membership"], graph, cut, [batch]


class SupplyTrainingTests(unittest.TestCase):
    def test_timeout_or_failure_preserves_original_output_without_success(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            with self.assertRaises(subprocess.TimeoutExpired):
                score(
                    [
                        sys.executable,
                        "-I",
                        "-B",
                        "-S",
                        "-c",
                        "import time; print('original partial',flush=True); time.sleep(2)",
                    ],
                    b"",
                    time.monotonic() + 0.2,
                    directory,
                    "partial.stdout",
                    "partial.stderr",
                )
            self.assertEqual(
                (directory / "partial.stdout").read_bytes(), b"original partial\n"
            )
            with self.assertRaises(RuntimeError):
                score(
                    [
                        sys.executable,
                        "-I",
                        "-B",
                        "-S",
                        "-c",
                        "import sys; print('original refusal',file=sys.stderr); sys.exit(7)",
                    ],
                    b"",
                    time.monotonic() + 2,
                    directory,
                    "refused.stdout",
                    "refused.stderr",
                )
            self.assertEqual(
                (directory / "refused.stderr").read_bytes(), b"original refusal\n"
            )

    def test_expired_original_budget_cannot_spawn_or_emit_numeric_output(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            with self.assertRaises(TimeoutError):
                score(
                    ["/no-program-spawned"],
                    b"",
                    time.monotonic() - 1,
                    directory,
                    "stdout",
                    "stderr",
                )
            self.assertEqual(list(directory.iterdir()), [])

    def test_prior_development_never_becomes_training_in_extension(self):
        membership, graph, old, batches = inputs()
        rows, partitions = join(membership, graph, old, batches)
        now = {row["pair_id"]: part for row, part in zip(rows, partitions, strict=True)}
        for row in old:
            self.assertEqual(now[row["pair_id"]], row["partition"])
        development = {
            row["component_digest"] for row in old if row["partition"] == "development"
        }
        self.assertTrue(
            all(
                part == "development"
                for row, part in zip(rows, partitions, strict=True)
                if row["component_digest"] in development
            )
        )
        altered = copy.deepcopy(membership)
        altered[
            next(
                index
                for index, row in enumerate(altered)
                if row["pair_id"] == old[0]["pair_id"]
            )
        ]["partition"] = "development"
        with self.assertRaises(ValueError):
            join(altered, graph, old, batches)

    def test_missing_duplicate_wrong_model_or_wrong_source_measurements_are_closed(
        self,
    ):
        membership, graph, old, batches = inputs()
        cases = []
        missing = copy.deepcopy(batches)
        missing[0]["measurements"].pop()
        cases.append(missing)
        duplicate = copy.deepcopy(batches)
        duplicate[0]["measurements"].append(duplicate[0]["measurements"][0])
        cases.append(duplicate)
        for field in ("weights_sha256", "source_row_sha256", "encoder_manifest_sha256"):
            altered = copy.deepcopy(batches)
            altered[0]["measurements"][0][field] = "0" * 64
            cases.append(altered)
        fake = copy.deepcopy(batches)
        fake[0]["learning_evidence_signed"] = True
        cases.append(fake)
        for case in cases:
            with self.assertRaises(ValueError):
                join(membership, graph, old, case)

    def test_actual_features_and_cut_are_independent_of_public_annotation_changes(self):
        membership, graph, old, batches = inputs()
        before = join(membership, graph, old, batches)
        changed = copy.deepcopy(batches)
        for row in changed[0]["measurements"]:
            row["public_diagnostic_label"] = "changed"
        self.assertEqual(before, join(membership, graph, old, changed))

    def test_extended_row_capacity_is_explicit_and_development_labels_cannot_train(
        self,
    ):
        features, labels, parts = [], [], []
        for index in range(698):
            feature = [0] * 512
            feature[0] = (1 << 24) if index % 2 == 0 else -(1 << 24)
            features.append(feature)
            labels.append(index % 2)
            parts.append("development" if index < 128 else "train")
        options = {
            "seed": 24,
            "epochs": 2,
            "learning_rate": 0.01,
            "deadline": time.monotonic() + 30,
        }
        with self.assertRaises(ValueError):
            train(features, labels, parts, **options)
        parameters, history = train(
            features, labels, parts, maximum_rows=698, **options
        )
        changed = [
            1 - label if part == "development" else label
            for label, part in zip(labels, parts, strict=True)
        ]
        other, alternate = train(features, changed, parts, maximum_rows=698, **options)
        self.assertEqual(quantized_payload(parameters), quantized_payload(other))
        self.assertEqual(history, alternate)


if __name__ == "__main__":
    unittest.main()
