import json
from pathlib import Path
import tempfile
import unittest

from experiments.shared_stem_cell.preflight_review import ARMS, PreflightError, review
from experiments.shared_stem_cell.wire import canonical, sha

H = "a" * 64
R = "b" * 40


def make_study(root: Path):
    producer = root / "producer"
    producer.mkdir()
    data = []
    for i, split in enumerate(("train", "train", "calibration", "calibration",
                               "holdout", "holdout", "retention", "retention")):
        data.append({"case_id": f"case-{i}", "group": f"g-{i}", "split": split,
                     "observed_at": None, "cell": i % 2, "scope": "research",
                     "text": f"physical text {i}", "label": i % 2})
    raw = b"".join(canonical(x) for x in data)
    (root / "dataset.jsonl").write_bytes(raw)
    manifest = {"schema": "hepta.shared-stem-execution.v1", "classes": 2, "cells": 2,
                "dataset": {"path": "dataset.jsonl", "sha256": sha(raw)},
                "model": {"revision": R, "kind": "encoder", "files": {"model.safetensors": H}}}
    (root / "manifest.json").write_bytes(canonical(manifest))
    predicted = []
    scores = []
    for arm in ARMS:
        for row in data[4:]:
            label = row["label"]
            probs = [0.1, 0.9] if label == 1 else [0.9, 0.1]
            predicted.append({"case_id": row["case_id"], "group": row["group"],
                              "split": row["split"], "cell": row["cell"],
                              "input_digest": sha(canonical([row["scope"], row["text"]])),
                              "arm": arm, "probabilities": probs,
                              "frozen_probabilities": probs})
        for split in ("holdout", "retention"):
            scores.append({"arm": arm, "split": split, "cases": 2,
                           "accuracy": 1.0, "same_init_frozen_accuracy": 1.0,
                           "brier": 0.02, "independent_evaluation": False})
    (producer / "predictions.json").write_bytes(canonical({"predictions": predicted}))
    report = {"schema": "hepta.shared-stem-executed.v1", "mode": "local_pretrained",
              "production_accepted": False, "independent_evaluation": False,
              "source_sha256": H, "manifest_sha256": sha((root / "manifest.json").read_bytes()),
              "predictions_sha256": sha((producer / "predictions.json").read_bytes()),
              "encoding": {"simulated_encoder": False}, "scores": scores}
    (producer / "report.json").write_bytes(canonical(report))
    return producer


def checked(root):
    return review(root / "manifest.json", root / "producer",
                  sha((root / "producer" / "report.json").read_bytes()))


class PreflightReviewTests(unittest.TestCase):
    def test_exact_seal_recomputes_all_head_cases_but_never_promotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_study(root)
            r = checked(root)
            self.assertEqual(r["held_out_cases"], 4)
            self.assertEqual(len(r["scores_recomputed_from_sealed_predictions"]), 8)
            self.assertTrue(all(s["accuracy"] == 1 for s in r["scores_recomputed_from_sealed_predictions"]))
            self.assertFalse(r["ready_for_e1_e6_selection"])
            self.assertFalse(r["no_change_production_baseline_verified"])
            self.assertEqual(r["non_temporal_rows"], 8)

    def test_seal_drift_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_study(root)
            p = root / "producer" / "predictions.json"
            p.write_bytes(p.read_bytes() + b"\n")
            with self.assertRaisesRegex(PreflightError, "digest mismatch"):
                checked(root)

    def test_rehashed_false_score_does_not_bypass_arithmetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_study(root)
            p = root / "producer" / "report.json"
            x = json.loads(p.read_bytes())
            x["scores"][0]["accuracy"] = 0.0
            p.write_bytes(canonical(x))
            with self.assertRaisesRegex(PreflightError, "disagree"):
                checked(root)

    def test_rehashed_foreign_input_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_study(root)
            p = root / "producer" / "predictions.json"
            x = json.loads(p.read_bytes())
            x["predictions"][0]["input_digest"] = "c" * 64
            p.write_bytes(canonical(x))
            report_path = root / "producer" / "report.json"
            report = json.loads(report_path.read_bytes())
            report["predictions_sha256"] = sha(p.read_bytes())
            report_path.write_bytes(canonical(report))
            with self.assertRaisesRegex(PreflightError, "identity drift"):
                checked(root)

    def test_survivorship_cannot_drop_case_even_with_rehashed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_study(root)
            p = root / "producer" / "predictions.json"
            x = json.loads(p.read_bytes())
            x["predictions"].pop()
            p.write_bytes(canonical(x))
            report_path = root / "producer" / "report.json"
            report = json.loads(report_path.read_bytes())
            report["predictions_sha256"] = sha(p.read_bytes())
            report_path.write_bytes(canonical(report))
            with self.assertRaisesRegex(PreflightError, "incomplete physical"):
                checked(root)

    def test_simulated_or_unqualified_report_rejected(self):
        for key, bad in (("simulated_encoder", True), ("production_accepted", True)):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                make_study(root)
                path = root / "producer" / "report.json"
                report = json.loads(path.read_bytes())
                if key == "simulated_encoder":
                    report["encoding"][key] = bad
                else:
                    report[key] = bad
                path.write_bytes(canonical(report))
                with self.assertRaises(PreflightError):
                    checked(root)

    def test_dataset_content_change_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_study(root)
            (root / "dataset.jsonl").write_bytes(b"{}\n")
            with self.assertRaisesRegex(PreflightError, "digest mismatch"):
                checked(root)

    def test_symlinked_report_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_study(root)
            report = root / "producer" / "report.json"
            backup = root / "original-report.json"
            report.rename(backup)
            report.symlink_to(backup)
            with self.assertRaisesRegex(PreflightError, "symlinked"):
                checked(root)


if __name__ == "__main__":
    unittest.main()
