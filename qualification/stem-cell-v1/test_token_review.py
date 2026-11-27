import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from token_review import digest, review, score


class TokenReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.sources, self.ids, self.official = {}, {}, {}
        for split, filename, paragraphs in (("train", "train.jsonl", [(0, "Training evidence.")]),
                                            ("validation", "val.jsonl", [(0, "Prior evidence."), (1, "Fresh evidence.")])):
            records = []
            for paragraph_id, text in paragraphs:
                source = hashlib.sha256(text.encode()).hexdigest()
                self.sources[(split, paragraph_id)] = source
                questions = []
                for q in range(2):
                    answers = []
                    for a in range(2):
                        case = json.dumps([split, str(paragraph_id), str(q), str(a)], separators=(",", ":"))
                        self.ids.setdefault((split, paragraph_id), []).append(case)
                        self.official[case] = dict(target=1-a, question_key=(split, str(paragraph_id), str(q)))
                        answers.append(dict(idx=a, text=str(a), label=1-a))
                    questions.append(dict(idx=q, question="Which?", answers=answers))
                records.append(dict(idx=paragraph_id, passage=dict(text=text, questions=questions)))
            (self.source / filename).write_text("".join(json.dumps(r) + "\n" for r in records))
        self.prior = self.root / "previous-design.json"
        self.prior.write_text(json.dumps(dict(partitions={"final": [self.sources[("validation", 0)]]},
                                               final_case_ids=self.ids[("validation", 0)])))
        self.ids_final = self.ids[("validation", 1)]
        (self.root / "model.py").write_text("# fixture\n")
        self.protocol = dict(schema="token.v1", source_sha256={"model.py": hashlib.sha256(b"# fixture\n").hexdigest()},
            dataset_files_sha256={name: hashlib.sha256((self.source / name).read_bytes()).hexdigest() for name in ("train.jsonl", "val.jsonl")},
            partitions={"train": [self.sources[("train", 0)]], "final": [self.sources[("validation", 1)]], "regression": [self.sources[("validation", 0)]]},
            final_case_ids=self.ids_final, final_question_candidate_ids={str(q): self.ids_final[q*2:q*2+2] for q in range(2)},
            previous_final_case_ids=list(self.ids[("validation", 0)]), previous_final_source_hashes=[self.sources[("validation", 0)]],
            previous_design_sha256=hashlib.sha256(self.prior.read_bytes()).hexdigest(),
            expected_arms=["token", "query_only"], expected_cohorts=["full", "deleted"],
            arm_model_sha256=dict(token="a"*64, query_only="b"*64), arm_thresholds=dict(token=.6, query_only=.6), arm_depths=dict(token=3, query_only=1),
            arm_input_transforms=dict(token="identity", query_only="delete_evidence"),
            public_feature_sha256={cohort: {case: digest([cohort, case]) for case in self.ids_final} for cohort in ("full", "deleted")})
        self.rows, self.batches = [], []
        for cohort in ("full", "deleted"):
            for arm in ("token", "query_only"):
                key = cohort + "." + arm
                self.batches.append(dict(batch_id=key, arm=arm, cohort=cohort, case_ids=self.ids_final,
                                         cpu_ns=10, wall_ns=20, steps=self.protocol["arm_depths"][arm], formula_flops=None))
                for case in self.ids_final:
                    p = .7 if self.official[case]["target"] else .55
                    effective = "deleted" if arm == "query_only" else cohort
                    self.rows.append(dict(case_id=case, arm=arm, cohort=cohort, batch_id=key, p_positive=p,
                                          prediction=int(p >= .6), raw_argmax=int(p > .5), valid=True,
                                          model_sha256=self.protocol["arm_model_sha256"][arm],
                                          feature_sha256=self.protocol["public_feature_sha256"][effective][case]))
        self.write()

    def write(self):
        summaries = {}
        for row in self.rows:
            row["protocol_sha256"] = digest(self.protocol)
        for cohort in self.protocol["expected_cohorts"]:
            for arm in self.protocol["expected_arms"]:
                panel = [r for r in self.rows if r["arm"] == arm and r["cohort"] == cohort]
                physical = [b for b in self.batches if b["arm"] == arm and b["cohort"] == cohort]
                summary = score(panel, self.official)
                summary.update(raw_argmax_metrics=score(panel, self.official, prediction_field="raw_argmax"),
                    physical_batches=len(physical), cpu_ns=sum(b["cpu_ns"] for b in physical),
                    wall_ns=sum(b["wall_ns"] for b in physical),
                    proposal_steps=sum(len(b["case_ids"]) * b["steps"] for b in physical))
                summaries[cohort + "." + arm] = summary
        for name, value in (("protocol.json", self.protocol), ("observations.json", self.rows),
                            ("inference-batches.json", self.batches),
                            ("report.json", dict(protocol_sha256=digest(self.protocol), summaries=summaries))):
            (self.root / name).write_text(json.dumps(value))

    def run_review(self):
        return review(self.root, source_dir=self.source, code_dir=self.root, previous_design=self.prior)

    def test_complete_labels_thresholds_and_costs_once_per_physical_batch(self):
        result = self.run_review()
        self.assertTrue(result["passed"])
        self.assertEqual(result["physical_inference_batches"], 4)
        panel = result["summaries"]["full.token"]
        self.assertEqual((panel["n"], panel["questions"], panel["f1_a"], panel["exact_match"]), (4, 2, 1., 1.))
        self.assertEqual((panel["physical_batches"], panel["cpu_ns"], panel["wall_ns"], panel["proposal_steps"]), (1, 10, 20, 12))
        self.assertEqual(panel["raw_argmax_metrics"]["f1_a"], 2/3)
        self.assertIsNone(panel["formula_flops"])
        self.assertEqual(result["all_positive"]["exact_match"], 0.)
        self.assertEqual(result["evidence_interventions"]["token"]["mean_absolute_probability_shift"], 0.)

    def test_global_f1_and_question_groups_are_independent(self):
        official = {str(i): dict(target=int(i < 4), question_key=("v", "p", "q" if i else "other")) for i in range(5)}
        rows = [dict(case_id=str(i), prediction=int(i == 0)) for i in range(5)]
        self.assertEqual(score(rows, official)["f1_a"], .4)
        self.assertEqual(score(rows, official)["exact_match"], .5)

    def test_changed_probability_threshold_or_raw_argmax_rejected(self):
        self.rows[0]["prediction"] = 0
        self.write()
        with self.assertRaisesRegex(ValueError, "threshold"):
            self.run_review()
        self.rows[0]["prediction"] = 1
        self.rows[0]["raw_argmax"] = 0
        self.write()
        with self.assertRaisesRegex(ValueError, "argmax"):
            self.run_review()

    def test_invalid_run_or_boolean_prediction_cannot_pass(self):
        self.rows[0]["valid"] = False
        self.write()
        with self.assertRaisesRegex(ValueError, "invalid"):
            self.run_review()
        self.rows[0]["valid"] = True
        self.rows[0]["prediction"] = True
        (self.root / "observations.json").write_text(json.dumps(self.rows))
        with self.assertRaisesRegex(ValueError, "typed binary"):
            self.run_review()

    def test_batch_costs_not_multiplied_or_inferred_from_caps(self):
        report = json.loads((self.root / "report.json").read_text())
        report["summaries"]["full.token"]["cpu_ns"] = 40
        (self.root / "report.json").write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "raw observations"):
            self.run_review()
        self.write()
        self.batches.append(copy.deepcopy(self.batches[0]))
        self.write()
        with self.assertRaisesRegex(ValueError, "unique physical"):
            self.run_review()

    def test_physical_batch_order_and_full_candidate_membership_required(self):
        self.batches[0]["case_ids"] = list(reversed(self.ids_final))
        self.write()
        with self.assertRaisesRegex(ValueError, "order/membership"):
            self.run_review()
        self.batches[0]["case_ids"] = self.ids_final
        self.rows.pop(0)
        self.write()
        with self.assertRaises(ValueError):
            self.run_review()

    def test_missing_entire_question_rejected_even_if_remaining_questions_complete(self):
        self.protocol["final_case_ids"] = self.ids_final[:2]
        self.protocol["final_question_candidate_ids"] = {"0": self.ids_final[:2]}
        self.write()
        with self.assertRaisesRegex(ValueError, "omits official questions"):
            self.run_review()

    def test_previous_evaluation_and_exact_prior_design_bytes_checked(self):
        self.protocol["previous_final_source_hashes"].append(self.sources[("validation", 1)])
        self.protocol["previous_final_case_ids"] += self.ids_final
        self.write()
        with self.assertRaisesRegex(ValueError, "previously evaluated"):
            self.run_review()
        self.protocol["previous_final_source_hashes"].pop()
        self.protocol["previous_final_case_ids"] = self.ids[("validation", 0)]
        self.write()
        self.prior.write_text(self.prior.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "prior design bytes"):
            self.run_review()

    def test_deleted_query_only_effective_features_cannot_be_swapped(self):
        row = next(r for r in self.rows if r["arm"] == "query_only" and r["cohort"] == "full")
        row["feature_sha256"] = self.protocol["public_feature_sha256"]["full"][row["case_id"]]
        self.write()
        with self.assertRaisesRegex(ValueError, "effective input"):
            self.run_review()


if __name__ == "__main__":
    unittest.main()
