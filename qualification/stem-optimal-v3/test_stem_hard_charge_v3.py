"""Adversarial source/heldout and independent-reviewer tests; no pretrained claim."""
from __future__ import annotations

import copy
import csv
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stem_hard_charge_review_v3 as review
import stem_hard_charge_v3 as producer

MATERIALS = Path(__file__).resolve().parents[1] / "stem-optimal-v1" / "MODEL_MATERIALS.json"


def fixture():
    def csv_bytes(split):
        f = io.StringIO()
        w = csv.writer(f)
        w.writerow(["text", "category"])
        for intent in producer.INTENTS:
            for i in range(24):
                w.writerow([f"{split} {intent} question number {i}", intent])
        return f.getvalue().encode()
    train, test = csv_bytes("train"), csv_bytes("heldout")
    hashes = {"train": producer.base.sha256(train), "test": producer.base.sha256(test)}
    source = producer.prepare(train, test, hashes=hashes)
    return train, test, hashes, source


def fake_run(source, materials, model):
    scores = [0.05, 0.85, 0.05, 0.05]
    return {
        "schema": producer.RUN_SCHEMA, "cohort": producer.COHORT,
        "candidate": model, "source_plan_sha256": source["source_plan_sha256"],
        "material_manifest_sha256": producer.base.sha256(producer.base.canonical(materials)),
        "model_repo": materials["candidates"][model]["repo"],
        "model_revision": materials["candidates"][model]["revision"],
        "actual_weight_sha256": materials["candidates"][model]["weight_sha256"],
        "initial_head_sha256": "a" * 64, "trained_head_sha256": "b" * 64,
        "head_parameters": 27656, "optimizer_steps": 100,
        "rows": [{"case_id": r["case_id"], "source_sha256": r["source_sha256"],
                  "scores": {arm: scores[:] for arm in review.SCORES}}
                 for r in source["heldout"]],
        "cost": {"physical_encoder_sequences": 96, "encoder_forward_batches": 6,
                 "elapsed_wall_seconds": 2.0, "elapsed_cpu_seconds": 1.0,
                 "model_download_load_wall_seconds": 0.4,
                 "feature_encode_wall_seconds": 0.3,
                 "head_train_wall_seconds": 0.5,
                 "maxrss_bytes": 1000000, "energy_joules": None,
                 "p99_latency_ms": None},
        "publisher_future_windows": 0, "matched_421m_lifecycle": False,
        "physical_claim_unattested": True, "production_authorized": False,
        "disposition": "HOLD_NO_GO", "authority": "DENY_ALL",
    }


