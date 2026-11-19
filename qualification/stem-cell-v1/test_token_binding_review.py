from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from token_binding_review import review_binding
from token_protocol import build_binding_cases, score_binding


class TokenBindingReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cases = list(build_binding_cases("final", groups=2, seed=9))
        self.public = []
        for case in self.cases:
            item = asdict(case)
            item["case_id"] = case.case_id
            self.public.append(item)
        self.rows = []
        for cohort in ("full", "deleted"):
            for case in self.cases:
                predicted = case.label if cohort == "full" else 0
                self.rows.append(dict(case_id=case.case_id, cohort=cohort, arm="token", prediction=predicted,
                    p_positive=.8 if predicted else .2, raw_argmax=predicted, valid=True,
                    model_sha256="a"*64, feature_sha256="b"*64, protocol_sha256="c"*64))
        self.write()

    def write(self):
        summaries = {cohort + ".token": score_binding(self.cases, [r["prediction"] for r in self.rows if r["cohort"] == cohort])
                     for cohort in ("full", "deleted")}
        for name, value in (("controlled-cases.json", self.public), ("observations.json", self.rows),
                            ("report.json", dict(protocol_sha256="c"*64, summaries=summaries))):
            (self.root / name).write_text(json.dumps(value))

    def run_review(self):
        return review_binding(self.root / "controlled-cases.json", self.root / "observations.json", self.root / "report.json")

    def test_semantics_and_complete_evidence_pairs_recomputed_without_generator_import(self):
        result = self.run_review()
        self.assertTrue(result["semantic_targets_independently_rederived"])
        self.assertEqual((result["controlled_cases"], result["controlled_pairs"]), (8, 4))
        full, deleted = result["summaries"]["full.token"], result["summaries"]["deleted.token"]
        self.assertEqual((full["f1_a"], full["exact_match"], full["both_worlds_correct"], full["evidence_switch_rate"]), (1., 1., 1., 1.))
        self.assertEqual((deleted["accuracy"], deleted["both_worlds_correct"], deleted["evidence_switch_rate"]), (.5, 0., 0.))
        self.assertFalse(result["natural_multirc_generalization"])

    def test_flipping_predictions_is_not_counted_as_solving_both_worlds(self):
        for row in self.rows:
            if row["cohort"] == "full":
                row["prediction"] = 1 - row["prediction"]
                row["raw_argmax"] = row["prediction"]
                row["p_positive"] = .8 if row["prediction"] else .2
        self.write()
        result = self.run_review()["summaries"]["full.token"]
        self.assertEqual((result["evidence_switch_rate"], result["both_worlds_correct"], result["accuracy"]), (1., 0., 0.))

    def test_fabricated_labels_reject_even_if_report_agrees(self):
        self.public[0]["label"] = 1 - self.public[0]["label"]
        self.write()
        with self.assertRaisesRegex(ValueError, "independently solved"):
            self.run_review()

    def test_evidence_tampering_and_unregistered_grammar_reject(self):
        self.public[0]["facts"] = list(self.public[0]["facts"])
        self.public[0]["facts"][0] += " "
        self.write()
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.run_review()
        self.public[0]["source_hash"] = hashlib.sha256("\n".join(self.public[0]["facts"]).encode()).hexdigest()
        self.write()
        with self.assertRaisesRegex(ValueError, "grammar"):
            self.run_review()

    def test_world_pairs_require_equal_words_and_complete_candidates(self):
        prefix = self.public[0]["paragraph_id"].rsplit("/world-", 1)[0]
        for case in self.public:
            if case["paragraph_id"] == prefix + "/world-1":
                old = next(fact.split()[0] for fact in case["facts"] if "stores" in fact)
                case["facts"] = [fact.replace(old, "Avery") for fact in case["facts"]]
                case["source_hash"] = hashlib.sha256("\n".join(case["facts"]).encode()).hexdigest()
        self.write()
        with self.assertRaisesRegex(ValueError, "equal-word-count"):
            self.run_review()

    def test_missing_world_rejects(self):
        world = self.public[0]["paragraph_id"].rsplit("/world-", 1)[0] + "/world-1"
        self.public = [case for case in self.public if case["paragraph_id"] != world]
        self.write()
        with self.assertRaisesRegex(ValueError, "both evidence worlds"):
            self.run_review()

    def test_duplicate_predictions_reject(self):
        self.rows.append(dict(self.rows[0]))
        (self.root / "observations.json").write_text(json.dumps(self.rows))
        with self.assertRaisesRegex(ValueError, "incomplete controlled"):
            self.run_review()

    def test_report_cannot_replace_pair_accuracy_with_switch_rate(self):
        report = json.loads((self.root / "report.json").read_text())
        report["summaries"]["deleted.token"]["both_worlds_correct"] = 1.
        (self.root / "report.json").write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "metric differs"):
            self.run_review()

    def test_model_and_typed_probability_bindings_checked(self):
        self.rows[-1]["model_sha256"] = "d"*64
        self.write()
        with self.assertRaisesRegex(ValueError, "model changed"):
            self.run_review()
        self.rows[-1]["model_sha256"] = "a"*64
        self.rows[-1]["p_positive"] = True
        self.write()
        with self.assertRaisesRegex(ValueError, "finite controlled"):
            self.run_review()


if __name__ == "__main__":
    unittest.main()
