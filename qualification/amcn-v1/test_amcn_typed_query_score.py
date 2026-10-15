"""Original query/source-first validation and adversarial retrieval score tests."""
from copy import deepcopy
from hashlib import sha256
import unittest

from amcn_typed_query_score import (
    Refused, ARMS, PROFILE, PUBLIC, WITHHELD, TRAIN_PROFILE, SOURCE_FIRST,
    canonical, digest, score_query_support, _row_input_digest,
)


def setup():
    rows, plans, publisher, row_labels, typed, pred = [], {}, {}, {}, {}, []
    scope, generation = "study", "snapshot1"
    info = {"schema": PUBLIC, "scope": scope, "generation": generation}
    for split in ("train", "select", "future_a", "future_b", "retention"):
        for ki, kind in enumerate(("semantic", "procedural")):
            qid = f"{split}:{kind}"
            if split != "train":
                publisher[qid] = ([] if split == "future_b" and ki == 1
                                  else [qid + "/source2"])
            ranked = [qid + f"/source{i}" for i in range(3)]
            if split != "train":
                plans[qid] = {"schema": SOURCE_FIRST,
                    "source_scope": scope, "source_generation": generation,
                    "question_sha256": digest(qid), "source_inventory_sha256": digest(qid),
                    "eligible_source_count": 3, "shortlist_size": 3,
                    "ranked_source_ids": ranked, "ranked_scores": [3.0, 2.0, 1.0],
                    "labels_accessed": False,
                    "independent_semantic_support_verified": False}
            for j in range(3):
                rid = f"{qid}:row{j}"
                text = f"Original evidence content for {qid}:{j}"
                ev = {"evidence_id": ranked[j], "source_root": qid,
                      "scope": scope, "revision": 1, "text": text,
                      "content_sha256": sha256(text.encode()).hexdigest(),
                      "generation": generation, "revoked": False}
                row = {"row_id": rid, "question_id": qid, "question": qid,
                       "family": f"family-{split}-{kind}", "split": split,
                       "evidence": ev}
                rows.append(row)
                typed[rid] = kind
                if split != "train":
                    row_labels[rid] = int(ev["evidence_id"] in publisher[qid])
                    probs = {arm: (0.9 if j == 2 else 0.3) for arm in ARMS
                             if arm != "lexical_top1"}
                    probs["untyped_equal_budget"] = 0.95 if j == 0 else 0.1
                    probs["typed_swapped_negative"] = 0.9 if j == 0 else 0.1
                    pred.append({"row_id": rid, "family": row["family"],
                        "split": split, "input_sha256": _row_input_digest(row, scope),
                        "memory_type": kind, "probabilities": probs})
    public = {**info, "rows": rows, "source_first_shortlists": plans}
    withheld = {"schema": WITHHELD, "row_labels": row_labels,
                "publisher_support": publisher,
                "source_first_plan_sha256": digest(plans)}
    feature_sha = digest("actual physical frozen feature identity")
    type_sha = digest({"profile": TRAIN_PROFILE, "features": feature_sha,
        "types": [(r["row_id"], typed[r["row_id"]]) for r in rows]})
    receipt = {"production_accepted": False, "metrics": {
        "profile": TRAIN_PROFILE, "frozen_feature_sha256": feature_sha,
        "prediction_sha256": digest(pred),
        "precommitted_type_inventory_sha256": type_sha}}
    return public, withheld, pred, receipt, typed


def run(p, w, pred, receipt, types, **kwargs):
    pins = {"expected_public_sha256": digest(p),
            "expected_withheld_sha256": digest(w),
            "expected_predictions_sha256": digest(pred),
            "expected_type_sha256": receipt["metrics"]["precommitted_type_inventory_sha256"]}
    pins.update(kwargs)
    return score_query_support(p, w, pred, receipt, types, **pins)


