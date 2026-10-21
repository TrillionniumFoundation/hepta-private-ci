"""Mechanism-only E1–E5 tests: synthetic input is NEVER real model/NDU evidence."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import sys

import torch
from e1_e5_trial import BUDGETS, MODELS, InputError, ResidualCellHead, trial, load_inputs
from e1_e5_review import ReviewError, evaluate, read, score_reader, score_media, score_resources, grouped_lower_bound


def d(x):
    return hashlib.sha256(x.encode()).hexdigest()


def dump(path, obj):
    raw = (json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def sample(root):
    cases, features, labels, baseline, targets = [], [], [], [], []
    for ix, phase in enumerate(("train", "calibration", "test", "future1", "future2", "future3", "ood")):
        for j in range(2 if phase != "train" else 8):
            cid = f"{phase}-{j}"
            case = {"case_id": cid, "group_id": f"group-{cid}", "split": phase,
                    "observed_at": (ix + 1) * 100 + j, "cell_id": "diagnostics",
                    "scope": "approved-scope", "generation": 1,
                    "language": ("en", "zh", "code")[j % 3], "modality": "text",
                    "input_sha256": d("input-" + cid), "state": [0.05] * 64}
            cases.append(case)
            y = j % 2
            if phase == "train":
                labels.append({"case_id": cid, "label": y})
            else:
                targets.append({"case_id": cid, "label": y,
                                "input_sha256": case["input_sha256"],
                                "outcome_owner_receipt_sha256": d("self-declared-receipt-" + cid)})
            baseline.append({"case_id": cid, "input_sha256": case["input_sha256"],
                             "probabilities": [0.5, 0.5], "nochange_source_sha256": d("external-nochange")})
            for mid, (dim, pool, source) in MODELS.items():
                a = [0.0] * dim
                a[(j + ix * 3) % dim] = 0.6
                a[(j + 5) % dim] = 0.4
                q = [0.0] * dim
                e = [0.0] * dim
                q[0] = 1.0
                e[0 if y else 1] = 1.0
                features.append({"case_id": cid, "model_id": mid,
                                 "input_sha256": case["input_sha256"], "vector": a,
                                 "query_vector": q, "evidence_vector": e,
                                 "revision": "1" * 40, "weights_sha256": d(mid + "-weights"),
                                 "producer_receipt_sha256": d(mid + "-forward-claim")})
    source = {"cases": cases, "features": features, "train_labels": labels, "nochange": baseline}
    files = {}
    for name, rows in source.items():
        filename = name + ".json"
        files[name] = {"path": filename, "sha256": dump(root / filename, rows)}
    config = {"schema": "hepta.stem-e1-e5.trial.v1", "steps": 5, "seed": 23,
              "head_budgets": list(BUDGETS), "files": files, "models": {
                  k: {"source": src, "revision": "1" * 40, "weights_sha256": d(k + "-weights"),
                      "preprocessor_sha256": d(k + "-preprocessor"), "pooling": pool,
                      "width": dim, "external_forward_receipt_sha256": d(k + "-forward-claim"),
                      "actual_pretrained_forward_claimed": True}
                  for k, (dim, pool, src) in MODELS.items()}}
    ph = dump(root / "plan.json", config)
    th = dump(root / "targets.json", targets)
    return config, ph, th


class E1E5ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg, self.plan_hash, self.targets_hash = sample(self.root)

    def revise(self, file, rows):
        self.cfg["files"][file]["sha256"] = dump(self.root / self.cfg["files"][file]["path"], rows)
        self.plan_hash = dump(self.root / "plan.json", self.cfg)

    def run_trial(self):
        path = self.root / "predictions.json"
        return trial(self.root / "plan.json", self.plan_hash, path)

    def run_review(self, pred_sha, **opts):
        return evaluate(self.root / "plan.json", self.plan_hash,
                        self.root / "predictions.json", pred_sha,
                        self.root / "targets.json", self.targets_hash,
                        self.root / "review.json", **opts)

    def test_real_torch_training_runs_all_budgets_and_controls(self):
        pred_sha = self.run_trial()
        record = read(self.root / "predictions.json", pred_sha)
        self.assertEqual(len(record["head_receipts"]), 18)
        self.assertEqual(len(record["results"]), 12 * 18)
        self.assertFalse(record["production_promotion_permitted"])
        for receipt in record["head_receipts"]:
            self.assertLessEqual(receipt["trainable_parameters"], receipt["budget"])
            self.assertEqual(receipt["updates"], self.cfg["steps"])
            self.assertNotEqual(receipt["frozen"]["sha256"], receipt["learned"]["sha256"])
        for rec in record["results"]:
            if rec["arm"].endswith("anchored"):
                for a, b in zip(rec["frozen_probabilities"], rec["nochange_probabilities"]):
                    self.assertAlmostEqual(a, b, places=6)
        self.assertEqual(record["feature_forward_in_this_runner"], 0)

    def test_independent_review_does_not_certify_synthetic_learning(self):
        pred_sha = self.run_trial()
        review_sha = self.run_review(pred_sha)
        report = read(self.root / "review.json", review_sha)
        self.assertEqual(len(report["e1_e2"]["paired_screens"]), 18)
        self.assertEqual(report["reader"]["status"], "MISSING_READER")
        self.assertEqual(report["e3_e4"]["image"]["status"], "MISSING_REAL_MEDIA")
        self.assertEqual(report["e5"]["status"], "MISSING_NATIVE_TARGET_HOST_PROFILES")
        self.assertEqual(report["authority"], "DENY_ALL")
        self.assertFalse(report["readout"]["e1_e5_production_qualified"])

    def test_no_future_label_in_trainer(self):
        rows = json.loads((self.root / "train_labels.json").read_text())
        rows.append({"case_id": "future1-0", "label": 1})
        self.revise("train_labels", rows)
        with self.assertRaises(InputError):
            self.run_trial()

    def test_missing_model_not_silently_replaced(self):
        rows = json.loads((self.root / "features.json").read_text())[:-1]
        self.revise("features", rows)
        with self.assertRaises(InputError):
            self.run_trial()

    def test_model_revision_drift_rejected(self):
        rows = json.loads((self.root / "features.json").read_text())
        rows[0]["revision"] = "2" * 40
        self.revise("features", rows)
        with self.assertRaises(InputError):
            self.run_trial()

    def test_changed_model_not_alias(self):
        rows = json.loads((self.root / "features.json").read_text())
        rows[0]["producer_receipt_sha256"] = d("other")
        self.revise("features", rows)
        with self.assertRaises(InputError):
            self.run_trial()

    def test_cross_split_group_leak_rejected(self):
        rows = json.loads((self.root / "cases.json").read_text())
        rows[-1]["group_id"] = rows[0]["group_id"]
        self.revise("cases", rows)
        with self.assertRaises(InputError):
            self.run_trial()

    def test_cross_split_content_replay_rejected(self):
        rows = json.loads((self.root / "cases.json").read_text())
        rows[-1]["input_sha256"] = rows[0]["input_sha256"]
        self.revise("cases", rows)
        with self.assertRaises(InputError):
            self.run_trial()

    def test_numerical_invalid_feature_denied(self):
        rows = json.loads((self.root / "features.json").read_text())
        rows[1]["vector"] = [0.0] * len(rows[1]["vector"])
        self.revise("features", rows)
        with self.assertRaises(InputError):
            self.run_trial()

    def test_unchanged_run_cannot_overwrite(self):
        self.run_trial()
        with self.assertRaises(FileExistsError):
            self.run_trial()

    def test_wrong_external_truth_identity_denied(self):
        p = self.run_trial()
        targets = json.loads((self.root / "targets.json").read_text())
        targets[-1]["input_sha256"] = d("wrong")
        self.targets_hash = dump(self.root / "targets.json", targets)
        with self.assertRaises(ReviewError):
            self.run_review(p)

    def test_changed_prediction_seal_rejected(self):
        p = self.run_trial()
        content = (self.root / "predictions.json").read_bytes()
        (self.root / "predictions.json").write_bytes(content + b" ")
        with self.assertRaises(ReviewError):
            self.run_review(p)

    def test_fake_production_authority_rejected(self):
        p = self.run_trial()
        predictions = read(self.root / "predictions.json", p)
        predictions["production_promotion_permitted"] = True
        p = dump(self.root / "predictions.json", predictions)
        with self.assertRaises(ReviewError):
            self.run_review(p)

    def test_missing_prediction_arm_rejected(self):
        p = self.run_trial()
        predictions = read(self.root / "predictions.json", p)
        predictions["results"].pop()
        p = dump(self.root / "predictions.json", predictions)
        with self.assertRaises(ReviewError):
            self.run_review(p)

    def test_reader_full_four_arm_parity_and_capacity_failure(self):
        cases = json.loads((self.root / "cases.json").read_text())
        t = {x["case_id"]: x["label"] for x in json.loads((self.root / "targets.json").read_text())}
        rows = []
        for case in cases:
            if case["case_id"] not in t:
                continue
            for mode in ("none", "retrieved", "reviewed_sufficient", "premise_removed"):
                rows.append({"case_id": case["case_id"], "input_sha256": case["input_sha256"],
                             "scenario": mode, "probabilities": [1.0, 0.0],
                             "reader_sha256": d("real_reader_claim"), "budget_tokens": 512})
        result = score_reader(rows, t, {c["case_id"]: c for c in cases})
        self.assertFalse(result["sufficient_evidence_capacity_screen"])
        self.assertFalse(result["independent_sufficient_evidence_verified"])
        rows.pop()
        with self.assertRaises(ReviewError):
            score_reader(rows, t, {c["case_id"]: c for c in cases})

    def test_media_missing_arm_cannot_claim_success(self):
        case = {"case_id": "visual", "modality": "image", "split": "test", "input_sha256": d("image")}
        row = {"case_id": "visual", "modality": "image", "arm": "bridge",
               "input_sha256": case["input_sha256"], "probabilities": [0.1, 0.9]}
        with self.assertRaises(ReviewError):
            score_media([row], {"visual": 1}, {"visual": case})

    def test_resource_profiles_cannot_drop_4096(self):
        with self.assertRaises(ReviewError):
            score_resources({"schema": "hepta.native-stem-e5-resource-claims.v1", "profiles": [
                {"cells": 64}, {"cells": 256}, {"cells": 1024}]})

    def test_head_constructor_2k_8k_16k_hard_ceiling(self):
        for width in (256, 384):
            for budget in BUDGETS:
                for anchored in (True, False):
                    obj = ResidualCellHead(width, budget, anchored=anchored)
                    self.assertLessEqual(obj.parameter_count(), budget)
                    z = torch.ones(2, width)
                    s = torch.zeros(2, 64)
                    base = torch.tensor([[0.4, 0.6], [0.1, 0.9]]).log()
                    result = obj(z, s, base)
                    if anchored:
                        self.assertTrue(torch.equal(result, base))

    def test_scale_physically_executes_head_only_not_encoder(self):
        from e1_e5_head_scale import probe
        for count in (64, 256, 1024, 4096):
            dest = self.root / f"scale-{count}.json"
            receipt_sha = probe(self.root / "plan.json", self.plan_hash,
                                dest, cells=count, active_fraction=0.1, reuse=0.5)
            record = read(dest, receipt_sha)
            self.assertEqual(record["logical_cells"], count)
            self.assertGreater(record["physical_head_forwards"], 0)
            self.assertEqual(record["physical_encoder_forwards"], 0)
            self.assertEqual(record["trained_heads"], 0)
            self.assertFalse(record["native_worker"])
            self.assertFalse(record["production_promotion_permitted"])
            self.assertEqual(record["latency_sample_count"], record["active_cells"])
            if record["active_cells"] < 100:
                self.assertIsNone(record["backend_latency_p99_ns"])

    def test_text_producer_checks_complete_canonical_task(self):
        from e1_e5_text_producer import typed_payload
        from execution import canonical, sha
        doc = {"case_id": "a", "scope": "s", "state": "state", "question": "question",
               "options": ["no", "yes"], "evidence": "evidence"}
        source = ["hepta.stem.e1-e5.typed-input.v1", "s", "state", "question", ["no", "yes"], "evidence"]
        doc["input_sha256"] = sha(canonical(source))
        full, query, evidence = typed_payload(doc)
        self.assertIn("state", full)
        self.assertIn("question", query)
        self.assertEqual(evidence, "evidence")
        doc["state"] = "different"
        with self.assertRaises(InputError):
            typed_payload(doc)

    def test_media_complete_image_arm_scored_but_not_authenticated(self):
        case = {"case_id": "visual", "modality": "image", "split": "test", "input_sha256": d("image")}
        rows = [{"case_id": "visual", "modality": "image", "arm": a,
                 "input_sha256": case["input_sha256"], "probabilities": [0.1, 0.9]}
                for a in ("ocr_only", "unaligned", "bridge", "gemma_native")]
        result = score_media(rows, {"visual": 1}, {"visual": case})
        self.assertEqual(result["image"]["arms"]["bridge"]["accuracy"], 1.0)
        self.assertFalse(result["image"]["causal_task_benefit_proven"])

    def test_media_order_flip_requires_true_opposing_labels(self):
        cases = {"a": {"case_id": "a", "modality": "video", "split": "test", "input_sha256": d("a")},
                 "b": {"case_id": "b", "modality": "video", "split": "test", "input_sha256": d("b")}}
        rows = [{"case_id": c, "modality": "video", "arm": a,
                 "input_sha256": cases[c]["input_sha256"], "probabilities": [0.1, 0.9]}
                for c in cases for a in ("order_blind", "temporal", "reversed")]
        result = score_media(rows, {"a": 1, "b": 0}, cases, [{"forward_id": "a", "reversed_id": "b"}])
        self.assertEqual(result["video"]["true_label_flip_pairs"], 1)
        with self.assertRaises(ReviewError):
            score_media(rows, {"a": 1, "b": 1}, cases,
                        [{"forward_id": "a", "reversed_id": "b"}])

    def test_complete_e5_claim_still_lacks_worker_authentication(self):
        raw = {"schema": "hepta.native-stem-e5-resource-claims.v1", "profiles": [{
            "cells": n, "active_cells": n, "unique_inputs": n // 2,
            "physical_encoder_forwards": n // 2, "peak_rss_bytes": 2**20,
            "cpu_ns": 1000000, "gpu_peak_bytes": 0, "power_joules": 0,
            "p95_ns": 10, "p99_ns": 20, "queue_p99_ns": 5,
            "throughput_per_s": 100, "worker_receipt_sha256": d("unsigned" + str(n)),
            "crash_reopen_verified": True, "revocation_test_verified": True,
        } for n in (64, 256, 1024, 4096)]}
        result = score_resources(raw)
        self.assertFalse(result["production_native_receipts_authenticated"])

    def test_group_bootstrap_requires_independent_future_groups(self):
        weak = grouped_lower_bound([1]*10, [0]*10, ["replayed"]*10)
        self.assertTrue(weak["underpowered"])
        genuine = grouped_lower_bound([1]*40, [0]*40, [str(i) for i in range(40)])
        self.assertGreater(genuine["bonferroni_one_sided_95_lcb"], 0)

if __name__ == '__main__':
    unittest.main()
