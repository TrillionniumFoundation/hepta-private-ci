"""Synthetic conformance fixtures: never a model benchmark result."""
import json
from pathlib import Path
import tempfile
import unittest

import evaluate


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((Path(__file__).parent / "plan.template.json").read_text())
        self.plan["source_sha"] = "f8c9419df6ddeb36ff8b522a50219981fb8d9345"
        self.samples = []
        for split, count in (("train", 6), ("calibration", 40), ("test", 14), ("ood", 6), ("retention", 10)):
            for i in range(count):
                self.samples.append({"id": f"{split}-{i}", "group_id": f"episode:{split}:{i}", "split": split, "task": "triage", "language": "en" if i % 2 else "zh", "state": {"body": f"synthetic sample {split} {i}"}, "instructions": "Choose an option", "criteria": {"left": "A", "right": "B"}, "ood": split == "ood", "gold": "left" if i % 2 else "right"})
        self.preds = []
        for model in evaluate.REQUIRED_MODELS:
            for s in self.samples:
                if s["split"] == "train":
                    continue
                gold = s["gold"]
                prob = {"left": 0.1, "right": 0.9} if gold == "right" else {"left": 0.9, "right": 0.1}
                self.preds.append({"model": model, "id": s["id"], "status": "ok", "probabilities": prob})

    def test_full_synthetic_pipeline_stays_blocked(self):
        self.assertEqual(evaluate.validate_dataset(self.samples)["independent_groups"], len(self.samples))
        metrics = evaluate.evaluate_decisions(self.plan, self.samples, self.preds)
        self.assertEqual(set(metrics), set(evaluate.REQUIRED_MODELS))
        self.assertEqual(metrics["laya_english"]["test"]["accuracy"], 1.0)
        self.assertEqual(metrics["arctic"]["test"]["macro_recall"], 1.0)
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp) / "data.jsonl"
            dataset.write_text("\n".join(map(json.dumps, self.samples)) + "\n")
            blockers = evaluate.evidence_gaps(self.plan, dataset, {}, [], [])
        self.assertIn("INDEPENDENT_NATIVE_AND_STATISTICAL_ACCEPTANCE_REQUIRED", blockers)
        self.assertIn("TARGET_HOST_RESOURCE_MISSING:arctic:4096", blockers)
        self.assertIn("MODEL_REVISION_UNPINNED:harrier", blockers)

    def test_leakage_blocks(self):
        self.samples[1]["group_id"] = self.samples[12]["group_id"]
        self.samples[1]["split"] = "test"
        with self.assertRaises(evaluate.EvidenceError):
            evaluate.validate_dataset(self.samples)

    def test_bad_probability_blocks(self):
        self.preds[0]["probabilities"] = {"left": 0.7, "right": 0.5}
        with self.assertRaisesRegex(evaluate.EvidenceError, "not normalized"):
            evaluate.evaluate_decisions(self.plan, self.samples, self.preds)

    def test_missing_model_rows_blocks(self):
        with self.assertRaisesRegex(evaluate.EvidenceError, "missing predictions"):
            evaluate.evaluate_decisions(self.plan, self.samples, self.preds[:-1])

    def test_abstain_produces_no_fake_distribution(self):
        self.preds[0]["status"] = "abstain"
        with self.assertRaisesRegex(evaluate.EvidenceError, "must not fabricate"):
            evaluate.evaluate_decisions(self.plan, self.samples, self.preds)

    def test_calibration_does_not_use_test_labels(self):
        t = evaluate.fit_temperature([({"left": 0.7, "right": 0.3}, "left")] * 30)
        self.assertTrue(0.5 <= t <= 5.0)
        self.assertEqual(evaluate.scale({"left": 0.7, "right": 0.3}, 1.0)["left"], 0.7)

    def test_cli_retains_incomplete_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "data.jsonl").write_text("\n".join(json.dumps(r) for r in self.samples) + "\n")
            (d / "plan.json").write_text(json.dumps(self.plan))
            (d / "predictions.jsonl").write_text("\n".join(json.dumps(r) for r in self.preds) + "\n")
            status = evaluate.main(["--plan", str(d / "plan.json"), "--dataset", str(d / "data.jsonl"), "--predictions", str(d / "predictions.jsonl"), "--output", str(d / "report.json")])
            self.assertEqual(status, 3)
            result = json.loads((d / "report.json").read_text())
            self.assertEqual(result["status"], "BLOCKED")
            self.assertNotEqual(result["model_scores"]["laya_typed"]["test"]["accuracy"], 0)


if __name__ == "__main__":
    unittest.main()