class QueryMetricTest(unittest.TestCase):
    def setUp(self):
        self.p, self.w, self.pred, self.receipt, self.types = setup()

    def value(self, **kwargs):
        return run(self.p, self.w, self.pred, self.receipt, self.types, **kwargs)

    def test_actual_question_metric_and_source_first_baseline(self):
        result = self.value()
        self.assertEqual(result["schema"], PROFILE)
        self.assertEqual(result["total_heldout_queries"], 8)
        self.assertEqual(result["total_heldout_candidates"], 24)
        self.assertEqual(result["zero_support_or_zero_shortlist_questions"], 1)
        self.assertFalse(result["production_accepted"])
        self.assertEqual(result["true_future_calendar_windows"], 0)
        rows = result["by_split_type_arm"]
        self.assertEqual(next(x["top1_hits"] for x in rows if x["split"] == "select" and
                              x["memory_type"] == "semantic" and x["arm"] == "typed_equal_budget"), 1)
        self.assertEqual(next(x["top1_hits"] for x in rows if x["split"] == "select" and
                              x["memory_type"] == "semantic" and x["arm"] == "lexical_top1"), 0)
        self.assertEqual(sum(x["top1_hits"] for x in rows if x["arm"] == "typed_equal_budget"), 7)
        self.assertEqual(sum(x["top1_hits"] for x in rows if x["arm"] == "untyped_equal_budget"), 0)
        self.assertEqual(result["future_source_family_count_upper_bound"], 4)

    def test_false_100_percent_row_accuracy_is_not_query_hit(self):
        # All-negative weak publisher case never becomes a successful answer.
        x = self.value()
        chosen = [r for r in x["by_split_type_arm"] if r["split"] == "future_b" and
                  r["memory_type"] == "procedural"]
        self.assertTrue(all(r["top1_hits"] == 0 for r in chosen))
        self.assertTrue(all(r["no_shortlist_support"] == 1 for r in chosen))

    def test_labels_cannot_be_edited_after_original_source_plan_seal(self):
        changed = deepcopy(self.w)
        changed["source_first_plan_sha256"] = digest("other")
        with self.assertRaises(Refused):
            run(self.p, changed, self.pred, self.receipt, self.types)

    def test_frozen_original_model_predictions_cannot_be_reordered_with_sources(self):
        pred = deepcopy(self.pred)
        pred[0]["input_sha256"] = digest("mutated")
        with self.assertRaises(Refused):
            run(self.p, self.w, pred, self.receipt, self.types)

    def test_cannot_change_sample_size_or_drop_zero_hit(self):
        pred = deepcopy(self.pred)
        pred.pop()
        with self.assertRaises(Refused):
            run(self.p, self.w, pred, self.receipt, self.types)
        p = deepcopy(self.p)
        p["rows"] = [r for r in p["rows"] if r["question_id"] != "future_b:procedural"]
        with self.assertRaises(Refused):
            run(p, self.w, self.pred, self.receipt, self.types)

    def test_changed_source_text_digest_even_with_rehashed_public_pin_refused(self):
        p = deepcopy(self.p)
        p["rows"][0]["evidence"]["text"] = "misleading changed source"
        with self.assertRaises(Refused):
            run(p, self.w, self.pred, self.receipt, self.types)

    def test_predictor_must_have_all_unchanged_five_arms(self):
        pred = deepcopy(self.pred)
        del pred[0]["probabilities"]["typed_swapped_negative"]
        with self.assertRaises(Refused):
            run(self.p, self.w, pred, self.receipt, self.types)
        pred = deepcopy(self.pred)
        pred[0]["probabilities"]["typed_equal_budget"] = float("nan")
        with self.assertRaises(ValueError):
            run(self.p, self.w, pred, self.receipt, self.types)

    def test_predeclared_functional_type_provenance(self):
        types = deepcopy(self.types)
        first = next(iter(types))
        types[first] = "salience"
        with self.assertRaises(Refused):
            run(self.p, self.w, self.pred, self.receipt, types)
        types = deepcopy(self.types)
        del types[first]
        with self.assertRaises(Refused):
            run(self.p, self.w, self.pred, self.receipt, types)

    def test_changed_lexical_shortlist_ranking_is_not_original(self):
        p = deepcopy(self.p)
        p["source_first_shortlists"]["future_a:semantic"]["ranked_source_ids"].reverse()
        with self.assertRaises(Refused):
            run(p, self.w, self.pred, self.receipt, self.types)

    def test_bad_publisher_support_rejected(self):
        w = deepcopy(self.w)
        w["publisher_support"]["future_a:semantic"] = ["unknown"]
        with self.assertRaises(Refused):
            run(self.p, w, self.pred, self.receipt, self.types)
        w = deepcopy(self.w)
        w["publisher_support"]["future_a:semantic"] = ["x", "x"]
        with self.assertRaises(Refused):
            run(self.p, w, self.pred, self.receipt, self.types)

    def test_foreign_or_revoked_source_rejected(self):
        p = deepcopy(self.p)
        p["rows"][0]["evidence"]["revoked"] = True
        with self.assertRaises(Refused):
            run(p, self.w, self.pred, self.receipt, self.types)
        p = deepcopy(self.p)
        p["rows"][0]["evidence"]["scope"] = "another-user"
        with self.assertRaises(Refused):
            run(p, self.w, self.pred, self.receipt, self.types)

    def test_original_generation_binding(self):
        p = deepcopy(self.p)
        p["rows"][0]["evidence"]["generation"] = "stale"
        with self.assertRaises(Refused):
            run(p, self.w, self.pred, self.receipt, self.types)

    def test_production_receipt_not_admitted(self):
        r = deepcopy(self.receipt)
        r["production_accepted"] = True
        with self.assertRaises(Refused):
            run(self.p, self.w, self.pred, r, self.types)

    def test_digest_fields_must_be_out_of_band_equal(self):
        with self.assertRaises(Refused):
            self.value(expected_public_sha256=digest("fake"))
        with self.assertRaises(Refused):
            self.value(expected_predictions_sha256=digest("fake"))


if __name__ == "__main__":
    unittest.main()
