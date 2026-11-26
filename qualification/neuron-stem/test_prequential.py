"""Chronological continual-learning proof obligations; offline pure-Python only."""
import unittest

from prequential_trial import (BoundedFeatureCache, model_only_ood_receipt,
                              prepare_chronology, prediction_precommit,
                              score_prediction)


def rows_fixture():
    rows = []
    for split, count, day in (("train", 2, 1), ("calibration", 2, 2),
                              ("test", 2, 3), ("future", 4, 4), ("ood", 2, 5)):
        for index in range(count):
            case = f"{split}-{index}"
            rows.append({
                "case_id": case, "group_id": case,
                "task_id": "decision", "scope_id": "S",
                "cell_id": "neuron-A" if index % 2 == 0 else "neuron-B",
                "split": split, "language": "en", "state": "State: " + case,
                "question": "Is this the next state?",
                "options": ["yes", "no"], "label": index % 2,
                "event_time": f"2026-01-0{day}T00:00:0{index}Z",
            })
    return rows


class PrequentialTests(unittest.TestCase):
    def test_bounded_case_feature_cache_is_lru_and_byte_accounted(self):
        class FakeFrozenFeature:
            def __init__(self, elements, size=4):
                self.elements, self.size = elements, size

            def numel(self):
                return self.elements

            def element_size(self):
                return self.size

        with self.assertRaisesRegex(ValueError, "Feature cache byte ceiling"):
            BoundedFeatureCache(0)
        with self.assertRaisesRegex(ValueError, "Feature cache byte ceiling"):
            BoundedFeatureCache(True)

        cache = BoundedFeatureCache(16)
        called = []
        def build(key, elements=2):
            def produce():
                called.append(key)
                return FakeFrozenFeature(elements)
            return produce

        a = cache.get_or_build(("S", "a"), build("a"))
        cache.get_or_build(("S", "b"), build("b"))
        self.assertIs(cache.get_or_build(("S", "a"), build("must-not-execute")), a)
        cache.get_or_build(("S", "c"), build("c"))
        self.assertEqual(cache.resident_bytes, 16)
        self.assertEqual(cache.peak_resident_bytes, 16)
        self.assertEqual(cache.evictions, 1)
        self.assertEqual(cache.hits, 1)
        self.assertEqual(cache.misses, 3)
        self.assertEqual(called, ["a", "b", "c"])
        cache.get_or_build(("S", "b"), build("b-again"))
        self.assertEqual(called, ["a", "b", "c", "b-again"])
        self.assertLessEqual(cache.resident_bytes, cache.max_bytes)
        with self.assertRaisesRegex(ValueError, "exceeds frozen cache budget"):
            cache.get_or_build(("S", "too-large"), build("oversized", 5))
        self.assertLessEqual(cache.resident_bytes, cache.max_bytes)
        self.assertNotIn(("S", "too-large"), cache.entries)

    def test_feature_cache_keys_must_bind_full_cell_and_options_identity(self):
        from jina_v5 import sha256_record
        before = rows_fixture()[0]
        key = (before["case_id"], before["scope_id"], before["cell_id"],
               sha256_record([before["state"], before["question"], before["options"]]))
        altered = dict(before)
        altered["options"] = list(reversed(before["options"]))
        reordered_key = (altered["case_id"], altered["scope_id"], altered["cell_id"],
                         sha256_record([altered["state"], altered["question"], altered["options"]]))
        self.assertNotEqual(key, reordered_key)
        altered["options"] = before["options"]
        altered["scope_id"] = "other-scope"
        scope_key = (altered["case_id"], altered["scope_id"], altered["cell_id"],
                     sha256_record([altered["state"], altered["question"], altered["options"]]))
        self.assertNotEqual(key, scope_key)

    def test_ood_receipts_are_model_only_and_never_embed_labels(self):
        record = dict(rows_fixture()[3])
        record["split"] = "ood"
        item = model_only_ood_receipt(
            record, "frozen", [.4, .6], model="jina-v5-text-nano",
            revision="d" * 40, weights_digest="c" * 64, generation=7,
            feature_manifest_digest="b" * 64)
        self.assertEqual(item["case_id"], record["case_id"])
        self.assertEqual(item["split"], "ood")
        self.assertNotIn("label", item)
        self.assertNotIn("outcome", item)
        self.assertNotIn("external_ndu_utility", item)
        self.assertFalse(item["production_promotion_permitted"])
        self.assertEqual(item["generation"], 7)
        self.assertEqual(item["feature_manifest_digest"], "b" * 64)
        reordered = dict(record)
        reordered["options"] = list(reversed(record["options"]))
        self.assertNotEqual(
            item["input_digest"],
            model_only_ood_receipt(
                reordered, "frozen", [.4, .6], model="jina-v5-text-nano",
                revision="d" * 40, weights_digest="c" * 64,
                generation=7, feature_manifest_digest="b" * 64)["input_digest"])
        for invalid_kwargs, error in (
                ({"arm": "no_change"}, "only learned/frozen"),
                ({"weights_digest": "unpinned"}, "revision/generation/Encoder manifest not pinned"),
                ({"generation": 0}, "revision/generation/Encoder manifest not pinned"),
                ({"feature_manifest_digest": "unpinned"}, "Encoder manifest not pinned"),
                ({"feature_manifest_digest": "G" * 64}, "Encoder manifest not pinned"),
                ({"revision": "G" * 40}, "revision/generation/Encoder manifest not pinned"),
                ({"probabilities": [float("nan"), 1.0]}, "normalized"),
                ({"probabilities": [.9, .9]}, "normalized")):
            values = dict(
                arm="trained", probabilities=[.4, .6],
                model="jina-v5-text-nano", revision="d" * 40,
                weights_digest="c" * 64, generation=1,
                feature_manifest_digest="b" * 64)
            values.update(invalid_kwargs)
            with self.assertRaisesRegex(ValueError, error):
                model_only_ood_receipt(record, **values)

    def test_precommit_is_label_free_and_deterministic(self):
        row = rows_fixture()[0]
        record = prediction_precommit(row, [.3, .7], "a" * 64, 0)
        self.assertFalse(record["outcome_included"])
        self.assertNotIn("label", record)
        self.assertNotIn("answer", record)
        self.assertEqual(record["event_order"], 0)
        altered_label = dict(row)
        altered_label["label"] = 1 - row["label"]
        self.assertEqual(
            prediction_precommit(row, [.3, .7], "a" * 64, 0),
            prediction_precommit(altered_label, [.3, .7], "a" * 64, 0),
        )
        changed_input = dict(row)
        changed_input["state"] = "Different state"
        self.assertNotEqual(
            prediction_precommit(row, [.3, .7], "a" * 64, 0)["input_digest"],
            prediction_precommit(changed_input, [.3, .7], "a" * 64, 0)["input_digest"],
        )
        with self.assertRaisesRegex(ValueError, "normalization"):
            prediction_precommit(row, [.1, .1], "a" * 64, 0)
        with self.assertRaisesRegex(ValueError, "Head"):
            prediction_precommit(row, [.3, .7], "unbound", 0)

    def test_future_events_are_sorted_and_isolated(self):
        rows = rows_fixture()
        rows = list(reversed(rows))
        task, future, cells, width, audit = prepare_chronology(rows, "decision")
        self.assertEqual(len(future), 4)
        self.assertEqual(len(cells), 2)
        self.assertEqual(width, 2)
        self.assertEqual(audit["cases"], len(rows))
        self.assertEqual([row["case_id"] for row in future],
                         ["future-0", "future-1", "future-2", "future-3"])

    def test_missing_cell_and_duplicate_future_input_fail(self):
        rows = rows_fixture()
        tampered = [dict(row) for row in rows]
        tampered[-1]["cell_id"] = ""
        with self.assertRaisesRegex(ValueError, "cell_id"):
            prepare_chronology(tampered, "decision")
        tampered = [dict(row) for row in rows]
        f0, f2 = next(row for row in tampered if row["case_id"] == "future-0"), next(
            row for row in tampered if row["case_id"] == "future-2")
        f2["state"] = f0["state"]
        f2["question"] = f0["question"]
        f2["options"] = f0["options"]
        with self.assertRaisesRegex(ValueError, "duplicate future"):
            prepare_chronology(tampered, "decision")

    def test_label_integrity_and_normalization(self):
        self.assertEqual(score_prediction([.8, .2], 0)["correct"], 1)
        with self.assertRaisesRegex(ValueError, "distribution mass"):
            score_prediction([.8, .8], 0)
        with self.assertRaisesRegex(ValueError, "invalid predicted probability"):
            score_prediction([float("nan"), 1.], 0)

    def test_oood_may_follow_future_without_future_leak(self):
        rows = rows_fixture()
        # Dataset audit allows OOD window later than future; time-based
        # supervised learning only uses the historical train set.
        task, future, cells, width, audit = prepare_chronology(rows, "decision")
        self.assertEqual(len(future), 4)
        altered = [dict(row) for row in rows]
        for row in altered:
            if row["split"] == "future":
                row["event_time"] = "2026-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "future"):
            prepare_chronology(altered, "decision")


if __name__ == "__main__":
    unittest.main()
