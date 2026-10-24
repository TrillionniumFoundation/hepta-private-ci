"""Preserve actual LoCoMo retrieval outcomes and reject inflated nine-arm claims."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from memory_nine_arm_existing_evidence import CODE_DIR, EVIDENCE_DIR, recount
from memory_nine_arm_gate import Refused


def copied():
    tmp = tempfile.TemporaryDirectory()
    d = Path(tmp.name)
    for name in ("plan.json", "selection.json", "report.json"):
        (d / name).write_bytes((EVIDENCE_DIR / name).read_bytes())
    return tmp, d


class ActualRetainedEvidenceTests(unittest.TestCase):
    def test_recount_real_retained_report_stays_negative(self):
        data = recount()
        self.assertEqual(data["status"], "HOLD_NO_GO")
        self.assertEqual(set(data["other_arms"]), set("BCEFGHI"))
        self.assertEqual(data["reader_answers_generated"], 0)
        self.assertEqual(data["adversarial_questions_accepted"], 299)
        self.assertLess(data["multi_hop_all_support_regression"], 0)
        self.assertGreater(data["A_to_D_group_macro_support_delta"], 0)
        self.assertFalse(data["superiority_established"])

    def test_historical_recount_does_not_roll_back_current_scorer(self):
        # The current scorer has the later paired-cohort correction. It must
        # remain distinct from the producer that generated the retained report.
        self.assertEqual(recount()["status"], "HOLD_NO_GO")
        with self.assertRaisesRegex(Refused, "original producer source modified"):
            recount(code_dir=Path(__file__).parent)

    def test_archived_producer_tampering_remains_refused(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for source in CODE_DIR.glob("*.py"):
                (root / source.name).write_bytes(source.read_bytes())
            source = root / "memory_retrieval_scoring.py"
            source.write_bytes(source.read_bytes() + b"\n# not original bytes\n")
            with self.assertRaisesRegex(Refused, "original producer source modified"):
                recount(code_dir=root)

    def test_cannot_relabel_retrieval_as_answer_correctness(self):
        tmp, root = copied()
        with tmp:
            p = root / "report.json"
            value = json.loads(p.read_bytes())
            value["boundaries"]["answer_correctness_measured"] = True
            p.write_text(json.dumps(value))
            with self.assertRaisesRegex(Refused, "retrieval-only evidence relabeled"):
                recount(root)

    def test_cannot_hide_original_adversarial_failures(self):
        tmp, root = copied()
        with tmp:
            p = root / "report.json"
            value = json.loads(p.read_bytes())
            value["results"]["evaluation"]["episodic_context"]["overall"][
                "answerability_balanced_accuracy"] = 1
            p.write_text(json.dumps(value))
            with self.assertRaisesRegex(Refused, "adversarial failure silently repaired"):
                recount(root)

    def test_cannot_relabel_six_dialogues_as_large_source_census(self):
        tmp, root = copied()
        with tmp:
            p = root / "report.json"
            value = json.loads(p.read_bytes())
            value["paired_evaluation"]["episodic_minus_strong_sparse"]["groups"] = 200
            p.write_text(json.dumps(value))
            with self.assertRaisesRegex(Refused, "original paired low-power result changed"):
                recount(root)

    def test_cannot_hide_retained_flat_category_multi_hop_regression(self):
        tmp, root = copied()
        with tmp:
            p = root / "report.json"
            value = json.loads(p.read_bytes())
            value["results"]["evaluation"]["episodic_context"]["by_category"]["1"][
                "all_support_recalled"] = 1
            p.write_text(json.dumps(value))
            with self.assertRaisesRegex(Refused, "original multi-hop regression hidden"):
                recount(root)

    def test_no_plan_mutation_without_changing_pin(self):
        tmp, root = copied()
        with tmp:
            p = root / "plan.json"
            value = json.loads(p.read_bytes())
            value["questions"] += 1
            p.write_text(json.dumps(value))
            with self.assertRaisesRegex(Refused, "original source-first plan hash drift"):
                recount(root)

    def test_no_fake_positive_from_changed_task_metric(self):
        tmp, root = copied()
        with tmp:
            p = root / "report.json"
            value = json.loads(p.read_bytes())
            value["results"]["evaluation"]["episodic_context"]["overall"][
                "group_macro_all_support"] = 1
            p.write_text(json.dumps(value))
            with self.assertRaisesRegex(Refused, "original paired low-power result changed"):
                recount(root)


if __name__ == "__main__":
    unittest.main()
