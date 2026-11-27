import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from token_review import score
from token_selection_review import review_selection


class TokenSelectionReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = self.root / "seed-41"
        self.seed.mkdir()
        self.source = self.root / "source"
        self.source.mkdir()
        row = dict(idx=0, passage=dict(text="Internal tuning evidence.", questions=[dict(idx=0, question="Which?",
            answers=[dict(idx=0, text="yes", label=1), dict(idx=1, text="no", label=0)])]))
        (self.source / "train.jsonl").write_text(json.dumps(row) + "\n")
        self.ids = [json.dumps(["train", "0", "0", str(i)], separators=(",", ":")) for i in range(2)]
        self.official = {key: dict(target=1-i, question_key=("train", "0", "0")) for i, key in enumerate(self.ids)}
        self.design = dict(expected_arms=["token"], threshold_grid=[i/20 for i in range(1, 20)],
            dataset_files_sha256={"train.jsonl": hashlib.sha256((self.source / "train.jsonl").read_bytes()).hexdigest()},
            partitions={"tune": [hashlib.sha256(row["passage"]["text"].encode()).hexdigest()]})
        (self.seed / "token.pt").write_bytes(b"frozen artifact fixture")
        self.models = dict(models={"core": dict(file="token.pt", file_sha256=hashlib.sha256((self.seed / "token.pt").read_bytes()).hexdigest(),
                model_sha256="a"*64)}, arm_thresholds=dict(token=.5), arm_model_names=dict(token="core"),
                frozen_before_final_ns=10, final_evaluation_started=False)
        probabilities = [.9, .1]
        candidates = []
        for threshold in self.design["threshold_grid"]:
            metrics = score([dict(case_id=key, prediction=int(p >= threshold)) for key, p in zip(self.ids, probabilities)], self.official)
            candidates.append(dict(threshold=threshold, metrics=metrics))
        self.tuning = dict(token=dict(threshold=.5, candidates=candidates, case_ids=list(self.ids), probabilities=probabilities,
            criterion="F1a_then_EM_then_nearest_0.5_then_lower", final_outcomes_used=False))
        self.write()

    def write(self):
        (self.root / "design.json").write_text(json.dumps(self.design))
        (self.seed / "tuning.json").write_text(json.dumps(self.tuning))
        (self.seed / "models.json").write_text(json.dumps(self.models))
        frozen = dict(final_evaluation_started=False, frozen_ns=20,
            model_manifests_sha256={"41": hashlib.sha256((self.seed / "models.json").read_bytes()).hexdigest()})
        (self.root / "all-models-frozen.json").write_text(json.dumps(frozen))

    def run_review(self):
        return review_selection(self.seed, source_dir=self.source)

    def test_complete_train_only_selection_replayed_and_artifacts_bound(self):
        result = self.run_review()
        self.assertTrue(result["passed"])
        self.assertEqual(result["arm_thresholds"], dict(token=.5))
        self.assertEqual((result["tuning_candidates"], result["tuning_sources"]), (2, 1))
        self.assertEqual(result["arm_model_sha256"], dict(token="a"*64))

    def test_partial_questions_and_final_outcomes_cannot_select(self):
        self.tuning["token"]["case_ids"].pop()
        self.write()
        with self.assertRaisesRegex(ValueError, "omits/duplicates"):
            self.run_review()
        self.tuning["token"]["case_ids"] = self.ids
        self.tuning["token"]["final_outcomes_used"] = True
        self.write()
        with self.assertRaisesRegex(ValueError, "rule changed"):
            self.run_review()

    def test_tie_break_cannot_be_overridden_by_consistent_manifest(self):
        self.tuning["token"]["threshold"] = .6
        self.models["arm_thresholds"]["token"] = .6
        self.write()
        with self.assertRaisesRegex(ValueError, "grid/tie-break"):
            self.run_review()

    def test_mutated_model_or_manifest_reject(self):
        (self.seed / "token.pt").write_bytes(b"changed weights")
        with self.assertRaisesRegex(ValueError, "artifact bytes"):
            self.run_review()
        (self.seed / "token.pt").write_bytes(b"frozen artifact fixture")
        (self.seed / "models.json").write_text((self.seed / "models.json").read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "global freeze"):
            self.run_review()

    def test_tuning_metrics_recomputed_and_source_bytes_pinned(self):
        self.tuning["token"]["candidates"][0]["metrics"]["f1_a"] = 0.
        self.write()
        with self.assertRaisesRegex(ValueError, "official labels"):
            self.run_review()
        (self.source / "train.jsonl").write_text((self.source / "train.jsonl").read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "dataset bytes"):
            self.run_review()


if __name__ == "__main__":
    unittest.main()
