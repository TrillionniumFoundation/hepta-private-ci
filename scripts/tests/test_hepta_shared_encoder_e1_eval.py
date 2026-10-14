"""Offline fixture tests. These are not real Encoder learning evidence."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "hepta-shared-encoder-e1-eval.py"
SPEC = importlib.util.spec_from_file_location("shared_encoder_e1", SOURCE)
assert SPEC and SPEC.loader
LIB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIB)


def packet(split, case, probability, *, committed="2026-10-15T09:00:00Z"):
    return {
        "case_id": case, "scope_id": "s", "task_id": "t",
        "split": split, "probability_positive": probability,
        "prediction_committed_at": committed, "abstain": False,
        "encoder_digest": "a" * 64, "head_digest": "b" * 64,
        "weights_digest": "c" * 64, "model_revision": "d" * 40,
        "runtime_generation": 1, "execution_receipt_id": "unverified:fixture",
        "latency_micros": 12, "resident_bytes": 4096, "transient_bytes": 128,
    }


def fixtures():
    dataset = [
        {
            "case_id": f"c{i}", "scope_id": "s", "task_id": "t",
            "split": "future" if i < 4 else ("old" if i == 4 else "ood"),
            "event_time": "2026-10-15T08:00:00Z",
            "label_available_at": "2026-10-15T10:00:00Z",
            "group_id": f"g{i}", "label": i % 2,
        }
        for i in range(6)
    ]
    baseline = [packet(r["split"], r["case_id"], .5) for r in dataset]
    candidate = [
        packet(r["split"], r["case_id"], .1 if r["label"] == 0 else .9)
        for r in dataset
    ]
    return dataset, baseline, candidate


class PairedTests(unittest.TestCase):
    def run_compare(self, dataset, baseline, candidate):
        return LIB.compare(
            dataset, baseline, candidate, scope="s", task="t",
            cutoff="2026-10-14T00:00:00Z", rounds=100,
        )

    def test_deterministic_benefit_never_promotes(self):
        dataset, baseline, candidate = fixtures()
        report = self.run_compare(dataset, baseline, candidate)
        self.assertGreater(report["future_paired"]["paired_brier_improvement"], 0)
        self.assertGreater(report["future_paired"]["bootstrap_ci_lower"], 0)
        self.assertFalse(report["production_promotion_permitted"])
        self.assertFalse(report["independent_ndu_verified"])
        self.assertEqual(report["status"], "RETROSPECTIVE_SHADOW_EVIDENCE_INCOMPLETE")
        self.assertEqual(report, self.run_compare(dataset, baseline, candidate))

    def test_duplicate_missing_extra_cases_fail_closed(self):
        dataset, baseline, candidate = fixtures()
        for bad in (
            candidate[:-1], candidate + [candidate[0]],
            candidate + [packet("future", "extra", .5)],
        ):
            with self.subTest(count=len(bad)), self.assertRaises(ValueError):
                self.run_compare(dataset, baseline, bad)

    def test_prediction_after_label_or_before_event_rejected(self):
        dataset, baseline, candidate = fixtures()
        candidate[0]["prediction_committed_at"] = "2026-10-16T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "label"):
            self.run_compare(dataset, baseline, candidate)
        candidate[0]["prediction_committed_at"] = "2026-10-14T20:00:00Z"
        with self.assertRaises(ValueError):
            self.run_compare(dataset, baseline, candidate)

    def test_invalid_probability_revision_receipt_resources_rejected(self):
        dataset, baseline, candidate = fixtures()
        for key, value in (
            ("probability_positive", float("nan")),
            ("model_revision", "main"),
            ("execution_receipt_id", ""),
            ("resident_bytes", -1),
            ("abstain", True),
        ):
            row = candidate[1].copy()
            row[key] = value
            changed = candidate.copy()
            changed[1] = row
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_compare(dataset, baseline, changed)

    def test_training_group_leak_and_split_drift_rejected(self):
        dataset, baseline, candidate = fixtures()
        train = dict(
            dataset[0], case_id="train-duplicate", split="train",
            event_time="2026-10-13T00:00:00Z",
            label_available_at="2026-10-13T01:00:00Z",
        )
        with self.assertRaisesRegex(ValueError, "group contamination"):
            self.run_compare(dataset + [train], baseline, candidate)
        dataset[0]["split"] = "calibration"
        with self.assertRaises(ValueError):
            self.run_compare(dataset, baseline, candidate)

    def test_pre_cutoff_label_and_calibration_group_leak_rejected(self):
        dataset, baseline, candidate = fixtures()
        late_train = dict(
            dataset[0], case_id="training-future-label", split="train",
            group_id="train-group", event_time="2026-10-13T00:00:00Z",
            label_available_at="2026-10-15T00:00:00Z",
        )
        with self.assertRaisesRegex(ValueError, "label leaked"):
            self.run_compare(dataset + [late_train], baseline, candidate)
        calibration = dict(
            dataset[0], case_id="calibration-overlap", split="calibration",
            event_time="2026-10-13T00:00:00Z",
            label_available_at="2026-10-13T01:00:00Z",
        )
        with self.assertRaisesRegex(ValueError, "cross-split group"):
            self.run_compare(dataset + [calibration], baseline, candidate)

    def test_refuses_overwrite_and_duplicate_json_keys(self):
        dataset, baseline, candidate = fixtures()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, rows in (
                ("dataset", dataset), ("baseline", baseline), ("candidate", candidate)
            ):
                (root / f"{name}.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in rows),
                    encoding="utf-8",
                )
            arguments = [
                "--dataset", str(root / "dataset.jsonl"),
                "--no-change", str(root / "baseline.jsonl"),
                "--candidate", str(root / "candidate.jsonl"),
                "--scope", "s", "--task", "t", "--train-cutoff", "2026-10-14T00:00:00Z",
                "--bootstrap-rounds", "100", "--out", str(root / "report.json"),
            ]
            self.assertEqual(LIB.main(arguments), 0)
            self.assertEqual(LIB.main(arguments), 2)
            bad_json = root / "duplicate.jsonl"
            bad_json.write_text('{"case_id":"c1","case_id":"c2"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                LIB.read_jsonl(bad_json)


if __name__ == "__main__":
    unittest.main()
