"""Hostile source/census/coverage checks; fixtures are NOT model evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from memory_nine_arm_gate import (
    ARMS, POLICY, SCHEMA, audit, canonical, freeze, read_json, read_jsonl, sha,
)


def digest(label):
    return sha(label.encode())


def specimen():
    sources, questions = [], []
    for split in ("train", "calibration", "future_1", "future_2",
                  "ood", "adversarial", "deletion"):
        group = "family-" + split
        source_id = "src:" + split
        sources.append({"group": group, "source_id": source_id,
                        "frame": "[" + source_id + "]\nExample evidence\n"})
        questions.append({"query_id": "q:" + split, "group": group,
                          "split": split, "gold_support_ids": [source_id],
                          "answerable": split not in ("adversarial", "deletion"),
                          "question_sha256": digest("question:" + split)})
    return {"schema": SCHEMA, "sources": sources, "questions": questions}


def metadata():
    return {"reader_sha256": digest("reader"),
            "source_frontier_sha256": digest("live-source-frontier"),
            "forget_frontier_sha256": digest("live-forget-frontier"),
            "arm_specs": {arm: {
                "kind": ARMS[arm], "artifact_sha256": digest("artifact:" + arm),
                "trained_group_ids": (["family-train"] if arm >= "E" else []),
            } for arm in ARMS}}


def receipts(cohort, meta):
    evidence = {(s["group"], s["source_id"]): s["frame"]
                for s in cohort["sources"]}
    result, verdicts = [], []
    for q in cohort["questions"]:
        for arm in ARMS:
            ref = q["gold_support_ids"][0]
            selected = [ref]
            context = evidence[q["group"], ref].encode()
            answer = "candidate answer" if q["answerable"] else ""
            accepted = bool(answer)
            row = {
                "query_id": q["query_id"], "group": q["group"],
                "split": q["split"], "arm": arm,
                "selected_source_ids": selected,
                "context_sha256": sha(context),
                "context_utf8_bytes": len(context),
                "source_frontier_sha256": meta["source_frontier_sha256"],
                "forget_frontier_sha256": meta["forget_frontier_sha256"],
                "reader_sha256": meta["reader_sha256"],
                "artifact_sha256": meta["arm_specs"][arm]["artifact_sha256"],
                "generation_receipt_sha256": digest("fixture:" + arm),
                "execution_kind": "original_model_execution",
                "answer": answer, "answer_sha256": sha(answer.encode()),
                "accepted": accepted,
                "resources": {
                    "wall_ns": 1000, "reader_forwards": int(accepted),
                    "encoder_forwards": int(arm != "A"),
                    "head_forwards": int(arm >= "E"),
                    "peak_rss_bytes": 16384, "resident_artifact_bytes": 2048,
                    "input_tokens": 20, "output_tokens": 2 if accepted else 0,
                },
            }
            result.append(row)
            verdicts.append({
                "query_id": q["query_id"], "arm": arm,
                "answer_sha256": row["answer_sha256"],
                "correct": bool(q["answerable"]),
                "supported": bool(q["answerable"]),
                "judge_id": "synthetic-unit-test-only",
            })
    return result, verdicts


class NineArmGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cohort = specimen()
        self.metadata = metadata()
        self.rows, self.judgments = receipts(self.cohort, self.metadata)
        self.write("cohort.json", self.cohort)
        self.write("metadata.json", self.metadata)
        self.plan_sha = freeze(self.root / "cohort.json",
                               self.root / "metadata.json",
                               self.root / "plan.json")
        self.write_rows()

    def write(self, name, value):
        (self.root / name).write_bytes(canonical(value) + b"\n")

    def write_rows(self):
        for name, data in (("predictions.jsonl", self.rows),
                           ("judgments.jsonl", self.judgments)):
            (self.root / name).write_bytes(
                b"".join(canonical(x) + b"\n" for x in data))

    def check(self, judgments=True):
        return audit(self.root / "plan.json", self.root / "cohort.json",
                     self.root / "predictions.jsonl",
                     self.root / "judgments.jsonl" if judgments else None)

    def test_complete_nine_arm_fixture_is_still_no_go(self):
        report = self.check()
        self.assertEqual(report["coverage"]["expected"], 9 * 7)
        self.assertEqual(report["coverage"]["observed"], 9 * 7)
        self.assertEqual(report["coverage"]["missing"], 0)
        self.assertEqual(report["disposition"], "HOLD_NO_GO")
        self.assertFalse(report["scientific_superiority_certified"])
        self.assertTrue(report["complete"])
        self.assertFalse(report["candidate_effect_thresholds_met"])
        self.assertEqual(len(report["comparisons"]["future_1"]), 10)
        self.assertIn("independently authenticated source, Reader, model and judge attestations absent",
                      report["blockers"])
        self.assertEqual(report["metrics"]["future_1"]["A"]["source_all_support"], 1)
        self.assertFalse(report["production_activation_allowed"])

    def test_freeze_is_exclusive_and_pins_source_byte_identity(self):
        self.assertEqual(self.plan_sha, sha((self.root / "plan.json").read_bytes()))
        with self.assertRaises(FileExistsError):
            freeze(self.root / "cohort.json", self.root / "metadata.json",
                   self.root / "plan.json")
        changed = copy.deepcopy(self.cohort)
        changed["sources"][0]["frame"] = "poison\n"
        self.write("cohort.json", changed)
        with self.assertRaisesRegex(ValueError, "plan/policy/source pin mismatch"):
            self.check()

    def test_missing_arm_execution_cannot_be_hidden_as_success(self):
        self.rows.pop()
        self.write_rows()
        report = self.check()
        self.assertFalse(report["complete"])
        self.assertEqual(report["coverage"]["missing"], 1)
        self.assertTrue(any("missing 1 original" in x for x in report["blockers"]))

    def test_duplicate_execution_is_rejected(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "duplicate query/arm"):
            self.check()

    def test_model_implementation_cannot_be_relabelled(self):
        self.rows[0]["execution_kind"] = "synthetic_fixture"
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "mock/replay"):
            self.check()
        self.rows[0]["execution_kind"] = "original_model_execution"
        self.rows[0]["artifact_sha256"] = digest("wrong")
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "unregistered"):
            self.check()

    def test_reader_generation_and_forget_frontiers_are_bound(self):
        for field, expected in (
            ("reader_sha256", "Reader or live"),
            ("source_frontier_sha256", "Reader or live"),
            ("forget_frontier_sha256", "Reader or live"),
        ):
            with self.subTest(field=field):
                original = self.rows[0][field]
                self.rows[0][field] = digest("stale")
                self.write_rows()
                with self.assertRaisesRegex(ValueError, expected):
                    self.check()
                self.rows[0][field] = original

    def test_cross_scope_or_fake_context_is_rejected(self):
        self.rows[0]["selected_source_ids"] = ["src:future_1"]
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "cross-group"):
            self.check()
        self.rows[0]["selected_source_ids"] = ["src:train"]
        self.rows[0]["context_sha256"] = digest("fabricated")
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "source-frame context changed"):
            self.check()

    def test_claimed_success_cannot_replace_independent_judgments(self):
        self.judgments[0]["correct"] = 1
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "unbound or fake"):
            self.check()
        self.judgments[0]["correct"] = False
        self.judgments[0]["answer_sha256"] = digest("fake answer")
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "unbound or fake"):
            self.check()
        self.judgments[0]["answer_sha256"] = self.rows[0]["answer_sha256"]
        self.write_rows()
        self.assertIn("missing sealed independent answer judgments",
                      self.check(judgments=False)["blockers"])

    def test_cost_token_count_and_boolean_type_are_strict(self):
        cases = [
            ("accepted", 1, "strict Boolean"),
            ("context_utf8_bytes", 0, "source-frame context"),
            ("answer_sha256", digest("fake"), "answer bytes"),
        ]
        for name, mutation, pattern in cases:
            with self.subTest(name=name):
                old = self.rows[0][name]
                self.rows[0][name] = mutation
                self.write_rows()
                with self.assertRaisesRegex(ValueError, pattern):
                    self.check()
                self.rows[0][name] = old
        self.rows[0]["resources"]["output_tokens"] = POLICY["max_reader_output_tokens"] + 1
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "Reader token"):
            self.check()

    def test_training_on_future_groups_and_source_group_overlap_fail(self):
        altered = copy.deepcopy(self.metadata)
        altered["arm_specs"]["I"]["trained_group_ids"] = ["family-future_2"]
        self.write("metadata.json", altered)
        (self.root / "alternate-plan.json").write_bytes(canonical({
            **read_json(self.root / "plan.json"), "arm_specs": altered["arm_specs"]
        }) + b"\n")
        with self.assertRaisesRegex(ValueError, "trained on holdout"):
            audit(self.root / "alternate-plan.json", self.root / "cohort.json",
                  self.root / "predictions.jsonl", self.root / "judgments.jsonl")
        changed = copy.deepcopy(self.cohort)
        changed["questions"][1]["group"] = changed["questions"][0]["group"]
        changed["questions"][1]["split"] = "future_1"
        self.write("overlap-cohort.json", changed)
        with self.assertRaisesRegex(ValueError, "same source family crosses"):
            freeze(self.root / "overlap-cohort.json", self.root / "metadata.json",
                   self.root / "overlap-plan.json")

    def test_json_duplicate_key_and_incomplete_spec_rejected(self):
        (self.root / "duplicate.json").write_text('{"a":1,"a":2}', encoding="utf8")
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            read_json(self.root / "duplicate.json")
        reduced = copy.deepcopy(self.metadata)
        del reduced["arm_specs"]["C"]
        self.write("bad-metadata.json", reduced)
        with self.assertRaisesRegex(ValueError, "A-I arm manifest"):
            freeze(self.root / "cohort.json", self.root / "bad-metadata.json",
                   self.root / "new-plan.json")

    def test_bare_replayed_receipts_do_not_count_as_physical_work(self):
        self.rows[0]["resources"]["reader_forwards"] = 0
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "physical Reader"):
            self.check()


if __name__ == "__main__":
    unittest.main()
