"""Source-only adversarial and true CPU Torch Head math (synthetic features)."""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stem_candidate_v1 as candidate
import stem_review_v1 as reviewer

ROOT = Path(__file__).parent


def _fixture():
    def csv_bytes(kind):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["text", "category"])
        for cat in candidate.INTENTS:
            for i in range(22):
                writer.writerow([f"{kind} {cat} phrase number {i}", cat])
        return stream.getvalue().encode()
    train = csv_bytes("train")
    test = csv_bytes("test")
    hashes = {"train": candidate.sha256(train), "test": candidate.sha256(test)}
    prepared = candidate.prepare_original(train, test, hashes=hashes)
    return train, test, hashes, prepared


def _run(prepared, mat, model, *, answer_class=0):
    scores = [1.0 if i == answer_class else 0.0 for i in range(4)]
    return {
        "schema": candidate.RUN_SCHEMA, "candidate": model,
        "source_plan_sha256": prepared["source_plan_sha256"],
        "material_manifest_sha256": candidate.sha256(candidate.canonical(mat)),
        "model_repo": mat["candidates"][model]["repo"],
        "model_revision": mat["candidates"][model]["revision"],
        "actual_weight_sha256": mat["candidates"][model]["weight_sha256"],
        "head_parameters": 27656, "optimizer_steps": 100,
        "initial_head_sha256": "a"*64, "trained_head_sha256": "b"*64,
        "rows": [{"case_id": r["case_id"], "source_sha256": r["source_sha256"],
                  "scores": {a: scores for a in ("learned", "frozen_init", "centroid")}}
                 for r in prepared["heldout"]],
        "cost": {"encoder_forward_batches": 6, "physical_encoder_sequences": 96,
                 "elapsed_wall_seconds": 2.0, "elapsed_cpu_seconds": 1.5,
                 "head_train_wall_seconds": 1.0, "model_download_load_wall_seconds": 0.2,
                 "feature_encode_wall_seconds": 0.2, "maxrss_bytes": 123000,
                 "energy_joules": None, "p99_latency_ms": None},
        "physical_claim_unattested": True, "future_windows_verified": 0,
        "real_4096_cell_training_verified": False,
        "production_authorized": False, "disposition": "HOLD_NO_GO",
    }


