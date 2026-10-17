"""Author-made source/journal fixtures; do not relabel as original model output."""

from pathlib import Path
import copy
import tempfile
import unittest

import associative_graph_causal as graph
import reader_citation_protocol as upstream
import reader_citation_grounding as grounding


class BoundPostsealContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan_dir, self.run_dir = self.root / "plan", self.root / "run"
        self.plan_dir.mkdir()
        self.run_dir.mkdir()
        self.entries = []
        self.journal = []
        for family_no in range(10):
            family = f"conv-{family_no}"
            for arm in upstream.ARMS:
                evidence = [{"label": "E1", "source_id": f"D{family_no}:1",
                             "text": "The original supervisor replaced the previous controller after two failed deployments."}]
                entry = {"family": family, "question_id": f"{family}/q0000",
                         "arm": arm, "question": "What happened to the controller?",
                         "evidence": evidence}
                self.entries.append(entry)
                self.journal.append({
                    "question_id": entry["question_id"], "arm": arm, "family": family,
                    "source_ids": [e["source_id"] for e in evidence],
                    "prompt_sha256": graph.digest(upstream._user_text(entry).encode()),
                    "result": {"status": "succeeded",
                               "answer": '"The original supervisor replaced the previous controller" [E1]',
                               "answer_postprocessed": False},
                })
        self.plan = {
            "schema": upstream.SCHEMA,
            "parent_plan_sha256": "f" * 64,
            "original_source_sha256": graph.DATASET_SHA256,
            "source_annotations_are_not_semantic_sufficiency": True,
            "answers_in_worker": False, "production_accepted": False,
            "rows": self.entries,
        }
        upstream.validate(self.plan)
        self.plan_hash = graph.create_only(self.plan_dir / "plan.json", self.plan)
        graph.create_only(self.plan_dir / "seal.json", {
            "schema": upstream.SCHEMA, "sha256": self.plan_hash,
            "planned": 40, "production_accepted": False,
        })
        self.journal_sha = graph.create_only(self.run_dir / "journal.json", self.journal)
        self.runseal = {"schema": upstream.SCHEMA, "plan_sha256": self.plan_hash,
                        "journal_sha256": self.journal_sha,
                        "reader_identity": "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c",
                        "reader_parity_certified": False, "planned": 40,
                        "max_generated_tokens": upstream.MAX_TOKENS,
                        "answers_in_worker": False, "production_accepted": False}
        graph.create_only(self.run_dir / "seal.json", self.runseal)
        self.review = {"schema": upstream.SCHEMA,
                       "plan_sha256": self.plan_hash,
                       "original_reader_sha256": self.journal_sha,
                       "replayed_model_calls": 40,
                       "planned": 40,
                       "citation_labels_are_not_semantic_entailment": True,
                       "production_accepted": False}
        self.review_file = self.root / "synthetic-replay-claim.json"
        graph.create_only(self.review_file, self.review)

    def test_full_count_and_no_fabricated_semantic_judgments(self):
        result = grounding.audit(self.plan_dir, self.run_dir, self.review_file,
                                 self.root / "independent-mechanical")
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["semantic_entailment_completed"])
        packet = graph.strict_load(graph.regular_bytes(
            self.root / "independent-mechanical" / "grounding-report.json"))
        worklist = graph.strict_load(graph.regular_bytes(
            self.root / "independent-mechanical" / "blinded-worklist.json"))
        self.assertEqual(packet["succeeded_for_blinded_review"], 40)
        self.assertEqual(len(worklist["cases"]), 40)
        self.assertEqual(packet["external_independent_reviewer_count"], 0)
        self.assertIsNone(packet["citation_entailment_precision"])
        self.assertTrue(all(x["independent_support_judgment"] is None for x in worklist["cases"]))
        self.assertTrue(all(x["status"] == "awaiting_external_adjudication" for x in worklist["cases"]))
        self.assertEqual({v["planned"] for v in packet["by_arm"].values()}, {10})
        with self.assertRaises(FileExistsError):
            grounding.audit(self.plan_dir, self.run_dir, self.review_file,
                            self.root / "independent-mechanical")

    def test_changed_and_resealed_model_answer_cannot_reuse_old_replay_receipt(self):
        changed = copy.deepcopy(self.journal)
        changed[0]["result"]["answer"] = "Fabricated unsupported answer [E1]"
        (self.run_dir / "journal.json").write_bytes(graph.canonical(changed))
        self.runseal["journal_sha256"] = graph.digest(
            (self.run_dir / "journal.json").read_bytes())
        (self.run_dir / "seal.json").write_bytes(graph.canonical(self.runseal))
        with self.assertRaisesRegex(ValueError, "verified exact-plan original Reader replay"):
            grounding.audit(self.plan_dir, self.run_dir, self.review_file,
                            self.root / "denied-changed-answer")

    def test_self_resealed_changed_source_cannot_reuse_old_plan_receipt(self):
        changed = copy.deepcopy(self.plan)
        changed["rows"][0]["evidence"][0]["text"] = "A different unsupported memory."
        for arm_entry in changed["rows"][:4]:
            arm_entry["evidence"][0]["text"] = "A different unsupported memory."
        upstream.validate(changed)
        (self.plan_dir / "plan.json").write_bytes(graph.canonical(changed))
        seal = {"schema": upstream.SCHEMA,
                "sha256": graph.digest((self.plan_dir / "plan.json").read_bytes()),
                "planned": 40, "production_accepted": False}
        (self.plan_dir / "seal.json").write_bytes(graph.canonical(seal))
        with self.assertRaises(ValueError):
            grounding.audit(self.plan_dir, self.run_dir, self.review_file,
                            self.root / "denied-source-mutation")


if __name__ == "__main__":
    unittest.main()
