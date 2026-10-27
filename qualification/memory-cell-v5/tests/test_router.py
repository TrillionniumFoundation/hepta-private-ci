"""Mechanism checks, separate from any semantic performance claim."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.linear_model import LogisticRegression

from v5.contracts import LABELS, REJECT, normalized_request, write_json
from v5.config import NEGATIVE_TRAINING_FAMILIES
from v5.corpus import build_public_corpus
from v5.features import FeatureBlock
from v5.metrics import summarize
from v5.router import Router
from v5.training_guard import REQUIRED_TRAINING_SOURCES, verify_training_freeze


class RouterMechanismTests(unittest.TestCase):
    def test_public_folds_have_no_normalized_overlap_or_conflict(self):
        folds, audit = build_public_corpus()
        self.assertEqual(audit["normalized_cross_fold_duplicates"], 0)
        self.assertEqual(audit["normalized_cross_label_conflicts"], 0)
        self.assertEqual(set(folds), {"train", "selection", "development"})

    def test_request_contract_does_not_accept_targets(self):
        request = {
            "utterance": "Read Q at 2020-07, not the previous month.",
            "series_name": "Q",
            "date": "2020-07",
        }
        text = normalized_request(request)
        self.assertIn("not the previous month", text)
        self.assertNotIn("2020-07", text)
        with self.assertRaises(ValueError):
            normalized_request({**request, "intent": "at"})

    def test_real_fitted_model_round_trip_fresh_process_and_tamper_refusal(self):
        requests = [
            {
                "utterance": word + " monthly Q at 2020-07",
                "series_name": "Q",
                "date": "2020-07",
            }
            for word in (
                "current",
                "earlier",
                "subtract",
                "average",
                "range",
                "maximum",
                "forecast",
            )
        ]
        texts = [normalized_request(request) for request in requests]
        block, matrix = FeatureBlock.fit("word", texts)
        learned = LogisticRegression(C=10, solver="lbfgs").fit(matrix, list(LABELS))
        reorder = [list(learned.classes_).index(label) for label in LABELS]
        router = Router(
            [block],
            learned.coef_[reorder],
            learned.intercept_[reorder],
            {"minimum_confidence": 0.0, "minimum_margin": 0.0, "reject_all": False},
            {"learner": "logistic"},
            {"source": "synthetic-mechanism-only"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            receipt = router.save(path / "model")
            manifest_sha = receipt["files"]["manifest.json"]["sha256"]
            write_json(path / "requests.json", requests)
            subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve().parents[1] / "read_router.py"),
                    "--model",
                    str(path / "model"),
                    "--manifest-sha256",
                    manifest_sha,
                    "--requests",
                    str(path / "requests.json"),
                    "--output",
                    str(path / "read.json"),
                ],
                check=True,
            )
            report = json.loads((path / "read.json").read_bytes())
            self.assertEqual(report["decisions"], router.decisions(requests))
            self.assertEqual(
                report["parameter_digest_before"], report["parameter_digest_after"]
            )
            self.assertTrue(
                all(
                    item["bytes"] <= 480000
                    for name, item in receipt["files"].items()
                    if name != "manifest.json"
                )
            )
            part = next((path / "model").glob("weights.npz.part*"))
            raw = bytearray(part.read_bytes())
            raw[-1] ^= 1
            part.write_bytes(raw)
            with self.assertRaises(ValueError):
                Router.load(path / "model", manifest_sha)

    def test_coverage_requires_correct_acceptance(self):
        rows = [{"intent": intent, "family": intent} for intent in LABELS]
        decisions = [
            {
                "raw_label": LABELS[(i + 1) % 6],
                "accepted_intent": LABELS[(i + 1) % 6],
                "accepted": True,
            }
            for i in range(6)
        ]
        decisions.append(
            {"raw_label": REJECT, "accepted_intent": None, "accepted": False}
        )
        report = summarize(rows, decisions)
        self.assertEqual(report["known_accepted"], 6)
        self.assertEqual(report["known_correct_accepted"], 0)
        self.assertFalse(report["qualified"])

    def test_negative_subclass_mapping_and_saved_readout(self):
        requests = [
            {"utterance": "Read Q at 2020-07", "series_name": "Q", "date": "2020-07"}
        ]
        block, matrix = FeatureBlock.fit("word", [normalized_request(requests[0])])
        model_labels = (
            *LABELS[:6],
            *(REJECT + "::" + family for family in NEGATIVE_TRAINING_FAMILIES),
        )
        coefficients = np.zeros((len(model_labels), matrix.shape[1]), dtype=np.float64)
        intercept = np.zeros(len(model_labels), dtype=np.float64)
        intercept[-1] = 10.0
        router = Router(
            [block],
            coefficients,
            intercept,
            {"minimum_confidence": 0.0, "minimum_margin": 0.0, "reject_all": False},
            {"learner": "logistic", "negative_subclasses": True},
            {"source": "synthetic-mechanism-only"},
            model_labels,
        )
        with tempfile.TemporaryDirectory() as temporary:
            receipt = router.save(Path(temporary) / "model")
            restored = Router.load(
                Path(temporary) / "model", receipt["files"]["manifest.json"]["sha256"]
            )
            decision = restored.decisions(requests)[0]
            self.assertEqual(decision["model_label"], model_labels[-1])
            self.assertEqual(decision["raw_label"], REJECT)
            self.assertIsNone(decision["accepted_intent"])
            self.assertEqual(decision["linear_scores"][-1], 10.0)
            self.assertEqual(decision["model_linear_scores"], list(intercept))

    def test_formal_source_guard_requires_matching_commit_and_complete_coverage(self):
        source = "1" * 40
        complete = {
            "source_commit": source,
            "source_files": dict.fromkeys(REQUIRED_TRAINING_SOURCES, {}),
        }
        identity = {"bytes": 123, "sha256": "2" * 64}
        with patch("v5.joint_cases.verify_freeze", return_value=(complete, identity)):
            self.assertEqual(verify_training_freeze(source), (complete, identity))
            with self.assertRaises(ValueError):
                verify_training_freeze("3" * 40)
        incomplete = {**complete, "source_files": dict(complete["source_files"])}
        del incomplete["source_files"]["v5/router.py"]
        with patch("v5.joint_cases.verify_freeze", return_value=(incomplete, identity)):
            with self.assertRaises(ValueError):
                verify_training_freeze(source)
        with patch(
            "v5.joint_cases.verify_freeze",
            side_effect=FileNotFoundError("missing project FREEZE.json"),
        ):
            with self.assertRaises(FileNotFoundError):
                verify_training_freeze(source)


if __name__ == "__main__":
    unittest.main()