class StemOriginalSourceTests(unittest.TestCase):
    def setUp(self):
        self.train, self.test, self.hashes, self.prep = _fixture()
        self.mat = candidate.load_materials(ROOT / "MODEL_MATERIALS.json")
        self.runs = [_run(self.prep, self.mat, name) for name in candidate.MODEL_NAMES]

    def test_true_original_pub_bytes_required_by_public_entry(self):
        with self.assertRaisesRegex(ValueError, "publisher data bytes"):
            candidate.prepare_original(self.train, self.test)

    def test_blind_test_contains_no_target(self):
        self.assertEqual(len(self.prep["heldout"]), 32)
        self.assertTrue(all("label" not in x for x in self.prep["heldout"]))
        self.assertEqual(len({x["source_sha256"] for x in self.prep["train"] + self.prep["heldout"]}), 96)

    def test_publisher_tamper_rejected(self):
        with self.assertRaisesRegex(ValueError, "publisher data bytes"):
            candidate.prepare_original(self.train + b"\n", self.test, hashes=self.hashes)

    def test_conflicting_duplicate_fails(self):
        raw = self.train + b"train card_arrival phrase number 1,exchange_rate\r\n"
        with self.assertRaisesRegex(ValueError, "conflicting original labels"):
            candidate.prepare_original(raw, self.test, hashes={"train": candidate.sha256(raw), "test": self.hashes["test"]})

    def test_duplicate_or_leaked_heldout_field_rejected(self):
        # Producer verifier checks materialization protocol before any Encoder model download.
        v = copy.deepcopy(self.prep)
        v["publisher_sha256"] = dict(candidate.ORIGINAL_SHA)
        v["heldout"][0]["label"] = 0
        v["source_plan_sha256"] = candidate.sha256(candidate.canonical({k:x for k,x in v.items() if k != "source_plan_sha256"}))
        with self.assertRaisesRegex(ValueError, "heldout label"):
            candidate.verify_prepared(v)

    def test_same_model_original_source_reviewer(self):
        report = reviewer._review(self.train, self.test, self.prep, self.runs, self.mat, source_hashes=self.hashes)
        self.assertEqual(report["disposition"], "HOLD_NO_GO")
        self.assertFalse(report["publisher_original_sha_verified"])
        self.assertFalse(report["stem_winner_verified"])
        self.assertEqual(len(report["models"]), 3)

    def test_original_reviewer_does_not_accept_fixture_for_real_source(self):
        with self.assertRaisesRegex(ValueError, "source version changed"):
            reviewer.review_original(self.train, self.test, self.prep, self.runs, self.mat)

    def test_changed_source_in_reviewer_rejected(self):
        runs = copy.deepcopy(self.runs)
        runs[0]["source_plan_sha256"] = "d"*64
        with self.assertRaisesRegex(ValueError, "source/material substitution"):
            reviewer._review(self.train, self.test, self.prep, runs, self.mat, source_hashes=self.hashes)

    def test_changed_model_pinned_material_rejected(self):
        runs = copy.deepcopy(self.runs)
        runs[0]["actual_weight_sha256"] = "d"*64
        with self.assertRaisesRegex(ValueError, "false model material"):
            reviewer._review(self.train, self.test, self.prep, runs, self.mat, source_hashes=self.hashes)

    def test_label_leakage_in_predictions_fails(self):
        runs = copy.deepcopy(self.runs)
        runs[0]["rows"][0]["label"] = 0
        with self.assertRaisesRegex(ValueError, "unexpected producer case"):
            reviewer._review(self.train, self.test, self.prep, runs, self.mat, source_hashes=self.hashes)

    def test_missing_case_fails(self):
        runs = copy.deepcopy(self.runs)
        runs[1]["rows"] = runs[1]["rows"][:-1]
        with self.assertRaisesRegex(ValueError, "missing original predictions"):
            reviewer._review(self.train, self.test, self.prep, runs, self.mat, source_hashes=self.hashes)

    def test_head_budget_fraud_fails(self):
        runs = copy.deepcopy(self.runs)
        runs[1]["optimizer_steps"] = 50
        with self.assertRaisesRegex(ValueError, "nonidentical Head"):
            reviewer._review(self.train, self.test, self.prep, runs, self.mat, source_hashes=self.hashes)

    def test_nans_and_provenance_fraud_fail(self):
        for mutation in (lambda x: x["rows"][0]["scores"]["learned"].__setitem__(0, float("nan")),
                         lambda x: x.__setitem__("production_authorized", True),
                         lambda x: x["cost"].__setitem__("energy_joules", 1),
                         lambda x: x.__setitem__("future_windows_verified", 2)):
            runs = copy.deepcopy(self.runs)
            mutation(runs[0])
            with self.assertRaises(ValueError):
                reviewer._review(self.train, self.test, self.prep, runs, self.mat, source_hashes=self.hashes)

    def test_unresolved_candidate_or_completeness_fails(self):
        with self.assertRaisesRegex(ValueError, "all three physical jobs"):
            reviewer._review(self.train, self.test, self.prep, self.runs[:2], self.mat, source_hashes=self.hashes)

    def test_strong_baseline_no_false_superiority(self):
        report = reviewer._review(self.train, self.test, self.prep, self.runs, self.mat, source_hashes=self.hashes)
        self.assertTrue(all(x["paired"]["centroid"]["learned_only"] == 0 for x in report["models"].values()))
        self.assertFalse(report["host_cost_attestation"])
        self.assertEqual(report["source_independent_families"], 1)

    def test_mcnemar_correct_small_cases(self):
        self.assertEqual(reviewer._exact_mcnemar(0, 0), 1.0)
        self.assertEqual(reviewer._exact_mcnemar(0, 5), 0.0625)
        self.assertEqual(reviewer._exact_mcnemar(5, 5), 1.0)


class PhysicalSyntheticHeadTests(unittest.TestCase):
    def test_real_torch_gradient_and_head_receipt_on_synthetic_features(self):
        try:
            import torch
        except ImportError:
            self.skipTest("torch is required only for synthetic numerical test")
        torch.set_num_threads(2)
        t = torch.arange(64 * 384, dtype=torch.float32).reshape(64, 384)
        train = torch.nn.functional.normalize(torch.sin(t / 101), dim=-1)
        held = train[:32].clone()
        mat = candidate.load_materials(ROOT / "MODEL_MATERIALS.json")
        result = candidate._torch_head_training(train, [i % 4 for i in range(64)], held, config=mat["training"])
        self.assertEqual(result["total_head_parameters"], 4*6914)
        self.assertNotEqual(result["initial_head_sha256"], result["trained_head_sha256"])
        self.assertEqual(len(result["learned"]), 32)
        self.assertTrue(all(abs(sum(x)-1) < 1e-5 for x in result["learned"]))
        self.assertEqual(result["steps"], 100)
        self.assertNotEqual(result["learned"], result["frozen_init"])


if __name__ == "__main__":
    unittest.main()
