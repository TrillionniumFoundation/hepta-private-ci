"""Only staged/blind-score protocol fixtures; natural data/model scores are external."""
from dataclasses import asdict
from pathlib import Path
from hashlib import sha256
import tempfile
import unittest

from amcn_core import Evidence, Refused, digest
from amcn_historical_trial import (
    CORPUS, GENERATION, PROFILE, SCOPE, read_bounded, score_only_after_seal,
    write_once,
)


def source(label, text):
    return Evidence(label, "locomo:fixture", SCOPE, 1, text,
                    sha256(text.encode()).hexdigest(), GENERATION)


class ThreeProcessOriginalTrialTests(unittest.TestCase):
    def test_source_subset_blind_pairwise_score_and_fail_closed(self):
        a = source("ev-a", "deadlock locks transaction")
        b = source("ev-b", "sunshine lake weather")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            public = {"schema": PROFILE + ".public",
                      "dataset_sha256": CORPUS,
                      "rows": [
                          {"row_id": "a", "question_id": "q", "question": "deadlock locks",
                           "family": "one", "split": "future_a", "evidence": asdict(a)},
                          {"row_id": "b", "question_id": "q", "question": "deadlock locks",
                           "family": "one", "split": "future_a", "evidence": asdict(b)}]}
            write_once(base / "public.json", public)
            write_once(base / "gold.json", {"a": 1, "b": 0})
            predictions = [
                {"row_id": "a", "split": "future_a", "family": "one",
                 "input_sha256": "original-a",
                 "frozen_relevance": .3, "trained_relevance": .8},
                {"row_id": "b", "split": "future_a", "family": "one",
                 "input_sha256": "original-b",
                 "frozen_relevance": .7, "trained_relevance": .1}]
            sealed = base / "sealed"
            sealed.mkdir()
            write_once(sealed / "sealed-predictions.json", predictions)
            receipt = {"schema": "hepta.amcn.real-head-candidate.v1",
                       "prediction_digest": digest(predictions),
                       "production_accepted": False}
            write_once(sealed / "candidate-receipt.json", receipt)
            result = score_only_after_seal(base / "public.json", base / "gold.json",
                                            sealed, base / "scores.json")
            self.assertFalse(result["production_accepted"])
            self.assertEqual(result["metrics"]["full_Reader_responses"], 0)
            metric = result["metrics"]["publisher_weak_support_pairwise_score"]
            self.assertEqual(metric["trained_pairwise_correct"]["correct"], 1)
            self.assertEqual(metric["frozen_pairwise_correct"]["correct"], 0)
            self.assertEqual(metric["simple_bm25_pairwise_correct"]["correct"], 1)
            self.assertEqual(read_bounded(base / "scores.json"), result)
            with self.assertRaises(FileExistsError):
                score_only_after_seal(base / "public.json", base / "gold.json",
                                      sealed, base / "scores.json")
            with self.assertRaises(Refused):
                read_bounded(base / "missing.json")

    def test_withheld_denominator_and_seal_drift_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_once(root / "public.json",
                       {"schema": PROFILE + ".public", "dataset_sha256": CORPUS,
                        "rows": []})
            write_once(root / "gold.json", {"forged": 1})
            sealed = root / "sealed"
            sealed.mkdir()
            write_once(sealed / "sealed-predictions.json", [])
            write_once(sealed / "candidate-receipt.json",
                       {"schema": "hepta.amcn.real-head-candidate.v1",
                        "prediction_digest": digest([]), "production_accepted": False})
            with self.assertRaises(Refused):
                score_only_after_seal(root / "public.json", root / "gold.json",
                                      sealed, root / "score.json")
            self.assertFalse((root / "score.json").exists())


if __name__ == "__main__":
    unittest.main()
