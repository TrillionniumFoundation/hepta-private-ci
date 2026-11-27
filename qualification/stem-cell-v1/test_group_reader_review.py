import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from group_reader_review import _digest, review, score_multirc


class ReaderReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.sources = self.folder / "source"
        self.sources.mkdir()
        records = {}
        for name, text in (("train.jsonl", "Train paragraph."), ("val.jsonl", "Heldout paragraph.")):
            record = dict(idx=0, passage=dict(text=text, questions=[dict(idx=0, question="Question?", answers=[
                dict(idx=0, text="Positive", label=1), dict(idx=1, text="Negative", label=0)])]))
            (self.sources / name).write_text(json.dumps(record) + "\n")
            records[name] = record
        self.source = hashlib.sha256(b"Heldout paragraph.").hexdigest()
        train_source = hashlib.sha256(b"Train paragraph.").hexdigest()
        self.ids = [json.dumps(["validation", "0", "0", str(a)], separators=(",", ":")) for a in range(2)]
        (self.folder / "reader.py").write_text("# frozen fixture\n")
        self.protocol = dict(schema="reader.v1", source_sha256={"reader.py": hashlib.sha256(b"# frozen fixture\n").hexdigest()},
            dataset_files_sha256={n: hashlib.sha256((self.sources / n).read_bytes()).hexdigest() for n in records},
            partitions={"train": [train_source], "final": [self.source]}, final_case_ids=self.ids,
            final_question_candidate_ids={"question-0": self.ids}, expected_arms=["static", "ndu"],
            expected_cohorts=["final"], selected_hyperparameters={"width": 8}, training_majority_prediction=0)
        self.rows = [dict(case_id=case, paragraph_id="0", question_id="0", answer_id=str(a),
            source_hash=self.source, cohort="final", arm=arm, prediction=1-a, target=1-a,
            valid=True, status="completed", steps=1, cpu_ns=10, wall_ns=20, formula_flops=None,
            model_sha256=("a" if arm == "static" else "b") * 64,
            feature_sha256=hashlib.sha256(case.encode()).hexdigest(), protocol_sha256=_digest(self.protocol))
            for arm in ("static", "ndu") for a, case in enumerate(self.ids)]
        self.write()

    def write(self):
        summaries = {}
        for row in self.rows:
            row["protocol_sha256"] = _digest(self.protocol)
        for cohort in self.protocol["expected_cohorts"]:
            for arm in self.protocol["expected_arms"]:
                selected = [r for r in self.rows if r["arm"] == arm and r["cohort"] == cohort]
                summary = score_multirc(selected)
                summary.update({key: sum(r[key] for r in selected) for key in ("steps", "cpu_ns", "wall_ns")})
                summary["formula_flops"] = None
                for key in ("native_child_cpu_ns", "native_subprocess_wall_ns", "total_online_cpu_ns"):
                    if any(key in r for r in selected):
                        summary[key] = sum(r[key] for r in selected) if all(r.get(key) is not None for r in selected) else None
                summaries[cohort + "." + arm] = summary
        for name, value in (("protocol.json", self.protocol), ("observations.json", self.rows),
                            ("report.json", dict(protocol_sha256=_digest(self.protocol), summaries=summaries))):
            (self.folder / name).write_text(json.dumps(value))

    def run_review(self):
        return review(self.folder, source_dir=self.sources, code_dir=self.folder)

    def test_independent_labels_complete_questions_and_actual_null_costs(self):
        receipt = self.run_review()
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["summaries"]["final.ndu"]["f1_a"], 1.)
        self.assertIsNone(receipt["summaries"]["final.ndu"]["formula_flops"])

    def test_global_answer_f1_is_not_question_average(self):
        rows = [dict(case_id=str(i), source_hash="p", question_id="q1" if i == 0 else "q2",
                     target=int(i < 4), prediction=int(i == 0)) for i in range(5)]
        metrics = score_multirc(rows, majority_prediction=1)
        self.assertEqual(metrics["f1_a"], .4)
        self.assertEqual(metrics["exact_match"], .5)
        self.assertEqual(metrics["confusion"], dict(tp=1, fp=0, fn=3, tn=1))
        self.assertEqual(metrics["baselines"]["all_positive"]["f1_a"], 8/9)
        negatives = [dict(case_id="0", source_hash="p", question_id="q", target=0, prediction=0)]
        self.assertEqual(score_multirc(negatives)["f1_a"], 0.)

    def test_missing_answer_cannot_manipulate_question_exact_match(self):
        self.protocol["final_case_ids"] = self.ids[:1]
        self.protocol["final_question_candidate_ids"] = {"q": self.ids[:1]}
        self.rows = [r for r in self.rows if r["case_id"] == self.ids[0]]
        self.write()
        with self.assertRaisesRegex(ValueError, "omits"):
            self.run_review()

    def test_question_ids_do_not_merge_across_paragraphs_and_source_bytes_are_pinned(self):
        rows = [dict(case_id=json.dumps(["validation", str(i), "0", "0"]), source_hash="same",
                     paragraph_id=str(i), question_id="0", target=1, prediction=1-i) for i in range(2)]
        self.assertEqual(score_multirc(rows)["questions"], 2)
        self.assertEqual(score_multirc(rows)["exact_match"], .5)
        path = self.sources / "val.jsonl"
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            self.run_review()

    def test_leakage_changed_source_and_changed_target_reject(self):
        self.protocol["partitions"]["train"].append(self.source)
        self.write()
        with self.assertRaisesRegex(ValueError, "leaked"):
            self.run_review()
        self.protocol["partitions"]["train"].pop()
        self.rows[0]["target"] = 0
        self.write()
        with self.assertRaises(ValueError):
            self.run_review()

    def test_caps_are_not_actual_costs_and_invalid_runs_are_not_dropped(self):
        report = json.loads((self.folder / "report.json").read_text())
        report["summaries"]["final.ndu"]["formula_flops"] = 10**9
        (self.folder / "report.json").write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "consumption"):
            self.run_review()
        self.rows[0]["valid"] = False
        self.write()
        with self.assertRaisesRegex(ValueError, "invalid/fallback"):
            self.run_review()

    def test_query_only_uses_registered_deleted_features_in_every_cohort(self):
        self.protocol["expected_arms"] = ["static", "query_only"]
        self.protocol["expected_cohorts"] = ["full", "deleted", "permuted"]
        self.protocol["arm_input_transforms"] = dict(static="identity", query_only="delete_evidence")
        self.protocol["public_feature_sha256"] = {
            cohort: {case: _digest([cohort, case]) for case in self.ids}
            for cohort in self.protocol["expected_cohorts"]}
        originals, self.rows = copy.deepcopy(self.rows), []
        for cohort in self.protocol["expected_cohorts"]:
            for row in originals:
                row = copy.deepcopy(row)
                row["cohort"] = cohort
                if row["arm"] == "ndu":
                    row["arm"] = "query_only"
                effective = "deleted" if row["arm"] == "query_only" else cohort
                row["feature_sha256"] = self.protocol["public_feature_sha256"][effective][row["case_id"]]
                self.rows.append(row)
        self.write()
        self.assertTrue(self.run_review()["passed"])
        wrong = next(r for r in self.rows if r["cohort"] == "full" and r["arm"] == "query_only")
        wrong["feature_sha256"] = self.protocol["public_feature_sha256"]["full"][wrong["case_id"]]
        self.write()
        with self.assertRaisesRegex(ValueError, "effective input"):
            self.run_review()

    def test_native_cpu_unknown_propagates_and_wall_cannot_be_double_charged(self):
        for row in self.rows:
            row.update(native_child_cpu_ns=5, native_subprocess_wall_ns=2, total_online_cpu_ns=15)
        self.rows[0].update(native_child_cpu_ns=None, total_online_cpu_ns=None)
        self.write()
        receipt = self.run_review()
        self.assertIsNone(receipt["summaries"]["final.static"]["total_online_cpu_ns"])
        self.assertEqual(receipt["summaries"]["final.ndu"]["total_online_cpu_ns"], 30)
        self.rows[0]["total_online_cpu_ns"] = 10
        self.write()
        with self.assertRaisesRegex(ValueError, "remain null"):
            self.run_review()
        self.rows[0]["total_online_cpu_ns"] = None
        self.rows[0]["native_subprocess_wall_ns"] = 21
        self.write()
        with self.assertRaisesRegex(ValueError, "subset"):
            self.run_review()


if __name__ == "__main__":
    unittest.main()
