"""Fail-closed checks for published, real-reader evidence dispositions.

These tiny fixtures test the verifier; they are not new Qwen predictions.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import archived_rag_disposition as audit


def fixture():
    content = json.dumps(
        {"schema": "hepta.controlled-event.v1", "id": "evt",
         "entity": "service_one", "attribute": "location",
         "revision": 1, "supersedes": [], "value": "site_deadbeef"},
        sort_keys=True,
    )
    document = {
        "identity": "evt", "root": "root_1", "scope": "q",
        "observed_at": "2026-01-01T00:00:00Z", "content": content,
    }
    question = {
        "identity": "q", "scope": "q", "family": "family",
        "content": "What site?", "observed_at": "2026-01-01T00:00:00Z",
    }
    candidates = ["evt", "other"]
    case = {
        "query": question, "candidate_ids": candidates,
        "candidate_digest": audit.native_digest(candidates),
        "controls": {"organized": {"selected": ["evt"]}},
    }
    delivered = {
        "label": "E1", "id": "x" * 64, "original_id": "evt",
        "root": "root_1", "scope": "q", "source_start": 0,
        "source_end": len(content.encode()), "excerpt": content,
        "source_digest": audit.native_digest(content),
    }
    request = {
        "query_id": "q", "scope": "q", "question": question["content"],
        "question_time": question["observed_at"],
        "answer": "site_deadbeef [E1]", "prompt_digest": "a" * 64,
        "sources": [{
            "label": "E1", "id": "x" * 64,
            "root": audit.native_root_digest("root_1"), "excerpt": content,
        }],
    }
    row = {
        "question_id": "q", "kind": "new_fact", "arm": "organized",
        "selected": ["evt"], "candidate_digest": case["candidate_digest"],
        "status": "succeeded", "answer": "site_deadbeef [E1]",
        "receipt": {
            "token_limit": 2048, "input_tokens": 100, "generated_tokens": 6,
            "trainable_parameters": 0, "answer_postprocessed": False,
            "production_accepted": False, "seconds": 0.3,
            "input_ids_digest": "a" * 64,
            "generated_ids_digest": "b" * 64,
            "delivered_evidence": [delivered],
        },
        "citation_audit": {"request": request, "judgement": None},
    }
    scored = dict(
        row, parsed_identifier="site_deadbeef", strict_task_success=True,
        required_sources_covered=True,
    )
    truth = {
        "id": "q", "kind": "new_fact", "expected": "site_deadbeef",
        "support": ["evt"],
    }
    return row, scored, case, truth, {"evt": document}


class VerifiedRagEvidenceTests(unittest.TestCase):
    def test_strict_identifier_has_no_lenient_answer_repair(self):
        self.assertEqual(
            audit.response_identifier("site_deadbeef [E1]"), "site_deadbeef"
        )
        for text in ("Maybe site_deadbeef", "site_deadbeef [E0]", "unknown"):
            self.assertIsNone(audit.response_identifier(text))

    def test_program_outcome_requires_actual_recipe_execution(self):
        truth = {
            "kind": "procedure", "procedure": {
                "modes": {"mode_11111111": "sort", "mode_22222222": "reverse"},
                "values": [3, 1, 2], "target": [1, 2, 3],
            },
        }
        self.assertTrue(audit.task_success("mode_11111111", truth))
        self.assertFalse(audit.task_success("mode_22222222", truth))
        self.assertFalse(audit.task_success(None, truth))

    def test_actual_delivered_source_and_citation_binding(self):
        row, scored, case, truth, docs = fixture()
        result = audit.verify_row(
            row, scored, case, "organized", 1, truth, docs, {}
        )
        self.assertTrue(result["task_success"])
        self.assertTrue(result["correct_and_full_source_cited"])

    def test_scorer_cannot_replace_original_answer(self):
        row, scored, case, truth, docs = fixture()
        tampered = deepcopy(scored)
        tampered["answer"] = "site_00000000 [E1]"
        with self.assertRaises(ValueError):
            audit.verify_row(row, tampered, case, "organized", 1, truth, docs, {})

    def test_untrusted_original_source_bytes_reject(self):
        row, scored, case, truth, docs = fixture()
        tampered = deepcopy(row)
        tampered["receipt"]["delivered_evidence"][0]["excerpt"] += "modified"
        tampered_scored = dict(scored)
        tampered_scored["receipt"] = tampered["receipt"]
        with self.assertRaises(ValueError):
            audit.verify_row(
                tampered, tampered_scored, case, "organized", 1, truth, docs, {}
            )

    def test_unreviewed_correct_answer_does_not_get_full_citation_credit(self):
        row, scored, case, truth, docs = fixture()
        wrong_support = dict(truth, support=["unknown_source"])
        scored = dict(scored, required_sources_covered=False)
        result = audit.verify_row(
            row, scored, case, "organized", 1, wrong_support, docs, {}
        )
        self.assertTrue(result["task_success"])
        self.assertFalse(result["correct_and_source_covered"])
        self.assertFalse(result["correct_and_full_source_cited"])

    def test_selection_has_no_oracle_parameter(self):
        row, scored, case, truth, docs = fixture()
        self.assertEqual(
            audit.chosen_sources(case, "selected_k", 1, {}), ["evt"]
        )
        self.assertEqual(
            audit.chosen_sources(case, "hybrid_k4_reversed", 1, {}),
            ["other", "evt"],
        )
        bad = deepcopy(case)
        bad["candidate_ids"] = list(reversed(case["candidate_ids"]))
        with self.assertRaises(ValueError):
            audit.chosen_sources(bad, "selected_k", 1, {})

    def test_duplicate_and_nan_json_rejected(self):
        for data in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                audit.strict_json(data)

    def test_manifest_member_cannot_be_altered_with_repacked_outer_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "sample.zip"
            checksum = hashlib.sha256(b"original").hexdigest()
            with zipfile.ZipFile(filename, "w") as out:
                out.writestr("file.txt", b"changed")
                out.writestr("SHA256SUMS", f"{checksum}  file.txt\n")
            with self.assertRaisesRegex(ValueError, "manifest member changed"):
                audit.archive(filename, audit.sha(filename.read_bytes()))

    def test_manifest_accepts_complete_consistent_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "sample.zip"
            checksum = hashlib.sha256(b"original").hexdigest()
            with zipfile.ZipFile(filename, "w") as out:
                out.writestr("file.txt", b"original")
                out.writestr("SHA256SUMS", f"{checksum}  file.txt\n")
            files, census = audit.archive(filename, audit.sha(filename.read_bytes()))
            self.assertEqual(census, 1)
            self.assertEqual(files["file.txt"], b"original")

    def test_paired_task_delta_is_not_a_confidence_interval(self):
        rows = [
            {"question_id": "a", "arm": "left", "task_success": False},
            {"question_id": "a", "arm": "right", "task_success": True},
            {"question_id": "b", "arm": "left", "task_success": True},
            {"question_id": "b", "arm": "right", "task_success": False},
        ]
        self.assertEqual(
            audit.paired(rows, "left", "right"),
            {"wins": 1, "losses": 1, "ties": 0},
        )

    def test_leave_one_out_is_based_on_real_heldout_task_not_model_size(self):
        records = []
        for qid, outcome in (("q1", (True, False)), ("q2", (False, True))):
            for k in audit.KS:
                correct = outcome[0] if k == 1 else outcome[1]
                records.append({
                    "question_id": qid,
                    "arm": f"k{k}",
                    "task_success": correct,
                    "correct_and_source_covered": correct,
                    "correct_and_full_source_cited": correct,
                    "input_tokens": k * 100,
                    "output_tokens": 1,
                    "reader_seconds": 1.0,
                })
        folds = audit.leave_one_out(records, ["q1", "q2"])
        self.assertEqual(len(folds), 2)
        self.assertEqual(
            [x["chosen_k_without_that_question"] for x in folds], [2, 1]
        )
        self.assertEqual(folds[0]["heldout_comparison"], "tie")
        self.assertEqual(folds[1]["heldout_comparison"], "selected_loses")

    def test_deterministic_repeatability_detects_real_output_drift(self):
        record = {
            "question_id": "q", "selected": ["event1"],
            "prompt_digest": "d" * 64, "input_tokens": 100,
            "answer": "site_deadbeef [E1]", "generated_digest": "c" * 64,
        }
        a = audit.verify_repeats([record, dict(record)])
        self.assertEqual(a["matched_prompt_pairs"], 1)
        self.assertEqual(a["answer_disagreements"], 0)
        altered = dict(record, answer="site_01234567 [E1]")
        b = audit.verify_repeats([record, altered])
        self.assertEqual(b["answer_disagreements"], 1)
        with self.assertRaises(ValueError):
            audit.verify_repeats([record, dict(record, input_tokens=200)])

    def test_committed_evidence_keeps_promotion_closed(self):
        path = Path(__file__).with_name("data") / "strong-rag-38224780900-verified.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(report["generating_commit"], audit.SOURCE_COMMIT)
        self.assertEqual(report["evaluation_replayed"]["attempts"], 72)
        self.assertEqual(report["calibration_replayed"]["attempts"], 40)
        self.assertFalse(report["memory_cell_learning_promotion_qualified"])
        self.assertFalse(report["production_accepted"])
        self.assertEqual(
            report["observations"]["organized_minus_full_path_task_wins"], 0
        )


if __name__ == "__main__":
    unittest.main()
