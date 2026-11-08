"""Software conformance and rejection tests; fixtures are not model results."""

import ast
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from .official_vqa_accuracy import (
    LockedTextAccuracy,
    UPSTREAM_SHA256,
    _Dataset,
    score_terminal_pool,
    validate_terminal_predictions,
)


def original(answer, count):
    return {
        "image": "fixture",
        "answer_type": "other",
        "answers": [
            {"answer": answer if i < count else "different", "answer_confidence": "yes"}
            for i in range(10)
        ],
    }


def envelope():
    return {
        "schema": "hepta.terminal-vqa-predictions.v1",
        "status": "completed",
        "prediction_origin": "synthetic_boundary_fixture",
        "purpose": "development_diagnostic",
        "manifest_sha256": "a" * 64,
        "predictions": [{"id": "case", "answer": "two", "finished": True}],
    }


class TerminalBoundaryTests(unittest.TestCase):
    def test_confirmation_probe_rejected_and_failure_cost_receipt_preserved(self):
        from .probe_vqa_conformance import run

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = json.dumps(
                {"cases": [{"id": "case", "project_split": "confirmation"}]}
            ).encode()
            (root / "CANDIDATES.json").write_bytes(raw)
            with patch(
                __package__ + ".probe_vqa_conformance.admit_candidate_pool"
            ) as admission:
                with self.assertRaisesRegex(ValueError, "cannot use confirmation"):
                    run(
                        root,
                        root / "missing.py",
                        root / "output",
                        manifest_sha256=hashlib.sha256(raw).hexdigest(),
                        history_sha256="b" * 64,
                    )
                admission.assert_not_called()
            receipt = json.loads((root / "output/CONFORMANCE.json").read_bytes())
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["probes_completed"], 0)
            self.assertGreaterEqual(receipt["cpu_seconds"], 0)
            self.assertIn("official_vqa_accuracy.py", receipt["source_sha256"])

    def test_unfinished_extra_privileged_fields_and_roster_mismatch_rejected(self):
        good = envelope()
        self.assertEqual(
            validate_terminal_predictions(good, "a" * 64, ["case"]), {"case": "two"}
        )
        alternatives = []
        for key, value in (
            ("status", "running"),
            ("purpose", "confirmation"),
            ("prediction_origin", "unspecified"),
            ("manifest_sha256", "b" * 64),
            ("future_reward", 1),
        ):
            row = copy.deepcopy(good)
            row[key] = value
            alternatives.append(row)
        row = copy.deepcopy(good)
        row["predictions"][0]["finished"] = False
        alternatives.append(row)
        row = copy.deepcopy(good)
        row["predictions"].append(copy.deepcopy(row["predictions"][0]))
        alternatives.append(row)
        row = copy.deepcopy(good)
        row["predictions"][0]["reference"] = "gold"
        alternatives.append(row)
        for row in alternatives:
            with self.subTest(row=row), self.assertRaises(ValueError):
                validate_terminal_predictions(row, "a" * 64, ["case"])
        with self.assertRaises(ValueError):
            validate_terminal_predictions(good, "a" * 64, ["another"])

    def test_unfinished_predictions_rejected_before_reference_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = json.dumps(
                {"cases": [{"id": "case", "project_split": "development"}]}
            ).encode()
            (root / "CANDIDATES.json").write_bytes(raw)
            pin = hashlib.sha256(raw).hexdigest()
            row = envelope()
            row["manifest_sha256"] = pin
            row["status"] = "running"
            prediction = json.dumps(row).encode()
            (root / "predictions.json").write_bytes(prediction)
            with patch(
                __package__ + ".official_vqa_accuracy.admit_candidate_pool"
            ) as admission:
                with self.assertRaisesRegex(ValueError, "Only completed"):
                    score_terminal_pool(
                        root,
                        root / "predictions.json",
                        root / "missing.py",
                        expected_manifest_sha256=pin,
                        expected_history_sha256="b" * 64,
                        expected_predictions_sha256=hashlib.sha256(
                            prediction
                        ).hexdigest(),
                    )
                admission.assert_not_called()

    def test_different_source_bytes_rejected_before_code_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.py"
            path.write_text("raise RuntimeError('must never execute')\n")
            with self.assertRaisesRegex(ValueError, "fixed pin"):
                LockedTextAccuracy(path)


class OfficialSourceConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value = os.environ.get("HEPTA_OFFICIAL_VIZWIZ_SOURCE")
        if not value:
            raise unittest.SkipTest(
                "Private pinned official source required for upstream conformance"
            )
        cls.path = Path(value)
        cls.raw = cls.path.read_bytes()
        if hashlib.sha256(cls.raw).hexdigest() != UPSTREAM_SHA256:
            raise ValueError("Conformance source pin differs")

    def test_accuracy_prefix_matches_full_upstream_class(self):
        class CaptionSink:
            def __init__(self, *args):
                self.eval = {}

            def evaluate(self):
                pass

        tree = ast.parse(self.raw)
        original_class = next(
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "VQAEval"
        )
        namespace = {"re": re, "sys": sys, "COCOEvalCap": CaptionSink}
        exec(
            compile(
                ast.Module(body=[original_class], type_ignores=[]),
                "full-upstream-vqa-class",
                "exec",
            ),
            namespace,
        )
        references = {
            "number": original("2", 3),
            "comma": original("1000", 2),
            "article": original("cat", 1),
            "decimal": original("3.14", 4),
        }
        predictions = {
            "number": "\tThe TWO.\n",
            "comma": "1,000",
            "article": "a cat!",
            "decimal": "3.14",
        }
        whole = namespace["VQAEval"](
            _Dataset(copy.deepcopy(references)),
            _Dataset(
                {
                    key: {"image": key, "answer": value}
                    for key, value in predictions.items()
                }
            ),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            whole.evaluate()
        result = LockedTextAccuracy(self.path).score(references, predictions)
        self.assertEqual(result, {"accuracy": whole.accuracy, "per_case": whole.evalQA})
        self.assertEqual(
            result["per_case"],
            {"number": 90.0, "comma": 60.0, "article": 30.0, "decimal": 100.0},
        )

    def test_gold_is_not_silently_normalized_and_ten_answers_are_required(self):
        component = LockedTextAccuracy(self.path)
        # This official version normalizes predictions only. Preserve that asymmetry.
        refs = {"case": original("The TWO.", 10)}
        before = copy.deepcopy(refs)
        self.assertEqual(
            component.score(refs, {"case": "two"})["per_case"]["case"], 0.0
        )
        self.assertEqual(refs, before)
        refs["case"]["answers"].pop()
        with self.assertRaisesRegex(ValueError, "Ten original"):
            component.score(refs, {"case": "two"})
        with self.assertRaisesRegex(ValueError, "roster"):
            component.score(before, {"missing": "two"})


if __name__ == "__main__":
    unittest.main()
