"""Numerical candidate behavior; these fixtures supply no evaluation authority."""

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import unittest

import numpy as np

from hepta_train_public_healthver import prediction_rows
from public_cpu_training import (
    Q24,
    candidate_manifest,
    component_cut,
    quantized_payload,
    train,
)


def samples():
    rows, features, labels = [], [], []
    for component in range(4):
        for label in (0, 1):
            for repeat in range(3):
                rows.append(
                    {
                        "component_digest": hashlib.sha256(
                            str(component).encode()
                        ).hexdigest()
                    }
                )
                feature = [0] * 512
                feature[0] = Q24 if label == 0 else -Q24
                feature[1] = Q24 // (repeat + 2)
                features.append(feature)
                labels.append(label)
    partitions = component_cut(rows, 24, 1)
    return rows, features, labels, partitions


def fit(features, labels, partitions):
    return train(
        features,
        labels,
        partitions,
        seed=20261002,
        epochs=100,
        learning_rate=0.01,
        deadline=time.monotonic() + 30,
    )


class PublicTrainingTests(unittest.TestCase):
    def test_component_split_does_not_depend_on_row_order_or_annotations(self):
        rows, _, _, partitions = samples()
        annotated = [
            row | {"gold": "changed", "entropy": 999} for row in reversed(rows)
        ]
        self.assertEqual(partitions, list(reversed(component_cut(annotated, 24, 1))))
        train_components = {
            row["component_digest"]
            for row, part in zip(rows, partitions, strict=True)
            if part == "train"
        }
        development = {
            row["component_digest"]
            for row, part in zip(rows, partitions, strict=True)
            if part == "development"
        }
        self.assertFalse(train_components & development)

    def test_development_labels_cannot_change_training_or_quantized_weights(self):
        _, features, labels, partitions = samples()
        parameters, history = fit(features, labels, partitions)
        changed = [
            1 - label if part == "development" else label
            for label, part in zip(labels, partitions, strict=True)
        ]
        alternate, other_history = fit(features, changed, partitions)
        self.assertEqual(quantized_payload(parameters), quantized_payload(alternate))
        self.assertEqual(history, other_history)
        self.assertLess(
            history["last_epoch_input_training_loss"],
            history["initial_training_loss"] / 4,
        )

    def test_payload_has_exact_native_dimensions_bounds_and_frozen_outputs(self):
        _, features, labels, partitions = samples()
        parameters, _ = fit(features, labels, partitions)
        payload = quantized_payload(parameters)
        self.assertEqual(
            (payload[:8], struct.unpack(">HHH", payload[8:14])),
            (b"HPTNCPU1", (512, 96, 10)),
        )
        self.assertEqual(len(payload), 14 + (96 * 513 + 2 * 10 * 97) * 8)
        coefficients = np.frombuffer(payload[14:], dtype=">i8")
        self.assertLessEqual(int(np.abs(coefficients).max()), 8 * Q24)
        heads = coefficients[96 * 513 :].reshape(2, 10, 97)
        np.testing.assert_array_equal(
            heads[:, 2:, :-1], np.zeros((2, 8, 96), dtype=np.int64)
        )
        np.testing.assert_array_equal(heads[:, 2:, -1], np.full((2, 8), -8 * Q24))

    def test_invalid_gradient_inputs_and_expired_budget_fail_before_artifact(self):
        _, features, labels, partitions = samples()
        with self.assertRaises(ValueError):
            fit(features, [0] * len(labels), partitions)
        with self.assertRaises(TimeoutError):
            train(
                features,
                labels,
                partitions,
                seed=24,
                epochs=100,
                learning_rate=0.01,
                deadline=time.monotonic() - 1,
            )
        parameters, _ = fit(features, labels, partitions)
        parameters[0][0, 0] = 8.01
        with self.assertRaises(ValueError):
            quantized_payload(parameters)

    def test_original_installed_numeric_program_executes_trained_nonconstant_heads(
        self,
    ):
        if not os.environ.get("HEPTA_PUBLIC_TRAIN_TEST_SCORER"):
            self.skipTest(
                "explicit immutable normal scorer source required for physical integration"
            )
        scorer = Path(os.environ["HEPTA_PUBLIC_TRAIN_TEST_SCORER"])
        template_path = Path(os.environ["HEPTA_PUBLIC_TRAIN_TEST_TEMPLATE"])
        self.assertEqual(
            hashlib.sha256(scorer.read_bytes()).hexdigest(),
            os.environ["HEPTA_PUBLIC_TRAIN_TEST_SCORER_SHA256"],
        )
        _, features, labels, partitions = samples()
        parameters, _ = fit(features, labels, partitions)
        payload = quantized_payload(parameters)
        manifest = candidate_manifest(
            json.loads(template_path.read_text()), payload, "fixture.public-trained"
        )
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name).resolve()
            (directory / "weights.bin").write_bytes(payload)
            raw = json.dumps(manifest, sort_keys=True).encode()
            path = directory / "manifest.json"
            path.write_bytes(raw)
            path.chmod(0o600)
            (directory / "weights.bin").chmod(0o600)
            inputs = b"".join(
                json.dumps(
                    {
                        "request_id": str(index),
                        "feature_vector_q24": feature,
                        "expected_output_width": 10,
                    }
                ).encode()
                + b"\n"
                for index, feature in enumerate(features)
            )
            observed = subprocess.run(
                [str(scorer), str(path), hashlib.sha256(raw).hexdigest()],
                input=inputs,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(observed.returncode, 0, observed.stderr.decode())
        predictions = prediction_rows(
            observed.stdout, {str(index) for index in range(len(labels))}, manifest
        )
        self.assertEqual(
            [predictions[str(index)] for index in range(len(labels))], labels
        )
        changed = json.loads(observed.stdout.splitlines()[0])
        changed["succeeded"] = False
        with self.assertRaises(ValueError):
            prediction_rows(json.dumps(changed).encode(), {"0"}, manifest)


if __name__ == "__main__":
    unittest.main()
