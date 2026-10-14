"""External source protocol tests on invented strings; NOT pretrained evidence."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments.shared_stem_cell import external_bbc_shift as b


class ShiftTests(unittest.TestCase):
    def texts(self):
        return [f"Synthetic article content number {i:04d} about topic and "
                f"publication number {i} with enough words to pass the limit"
                for i in range(256)]

    def test_label_free_hash_determinism_and_only_hashed_public_index(self):
        first = b.sample(self.texts())
        second = b.sample(list(self.texts()))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 128)
        self.assertEqual([r["cell"] for r in first], [i % 2 for i in range(128)])
        self.assertNotIn("text", b.public_cohort(first)[0])
        self.assertNotIn("synthetic", json.dumps(b.public_cohort(first)).lower())
        self.assertEqual(len({r["source_index"] for r in first}), 128)

    def test_unknown_label_never_mapped_to_one_of_four_ag_classes(self):
        rows = b.public_cohort(b.sample(self.texts()))
        labels = ["business", "sport", "politics", "tech", "entertainment"] * 25 + ["business"] * 3
        frozen = {arm: [[0.1, 0.1, 0.7, 0.1] for _ in rows] for arm in b.ARMS}
        result = b.score_sealed(frozen, labels, rows)
        self.assertEqual(result["unsupported"], 25)
        self.assertEqual(result["proxy_eligible"], 103)
        self.assertEqual(result["scores"]["bank"]["proxy_correct"], 28)
        self.assertFalse(result["same_label_ontology_verified"])
        self.assertFalse(result["production_accepted"])
        labels[0] = "unknown"
        with self.assertRaises(b.SourceError):
            b.score_sealed(frozen, labels, rows)

    def test_unsupported_category_high_confidence_is_reported_not_scored(self):
        rows = b.public_cohort(b.sample(self.texts()))
        labels = ["entertainment" if i % 8 == 0 else "business" for i in range(128)]
        probabilities = {arm: [[0.01, 0.01, 0.96, 0.02] for _ in rows] for arm in b.ARMS}
        report = b.score_sealed(probabilities, labels, rows)
        for arm in b.ARMS:
            score = report["scores"][arm]
            self.assertEqual(score["proxy_scored"], 112)
            self.assertEqual(score["proxy_correct"], 112)
            self.assertAlmostEqual(score["proxy_brier_uncalibrated"], 0.0022)
            unknown = score["unsupported_confidence"]
            self.assertEqual(unknown["cases"], 16)
            self.assertEqual(unknown["top1_at_least_0_8"], 16)
            self.assertEqual(unknown["top1_at_least_0_95"], 16)
            self.assertEqual(unknown["per_cell"]["0"]["cases"], 16)
            self.assertEqual(unknown["per_cell"]["1"]["cases"], 0)
        self.assertTrue(report["unsupported_confidence_is_not_a_fifth_class_prediction"])
        self.assertFalse(report["new_ood_calibration_performed"])
        self.assertFalse(report["production_accepted"])

    def test_missing_arm_malformed_probs_and_bad_source_reject(self):
        rows = b.public_cohort(b.sample(self.texts()))
        labels = ["business"] * 120 + ["entertainment"] * 8
        frozen = {arm: [[0.1, 0.1, 0.7, 0.1] for _ in rows] for arm in b.ARMS}
        for wrong in (dict(list(frozen.items())[:-1]),
                      {**frozen, "bank": frozen["bank"][:-1]},
                      {**frozen, "bank": [[0.2, 0.2, 0.2, 0.2]] + frozen["bank"][1:]}):
            with self.assertRaises(b.SourceError):
                b.score_sealed(wrong, labels, rows)
        with self.assertRaises(b.SourceError):
            b.score_sealed(frozen, labels, rows, source_revision="unqualified")

    def test_shared_producer_write_once_bytes_score_without_reinterpretation(self):
        from experiments.shared_stem_cell import wire
        rows = b.public_cohort(b.sample(self.texts()))
        probabilities = {arm: [[0.1, 0.1, 0.7, 0.1] for _ in rows] for arm in b.ARMS}
        packet = {"schema": b.SCHEMA, "source_revision": b.REVISION,
                  "cohort_sha256": b.digest(wire.canonical(rows)),
                  "case_ids": [r["case_id"] for r in rows],
                  "predictions": probabilities, "work": {}, "production_accepted": False}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pred, cohort = root / "predictions.json", root / "cohort.json"
            cohort_sha = wire.write_once(cohort, rows)
            self.assertEqual(packet["cohort_sha256"], cohort_sha)
            seal = wire.write_once(pred, packet)
            self.assertEqual(pred.read_bytes(), b.canonical(packet))
            self.assertEqual(cohort.read_bytes(), b.canonical(rows))
            count = []
            def label(index):
                self.assertTrue(pred.read_bytes().endswith(b"\n"))
                count.append(index)
                return "business" if len(count) <= 120 else "entertainment"
            result = b.evaluate_published(pred, seal, cohort, cohort_sha, rows, label)
            self.assertEqual(len(count), 128)
            self.assertEqual(result["scores"]["bank"]["proxy_correct"], 120)
            self.assertFalse(result["production_accepted"])

    def test_prediction_and_cohort_bytes_must_seal_before_label_callback(self):
        rows = b.public_cohort(b.sample(self.texts()))
        probs = {arm: [[0.1, 0.1, 0.7, 0.1] for _ in rows] for arm in b.ARMS}
        cohort_raw = b.canonical(rows)
        cohort_sha = b.digest(cohort_raw)
        packet = {"schema": b.SCHEMA, "source_revision": b.REVISION,
                  "cohort_sha256": cohort_sha,
                  "case_ids": [r["case_id"] for r in rows],
                  "predictions": probs, "work": {}, "production_accepted": False}
        raw = b.canonical(packet)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pred, cohort = root / "predictions.json", root / "cohort.json"
            pred.write_bytes(raw)
            cohort.write_bytes(cohort_raw)
            calls = []
            def label(index):
                self.assertEqual(b.digest(pred.read_bytes()), b.digest(raw))
                calls.append(index)
                return "business" if len(calls) < 121 else "entertainment"
            result = b.evaluate_published(pred, b.digest(raw), cohort,
                                          cohort_sha, rows, label)
            self.assertEqual(len(calls), 128)
            self.assertEqual(result["scores"]["bank"]["proxy_correct"], 120)
            calls.clear()
            pred.write_bytes(raw + b"\n")
            with self.assertRaises(b.SourceError):
                b.evaluate_published(pred, b.digest(raw), cohort,
                                     cohort_sha, rows, label)
            self.assertEqual(calls, [])
            pred.write_bytes(raw)
            cohort.write_bytes(cohort_raw + b"\n")
            with self.assertRaises(b.SourceError):
                b.evaluate_published(pred, b.digest(raw), cohort,
                                     cohort_sha, rows, label)
            self.assertEqual(calls, [])
            cohort.write_bytes(cohort_raw)
            def tamper_with_prediction(index):
                pred.write_bytes(b"{}")
                return "business"
            with self.assertRaises(b.SourceError):
                b.evaluate_published(pred, b.digest(raw), cohort,
                                     cohort_sha, rows, tamper_with_prediction)
            calls.clear()
            pred.write_bytes(raw)
            alias = root / "alias"
            alias.symlink_to(pred)
            with self.assertRaises(b.SourceError):
                b.evaluate_published(alias, b.digest(raw), cohort,
                                     cohort_sha, rows, lambda _: self.fail("premature label"))

    def test_full_historical_article_cannot_reenter_as_truncated_new_article(self):
        original = ("Historical economic report with long article content " * 16)
        self.assertGreater(len(original), b.PREFIX)
        texts = [original] + self.texts()
        # An exact full-document duplicate must be excluded despite BBC
        # embedding only the first 320 characters as the model input.
        rows = b.sample(texts, excluded=[original])
        self.assertEqual(len(rows), b.COUNT)
        self.assertTrue(all(r["source_index"] != 0 for r in rows))
        # Exclusion by the original representation is also preserved.
        prefix = " ".join(original.split())[:b.PREFIX]
        rows = b.sample(texts, excluded=[prefix])
        self.assertTrue(all(r["source_index"] != 0 for r in rows))

    def test_insufficient_or_duplicate_unlabeled_source_rejects(self):
        with self.assertRaises(b.SourceError):
            b.sample(self.texts()[:8])
        with self.assertRaises(b.SourceError):
            b.sample([self.texts()[0]] * 256)
        with self.assertRaises(b.SourceError):
            b.sample([*self.texts(), 7])
        with self.assertRaises(b.SourceError):
            b.sample(self.texts(), count=129)


if __name__ == "__main__":
    unittest.main()
