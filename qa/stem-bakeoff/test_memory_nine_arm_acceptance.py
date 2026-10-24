"""Independent failure-mode tests for the A-I historical Memory acceptance gate.

Fixtures are synthetic and never qualify real models, LoCoMo outcomes or a release.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from memory_nine_arm_acceptance import (
    ARMS, MANIFEST_SCHEMA, PARTITIONS, ROW_SCHEMA, SCHEMA, SOURCE_SCHEMA,
    AdmissionError, adjudicate, check_manifests, check_plan, freeze_plan,
    read_json, seal, sha, canonical, validate_attempts, _signflip_exact,
)
from memory_retrieval_data import Corpus, Gold, Query, Turn, SOURCE_SHA256


class MemoryNineArmAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.corpora, self.queries, self.gold = {}, [], {}
        self.public = {
            "schema": SOURCE_SCHEMA, "source_sha256": SOURCE_SHA256,
            "turns": {}, "queries": {},
        }
        for group in sum(PARTITIONS.values(), []):
            turn = Turn("D1:1", "session_1", 0, "Ada", "2023-01-01",
                        f"Public observation in {group}.", False)
            qid = f"{group}:qa:0000"
            query = Query(qid, group, "When did Ada report this observation?")
            self.corpora[group] = Corpus(group, (turn,))
            self.queries.append(query)
            self.gold[qid] = Gold(2, ("D1:1",), (), False)
            self.public["turns"][group] = [{
                "source_id": turn.source_id, "frame": turn.render(),
            }]
            self.public["queries"][qid] = {
                "group": group, "text": query.text,
            }
        self.plan = {
            "schema": SCHEMA, "source_sha256": SOURCE_SHA256,
            "parent_plan_sha256": "62216f4a7b69fb9f27e087b49daa5249bfb485e99ef96b88123d8fb8b025ff2f",
            "public_projection_sha256": sha(canonical(self.public)),
            "partitions": PARTITIONS, "query_ids": list(self.public["queries"]),
            "arms": ARMS,
            "comparisons": [["D", "C"], ["E", "D"], ["F", "E"],
                            ["G", "F"], ["H", "G"], ["I", "H"],
                            ["I", "B"], ["I", "C"]],
            "max_turns": 8, "max_context_bytes": 4096,
            "reader_artifact_sha256": "a" * 64,
            "tokenizer_sha256": "b" * 64,
            "prompt_sha256": "c" * 64,
            "source_frontier_sha256": "d" * 64,
            "forget_frontier_sha256": "e" * 64,
            "max_reader_input_tokens": 1024,
            "max_reader_output_tokens": 64,
            "reference_dataset_previously_examined": True,
            "genuinely_future_holdout": False,
            "original_answer_correctness_available": False,
            "source_independence_authenticated": False,
            "production_activation_allowed": False,
            "authority": "DENY_ALL",
        }
        self.manifests = {
            "schema": MANIFEST_SCHEMA,
            "plan_sha256": sha(canonical(self.plan)),
            "arms": [],
        }
        self.by_arm = {}
        for arm in ARMS:
            payload = canonical({"fixture": arm, "not_real_trained_weights": True})
            file = self.artifacts / f"{arm}.json"
            file.write_bytes(payload)
            files = [{
                "path": file.name, "sha256": sha(payload),
                "bytes": len(payload),
            }]
            m = {
                "arm": arm, "model_artifact_sha256": sha(canonical(files)),
                "shared_encoder_sha256": "f" * 64,
                "training_groups": ["conv-30"] if arm in "EFGHI" else [],
                "calibration_groups": ["conv-26"],
                "head_training_steps": 1 if arm in "EFGHI" else 0,
                "router_training_steps": 1 if arm in "GHI" else 0,
                "graph_training_steps": 1 if arm in "HI" else 0,
                "trained_heads": 2 if arm in "FGHI" else 1 if arm == "E" else 0,
                "split_count": 1 if arm == "I" else 0,
                "merge_count": 1 if arm == "I" else 0,
                "files": files,
            }
            self.manifests["arms"].append(m)
            self.by_arm[arm] = m
        self.rows = []
        for arm in ARMS:
            for query in self.queries:
                frame = self.public["turns"][query.group][0]["frame"]
                context_digest = sha(frame.encode())
                runtime = {
                    k: 0 for k in (
                        "wall_ns", "peak_rss_bytes", "resident_tensor_bytes",
                        "encoder_forwards", "dense_forwards", "reranker_forwards",
                        "typed_lookups", "head_forwards", "router_forwards",
                        "graph_traversals", "reader_forwards", "reader_input_tokens",
                        "reader_output_tokens",
                    )
                }
                runtime.update(wall_ns=12345, peak_rss_bytes=1048576,
                               resident_tensor_bytes=2048,
                               reader_forwards=1, reader_input_tokens=50,
                               reader_output_tokens=4)
                if arm == "B":
                    runtime.update(dense_forwards=1, reranker_forwards=1,
                                   encoder_forwards=1)
                if arm in "CHI":
                    runtime["graph_traversals"] = 1
                if arm in "DEFGHI":
                    runtime["typed_lookups"] = 1
                if arm in "EFGHI":
                    runtime["head_forwards"] = 1
                    runtime["encoder_forwards"] = 1
                if arm in "GHI":
                    runtime["router_forwards"] = 1
                record = {
                    "schema": ROW_SCHEMA,
                    "plan_sha256": sha(canonical(self.plan)),
                    "arm": arm, "query_id": query.query_id,
                    "group": query.group,
                    "model_artifact_sha256": self.by_arm[arm]["model_artifact_sha256"],
                    "reader_artifact_sha256": self.plan["reader_artifact_sha256"],
                    "reader_request_digest": sha(canonical({
                        "domain": "hepta.memory-nine-arm-reader-request.v1",
                        "query_id": query.query_id,
                        "question": query.text,
                        "context_sha256": context_digest,
                        "reader": self.plan["reader_artifact_sha256"],
                        "tokenizer": self.plan["tokenizer_sha256"],
                        "prompt": self.plan["prompt_sha256"],
                    })),
                    "source_frontier_sha256": self.plan["source_frontier_sha256"],
                    "forget_frontier_sha256": self.plan["forget_frontier_sha256"],
                    "selected_ids": ["D1:1"],
                    "context_sha256": context_digest,
                    "context_bytes": len(frame.encode()),
                    "status": "accepted", "answer": "A fixture, not a prediction.",
                    "runtime": runtime,
                }
                self.rows.append(record)
        self.attempts = self.root / "attempts.jsonl"
        self._rewrite()
        self.seal_path = self.root / "seal.json"

    def _rewrite(self):
        self.attempts.write_bytes(b"".join(canonical(row) + b"\n" for row in self.rows))

    def _validate(self):
        self._rewrite()
        return validate_attempts(
            self.plan, self.public, self.manifests, self.artifacts,
            self.attempts, require_original=False)

    def test_actual_physical_fixture_census_and_seal_without_gold(self):
        rows, totals = self._validate()
        self.assertEqual(len(rows), len(ARMS) * len(self.queries))
        self.assertEqual(totals["B"]["dense_forwards"], len(self.queries))
        with patch("memory_nine_arm_acceptance.load_source",
                   side_effect=AssertionError("seal must never load original gold")):
            receipt = seal(self.plan, self.public, self.manifests, self.artifacts,
                           self.attempts, self.seal_path, require_original=False)
        self.assertFalse(receipt["gold_opened"])
        self.assertEqual(read_json(self.seal_path)["question_arm_rows"], 90)

    def test_fixture_scoring_always_holds_no_go(self):
        self._validate()
        seal(self.plan, self.public, self.manifests, self.artifacts,
             self.attempts, self.seal_path, require_original=False)
        with patch("memory_nine_arm_acceptance.load_source",
                   return_value=(self.corpora, tuple(self.queries), self.gold)):
            report = adjudicate(
                self.plan, self.public, self.manifests, self.artifacts,
                self.attempts, self.seal_path, "unused",
                require_original=False)
        self.assertEqual(report["evaluation_question_census"], 6)
        self.assertEqual(report["decision"], "HOLD_NO_GO")
        self.assertFalse(report["superiority_established"])
        self.assertEqual(len(report["comparisons"]), 8)
        self.assertTrue(all(c["holm_adjusted_p"] >= c["one_sided_exact_signflip_p_unadjusted"]
                            for c in report["comparisons"]))

    def test_missing_arm_or_query_not_silently_excluded(self):
        self.rows.pop()
        with self.assertRaisesRegex(AdmissionError, "all nine arms"):
            self._validate()

    def test_duplicate_attempt_rejected(self):
        self.rows.append(deepcopy(self.rows[-1]))
        with self.assertRaisesRegex(AdmissionError, "duplicate prediction"):
            self._validate()

    def test_no_gold_or_fabricated_scoring_fields(self):
        self.rows[0]["all_support_recalled"] = 1
        with self.assertRaisesRegex(AdmissionError, "unknown/forged row"):
            self._validate()

    def test_source_identity_and_scope_cannot_shift(self):
        self.rows[0]["selected_ids"] = ["other-group-evidence"]
        with self.assertRaisesRegex(AdmissionError, "evidence reference"):
            self._validate()

    def test_forget_frontier_staleness_rejected(self):
        self.rows[0]["forget_frontier_sha256"] = "0" * 64
        with self.assertRaisesRegex(AdmissionError, "forget frontier"):
            self._validate()

    def test_reader_identity_cannot_be_swapped(self):
        self.rows[0]["reader_artifact_sha256"] = "0" * 64
        with self.assertRaisesRegex(AdmissionError, "Reader/prompt"):
            self._validate()

    def test_reader_request_digest_binds_question_prompt_and_context(self):
        self.rows[0]["reader_request_digest"] = "0" * 64
        with self.assertRaisesRegex(AdmissionError, "Reader/prompt"):
            self._validate()

    def test_partial_or_forged_context_rejected(self):
        self.rows[0]["context_bytes"] -= 1
        with self.assertRaisesRegex(AdmissionError, "Reader context"):
            self._validate()

    def test_unmeasured_reader_budget_rejected(self):
        self.rows[0]["runtime"]["reader_input_tokens"] = 8192
        with self.assertRaisesRegex(AdmissionError, "Reader/cost"):
            self._validate()

    def test_fake_dense_does_not_pass_as_physical_b(self):
        for row in self.rows:
            if row["arm"] == "B":
                row["runtime"]["dense_forwards"] = 0
        with self.assertRaisesRegex(AdmissionError, "per-question mechanism: B"):
            self._validate()

    def test_fake_graph_does_not_pass_as_physical_c(self):
        for row in self.rows:
            if row["arm"] == "C":
                row["runtime"]["graph_traversals"] = 0
        with self.assertRaisesRegex(AdmissionError, "per-question mechanism: C"):
            self._validate()

    def test_one_b_row_cannot_borrow_other_rows_reranker_work(self):
        row = next(x for x in self.rows if x["arm"] == "B")
        row["runtime"]["reranker_forwards"] = 0
        with self.assertRaisesRegex(AdmissionError, "per-question mechanism: B"):
            self._validate()

    def test_one_h_row_cannot_borrow_other_rows_graph_work(self):
        row = next(x for x in self.rows if x["arm"] == "H")
        row["runtime"]["graph_traversals"] = 0
        with self.assertRaisesRegex(AdmissionError, "per-question mechanism: H"):
            self._validate()

    def test_valid_early_abstention_does_not_require_graph_execution(self):
        row = next(x for x in self.rows if x["arm"] == "H")
        row["status"] = "abstained"
        row["answer"] = ""
        row["runtime"]["graph_traversals"] = 0
        row["runtime"]["reader_forwards"] = 0
        row["runtime"]["reader_output_tokens"] = 0
        rows, totals = self._validate()
        self.assertEqual(len(rows), len(ARMS) * len(self.queries))
        self.assertEqual(totals["H"]["graph_traversals"], len(self.queries) - 1)

    def test_fake_learning_steps_rejected_for_head_router_and_graph(self):
        for arm, field in (("E", "head_training_steps"),
                           ("G", "router_training_steps"),
                           ("H", "graph_training_steps")):
            with self.subTest(arm=arm):
                m = self.by_arm[arm]
                value = m[field]
                m[field] = 0
                with self.assertRaises(AdmissionError):
                    self._validate()
                m[field] = value

    def test_topology_requires_both_split_and_merge(self):
        self.by_arm["I"]["merge_count"] = 0
        with self.assertRaisesRegex(AdmissionError, "split and merge"):
            self._validate()

    def test_learning_and_calibration_cannot_include_heldout_group(self):
        self.by_arm["F"]["training_groups"].append("conv-47")
        with self.assertRaisesRegex(AdmissionError, "contamination"):
            self._validate()

    def test_corrupt_real_artifact_bytes_rejected(self):
        file = self.artifacts / "E.json"
        file.write_bytes(b"changed")
        with self.assertRaises(AdmissionError):
            self._validate()

    def test_path_escape_and_symlink_artifact_rejected(self):
        m = self.by_arm["A"]
        m["files"][0]["path"] = "../escape"
        with self.assertRaisesRegex(AdmissionError, "escapes root"):
            self._validate()
        m["files"][0]["path"] = "A.json"
        (self.artifacts / "A.json").unlink()
        (self.artifacts / "A.json").symlink_to(self.artifacts / "B.json")
        with self.assertRaises(AdmissionError):
            self._validate()

    def test_attempt_mutation_after_seal_refused_before_gold(self):
        self._validate()
        seal(self.plan, self.public, self.manifests, self.artifacts,
             self.attempts, self.seal_path, require_original=False)
        self.rows[0]["answer"] = "changed after sealing"
        self._rewrite()
        with patch("memory_nine_arm_acceptance.load_source",
                   side_effect=AssertionError("gold opened too early")):
            with self.assertRaisesRegex(AdmissionError, "sealed predictions"):
                adjudicate(self.plan, self.public, self.manifests,
                           self.artifacts, self.attempts, self.seal_path,
                           "unused", require_original=False)

    def test_seal_resource_counters_cannot_be_rewritten_before_scoring(self):
        self._validate()
        seal(self.plan, self.public, self.manifests, self.artifacts,
             self.attempts, self.seal_path, require_original=False)
        forged = read_json(self.seal_path)
        forged["resource_totals"]["B"]["dense_forwards"] = 0
        self.seal_path.write_bytes(canonical(forged) + b"\n")
        with patch("memory_nine_arm_acceptance.load_source",
                   side_effect=AssertionError("gold opened before seal census")):
            with self.assertRaisesRegex(AdmissionError, "postseal resource census"):
                adjudicate(self.plan, self.public, self.manifests, self.artifacts,
                           self.attempts, self.seal_path, "unused",
                           require_original=False)

    def test_seal_question_count_fabrication_rejected(self):
        self._validate()
        seal(self.plan, self.public, self.manifests, self.artifacts,
             self.attempts, self.seal_path, require_original=False)
        forged = read_json(self.seal_path)
        forged["question_arm_rows"] += 1
        self.seal_path.write_bytes(canonical(forged) + b"\n")
        with patch("memory_nine_arm_acceptance.load_source",
                   side_effect=AssertionError("gold opened before seal census")):
            with self.assertRaisesRegex(AdmissionError, "postseal resource census"):
                adjudicate(self.plan, self.public, self.manifests, self.artifacts,
                           self.attempts, self.seal_path, "unused",
                           require_original=False)

    def test_duplicate_json_key_rejected_without_parser_last_write_wins(self):
        file = self.root / "double.json"
        file.write_text('{"arm":"A","arm":"I"}')
        with self.assertRaisesRegex(AdmissionError, "duplicate JSON"):
            read_json(file)

    def test_no_zero_group_independence_or_qualification_by_default(self):
        self.assertAlmostEqual(_signflip_exact([1.0] * 6), 1 / 64)
        check_plan(self.plan, self.public, require_original=False)
        with self.assertRaisesRegex(AdmissionError, "historical LoCoMo"):
            check_plan(self.plan, self.public, require_original=True)

    def test_freeze_rejects_unpinned_past_protocol(self):
        with self.assertRaisesRegex(AdmissionError, "wrong parent"):
            freeze_plan({}, self.public, reader="a" * 64,
                        tokenizer="b" * 64, prompt="c" * 64,
                        source_frontier="d" * 64,
                        forget_frontier="e" * 64)


if __name__ == "__main__":
    unittest.main()
