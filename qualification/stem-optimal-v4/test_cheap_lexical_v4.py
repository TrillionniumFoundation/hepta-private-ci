"""Real stdlib lexical arithmetic on synthetic text, with denial/adversarial tests."""
from __future__ import annotations

import copy
import csv
import io
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "stem-optimal-v3"))
import cheap_lexical_stem_v4 as lexical
import cheap_lexical_review_v4 as review
import stem_hard_charge_v3 as cohort


def fixture():
    def csv_rows(split):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["text", "category"])
        for label, category in enumerate(cohort.INTENTS):
            for i in range(24):
                writer.writerow([f"{split} {category} charge question {i} variation {label}", category])
        return buffer.getvalue().encode("utf-8")
    train, test = csv_rows("train"), csv_rows("test")
    hashes = {"train": cohort.base.sha256(train),
              "test": cohort.base.sha256(test)}
    source = cohort.prepare(train, test, hashes=hashes)
    receipt = lexical.compute(source, hashes=hashes)
    return train, test, source, receipt, hashes


class CheapLexicalOriginalV4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train, cls.test, cls.source, cls.receipt, cls.hashes = fixture()

    def review(self, receipt=None, source=None, train=None):
        return review._review(
            self.train if train is None else train,
            self.test,
            self.source if source is None else source,
            self.receipt if receipt is None else receipt,
            hashes=self.hashes,
        )

    def test_true_python_cpu_features_and_independent_replay(self):
        result = self.review()
        self.assertEqual(set(result["cheap_controls"]), set(lexical.ARMS))
        self.assertTrue(result["independent_algorithm_replay"])
        self.assertEqual(result["case_count"], 32)
        self.assertFalse(result["publisher_original_sha_verified"])
        self.assertFalse(result["stem_winner_verified"])
        self.assertEqual(result["disposition"], "HOLD_NO_GO")

    def test_original_publisher_required_at_public_entry(self):
        with self.assertRaises(ValueError):
            lexical.compute(self.source)
        with self.assertRaisesRegex(ValueError, "actual original public bytes"):
            review.review_original(self.train, self.test, self.source, self.receipt)

    def test_no_model_loaded_no_encoder_forward(self):
        self.assertEqual(self.receipt["cost"]["neural_encoder_forward_count"], 0)
        self.assertFalse(self.receipt["cost"]["pretrained_model_loaded"])
        self.assertEqual(self.receipt["training_rows"], 64)
        self.assertEqual(self.receipt["prediction_rows"], 32)
        self.assertTrue(all("label" not in row and "category" not in row
                            for row in self.receipt["rows"]))

    def test_vocab_never_uses_heldout(self):
        other = copy.deepcopy(self.source)
        other["heldout"][0]["text"] = "arbitrary unheard words outside every fit sentence"
        one = lexical._vectors([r["text"] for r in self.source["train"]], lexical.ARMS[0])[1]
        two = lexical._vectors([r["text"] for r in other["train"] + other["heldout"]], lexical.ARMS[0])[1]
        self.assertEqual(one, two)

    def test_producer_nonfinite_probabilities_rejected(self):
        modified = copy.deepcopy(self.receipt)
        modified["rows"][0]["scores"][lexical.ARMS[0]][1] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite or invalid scores"):
            self.review(receipt=modified)

    def test_reject_changed_real_control_output_even_if_normalized(self):
        altered = copy.deepcopy(self.receipt)
        v = altered["rows"][0]["scores"][lexical.ARMS[0]]
        v[0] += 1e-4
        v[1] -= 1e-4
        with self.assertRaisesRegex(ValueError, "cannot be independently recomputed"):
            self.review(receipt=altered)

    def test_reject_fake_vocab_and_temperature(self):
        for mutate in (
            lambda r: r["lexical_vocabulary"].__setitem__(lexical.ARMS[0], 1),
            lambda r: r.__setitem__("temperature", 5.0),
            lambda r: r.__setitem__("algorithm", "label-selected-idf"),
        ):
            altered = copy.deepcopy(self.receipt)
            mutate(altered)
            with self.assertRaises(ValueError):
                self.review(receipt=altered)

    def test_reject_claimed_encoder_forward_and_forged_performance(self):
        for mutate in (
            lambda r: r["cost"].__setitem__("pretrained_model_loaded", True),
            lambda r: r["cost"].__setitem__("neural_encoder_forward_count", 1),
            lambda r: r["cost"].__setitem__("p99_latency_ms", 0.1),
            lambda r: r.__setitem__("production_authorized", True),
            lambda r: r.__setitem__("future_windows", 2),
            lambda r: r.__setitem__("stem_winner_verified", True),
        ):
            altered = copy.deepcopy(self.receipt)
            mutate(altered)
            with self.assertRaises(ValueError):
                self.review(receipt=altered)

    def test_reject_train_label_swaps_even_if_resealed(self):
        broken = copy.deepcopy(self.source)
        broken["train"][0]["label"] = (broken["train"][0]["label"] + 1) % 4
        broken["source_plan_sha256"] = cohort.base.sha256(cohort.base.canonical({
            k: v for k, v in broken.items() if k != "source_plan_sha256"
        }))
        with self.assertRaisesRegex(ValueError, "independent V3 cohort identity mismatch"):
            self.review(source=broken)

    def test_missing_duplicate_label_bearing_heldout_rejected(self):
        for mutate in (
            lambda r: r["rows"].pop(),
            lambda r: r["rows"].append(copy.deepcopy(r["rows"][0])),
            lambda r: r["rows"][0].__setitem__("label", 1),
            lambda r: r["rows"][0].__setitem__("source_sha256", "f" * 64),
        ):
            broken = copy.deepcopy(self.receipt)
            mutate(broken)
            with self.assertRaises(ValueError):
                self.review(receipt=broken)

    def test_source_across_split_mismatch_rejected(self):
        bad = copy.deepcopy(self.source)
        bad["heldout"][0] = {k: v for k, v in bad["train"][0].items() if k != "label"}
        with self.assertRaisesRegex(ValueError, "independent V3 cohort identity mismatch"):
            self.review(source=bad)


if __name__ == "__main__":
    unittest.main()