class HardChargeV3Tests(unittest.TestCase):
    def setUp(self):
        self.train, self.test, self.hashes, self.source = fixture()
        self.materials = producer.base.load_materials(MATERIALS)
        self.runs = [fake_run(self.source, self.materials, name)
                     for name in producer.base.MODEL_NAMES]

    def private_review(self, *, runs=None, source=None, train=None, test=None):
        return review._review(
            self.train if train is None else train,
            self.test if test is None else test,
            self.source if source is None else source,
            self.runs if runs is None else runs,
            self.materials, hashes=self.hashes,
        )

    def test_original_publisher_bytes_are_mandatory(self):
        with self.assertRaisesRegex(ValueError, "publisher data bytes"):
            producer.prepare(self.train, self.test)
        with self.assertRaisesRegex(ValueError, "actual original public bytes"):
            review.review_original(self.train, self.test, self.source,
                                   self.runs, self.materials)

    def test_heldout_is_hidden_and_entire_sample_roster_disjoint(self):
        producer.verify_source(self.source, hashes=self.hashes)
        self.assertEqual(len(self.source["train"]), 64)
        self.assertEqual(len(self.source["heldout"]), 32)
        self.assertEqual(len({r["source_sha256"] for split in ("train", "heldout")
                              for r in self.source[split]}), 96)
        self.assertTrue(all("label" not in row and "category" not in row
                            for row in self.source["heldout"]))

    def test_review_reconstructs_labels_independently_without_qualification(self):
        result = self.private_review()
        self.assertFalse(result["publisher_original_sha_verified"])
        self.assertFalse(result["stem_winner_verified"])
        self.assertFalse(result["production_authorized"])
        self.assertEqual(result["source_independent_families"], 1)
        self.assertEqual(result["future_windows"], 0)
        self.assertEqual(set(result["models"]), set(producer.base.MODEL_NAMES))
        self.assertEqual(result["disposition"], "HOLD_NO_GO")

    def test_full_input_sha_tamper(self):
        with self.assertRaisesRegex(ValueError, "publisher data bytes"):
            producer.prepare(self.train + b" ", self.test, hashes=self.hashes)

    def test_cross_split_duplicate_rejected(self):
        broken = copy.deepcopy(self.source)
        broken["heldout"][0] = {k: v for k, v in broken["train"][0].items()
                                if k != "label"}
        broken["heldout"][0]["case_id"] = broken["heldout"][0]["case_id"].replace(
            "fit:", "heldout:"
        )
        broken["source_plan_sha256"] = producer.base.sha256(producer.base.canonical(
            {k: v for k, v in broken.items() if k != "source_plan_sha256"}
        ))
        with self.assertRaisesRegex(ValueError, "source leak/duplicate"):
            producer.verify_source(broken, hashes=self.hashes)

    def test_explicit_heldout_labels_or_cohort_swap_rejected(self):
        for mutate in (
            lambda s: s["heldout"][0].__setitem__("label", 0),
            lambda s: s.__setitem__("cohort", "easy-four-intents-v1"),
            lambda s: s.__setitem__("intents", list(reversed(s["intents"]))),
            lambda s: s.__setitem__("production_authorized", True),
        ):
            broken = copy.deepcopy(self.source)
            mutate(broken)
            with self.assertRaises(ValueError):
                producer.verify_source(broken, hashes=self.hashes)

    def test_independent_source_roster_rejects_label_swap_even_when_resealed(self):
        bad = copy.deepcopy(self.source)
        bad["train"][0]["label"] = (bad["train"][0]["label"] + 1) % 4
        bad["source_plan_sha256"] = producer.base.sha256(producer.base.canonical(
            {k: v for k, v in bad.items() if k != "source_plan_sha256"}
        ))
        with self.assertRaisesRegex(ValueError, "not independently reconstructed"):
            self.private_review(source=bad)

    def test_model_head_source_and_candidate_guard(self):
        for mutate in (
            lambda r: r[0].__setitem__("source_plan_sha256", "0" * 64),
            lambda r: r[0].__setitem__("cohort", "easy-four-intents-v1"),
            lambda r: r[0].__setitem__("actual_weight_sha256", "f" * 64),
            lambda r: r[0].__setitem__("head_parameters", 1),
            lambda r: r[0].__setitem__("initial_head_sha256", "c" * 64),
            lambda r: r.pop(),
        ):
            broken = copy.deepcopy(self.runs)
            mutate(broken)
            with self.assertRaises(ValueError):
                self.private_review(runs=broken)

    def test_heldout_label_missing_case_nonfinite_and_forged_cost(self):
        for mutate in (
            lambda r: r[0]["rows"][0].__setitem__("label", 0),
            lambda r: r[0]["rows"].pop(),
            lambda r: r[0]["rows"][0]["scores"]["learned"].__setitem__(0, float("nan")),
            lambda r: r[0]["cost"].__setitem__("p99_latency_ms", 0.01),
            lambda r: r[0].__setitem__("publisher_future_windows", 1),
            lambda r: r[0].__setitem__("production_authorized", True),
        ):
            broken = copy.deepcopy(self.runs)
            mutate(broken)
            with self.assertRaises(ValueError):
                self.private_review(runs=broken)


if __name__ == "__main__":
    unittest.main()
