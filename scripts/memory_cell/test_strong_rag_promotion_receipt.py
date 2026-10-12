"""Model-free tests for exact archived research disposition (not model claims)."""

from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from strong_rag_promotion_receipt import (
    ARMS, GENERATING_COMMIT, MODEL_ZIP_SHA256, REPLAY_ZIP_SHA256,
    checked_archive, load, paired_delta, per_arm, qualifying_receipt,
    replay_leave_one_out, rows, sha, strict_json,
)


def archive_bytes(blobs):
    payloads = dict(blobs)
    manifest = "".join(sha(payloads[name]) + "  ./" + name + "\n" for name in sorted(payloads))
    payloads["SHA256SUMS"] = manifest.encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        for name, blob in payloads.items():
            z.writestr(name, blob)
    return stream.getvalue()


def simple_scored(n=1, *, arms=("a", "b")):
    initial, scored = [], []
    for qi in range(n):
        for i, arm in enumerate(arms):
            raw = dict(question_id=f"q{qi}", arm=arm, status="succeeded",
                       receipt=dict(input_tokens=10+i, generated_tokens=2, seconds=1.0),
                       answer="identifier [E1]")
            initial.append(raw)
            scored.append(raw | {"strict_task_success": bool(i)})
    return initial, scored


class StrictArchiveTests(unittest.TestCase):
    def test_rejects_nonfinite_and_duplicate_json(self):
        self.assertEqual(strict_json('{"answer":1}'), {"answer": 1})
        for payload in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                strict_json(payload)

    def test_complete_manifest_accepts_only_pinned_bytes(self):
        raw = archive_bytes({"tested-commit.txt": (GENERATING_COMMIT + "\n").encode(), "demo.json": b'{}'})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "archive.zip"
            path.write_bytes(raw)
            self.assertEqual(checked_archive(path, sha(raw))["demo.json"], b"{}")
            with self.assertRaisesRegex(ValueError, "ZIP hash"):
                checked_archive(path, "f" * 64)

    def test_inner_member_change_and_missing_manifest_are_rejected(self):
        raw = archive_bytes({"demo.json": b'{}'})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "archive.zip"
            with zipfile.ZipFile(io.BytesIO(raw)) as source:
                blobs = {x: source.read(x) for x in source.namelist()}
            blobs["demo.json"] = b'{"tampered":true}'
            with zipfile.ZipFile(path, "w") as sink:
                for name, data in blobs.items():
                    sink.writestr(name, data)
            with self.assertRaisesRegex(ValueError, "replaced"):
                checked_archive(path, sha(path.read_bytes()))
            path.write_bytes(archive_bytes({"demo.json": b'{}'}))
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("demo.json", "{}")
            with self.assertRaises(ValueError):
                checked_archive(path, sha(path.read_bytes()))

    def test_traversal_and_duplicate_archive_member_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.zip"
            for name in ("../escape.json", "x\\evil.json"):
                raw = archive_bytes({name: b'{}'})
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    checked_archive(path, sha(raw))
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("same.txt", b"1")
                z.writestr("same.txt", b"2")
                z.writestr("SHA256SUMS", b"")
            with self.assertRaises(ValueError):
                checked_archive(path, sha(path.read_bytes()))

    def test_raw_scored_journal_must_preserve_exact_model_text(self):
        raw, scored = simple_scored()
        files = {
            "evaluation/raw-answers.jsonl": ("\n".join(json.dumps(x) for x in raw) + "\n").encode(),
            "evaluation/scored-answers.json": json.dumps(scored).encode(),
        }
        produced, questions = rows(files, "evaluation", ("a", "b"), expected_queries=1)
        self.assertEqual(len(produced), 2)
        self.assertEqual(questions, {"q0"})
        changed = deepcopy(scored)
        changed[0]["answer"] = "rewritten"
        files["evaluation/scored-answers.json"] = json.dumps(changed).encode()
        with self.assertRaisesRegex(ValueError, "disagreement"):
            rows(files, "evaluation", ("a", "b"), expected_queries=1)

    def test_dropped_or_duplicate_attempts_are_rejected(self):
        raw, scored = simple_scored()
        files = {
            "evaluation/raw-answers.jsonl": ("\n".join(json.dumps(x) for x in raw+raw[:1])+"\n").encode(),
            "evaluation/scored-answers.json": json.dumps(scored+scored[:1]).encode(),
        }
        with self.assertRaises(ValueError):
            rows(files, "evaluation", ("a", "b"), expected_queries=1)

    def test_citation_counts_must_match_correct_answers_and_plan(self):
        _, scored = simple_scored()
        record = dict(by_arm={
            "a": dict(attempted=1, generations_succeeded=1, generations_failed=0,
                      strict_task_success=0, correct_with_full_program_declared_citations=0,
                      correct_with_public_event_chain_connected=0),
            "b": dict(attempted=1, generations_succeeded=1, generations_failed=0,
                      strict_task_success=1, correct_with_full_program_declared_citations=1,
                      correct_with_public_event_chain_connected=1),
        }, planned_attempts=2)
        self.assertEqual(per_arm(scored, ("a", "b"), record)["b"]["correct_with_event_path"], 1)
        fake = deepcopy(record)
        fake["by_arm"]["b"]["correct_with_public_event_chain_connected"] = 2
        with self.assertRaises(ValueError):
            per_arm(scored, ("a", "b"), fake)

    def test_effect_counts_use_original_eight_matched_question_ids(self):
        records = []
        for i in range(8):
            records.extend((
                dict(question_id=f"q{i}", arm="left", strict_task_success=i >= 4),
                dict(question_id=f"q{i}", arm="right", strict_task_success=True),
            ))
        self.assertEqual(paired_delta(records, "left", "right"),
                         dict(wins=4, losses=0, ties=4, difference_eighths=4))
        with self.assertRaises(ValueError):
            paired_delta(records[:-1], "left", "right")

    def test_loo_recomputed_from_original_question_level_scores(self):
        scored = []
        for i in range(8):
            for k in (1,2,3,4,6):
                scored.append(dict(question_id=f"q{i}", arm=f"k{k}",
                                   strict_task_success=k == 1,
                                   receipt=dict(input_tokens=100*k)))
        folds = [dict(omitted_calibration_question=f"q{i}",
                      chosen_k_without_that_question=1,heldout_comparison="selected_wins")
                 for i in range(8)]
        sensitivity = dict(folds=folds, chosen_k_counts={str(k):8 if k==1 else 0 for k in (1,2,3,4,6)},
                           stable_to_one_calibration_case_removal=True,
                           selected_wins_over_fixed_k4=8,selected_losses_to_fixed_k4=0,
                           selected_ties_with_fixed_k4=0)
        self.assertFalse(replay_leave_one_out(scored, sensitivity, 1))
        broken = deepcopy(sensitivity)
        broken["chosen_k_counts"]["2"] = 1
        with self.assertRaisesRegex(ValueError, "instability"):
            replay_leave_one_out(scored, broken, 1)

    def test_wrong_generating_commit_rejected_before_aggregate_scoring(self):
        with self.assertRaisesRegex(ValueError, "wrong generating source"):
            qualifying_receipt({"tested-commit.txt": b"incorrect"},
                               {"auditor-source-commit.txt": (GENERATING_COMMIT+"\n").encode()})

    def test_real_pinned_112_responses_when_archives_supplied(self):
        a, b = os.environ.get("HEPTA_STRONG_RAG_MODEL_ZIP"), os.environ.get("HEPTA_STRONG_RAG_REPLAY_ZIP")
        if not a or not b:
            self.skipTest("exact historical ZIP artifacts intentionally not bundled with source")
        model = checked_archive(Path(a), MODEL_ZIP_SHA256)
        replay = checked_archive(Path(b), REPLAY_ZIP_SHA256)
        actual = qualifying_receipt(model, replay)
        self.assertEqual((actual["actual_calibration_calls"],actual["actual_evaluation_calls"]), (40,72))
        self.assertEqual((actual["frozen_calibrated_k"],actual["by_arm"]["organized"]["correct"]), (1,8))
        self.assertEqual(actual["by_arm"]["organized"]["correct_with_event_path"],4)
        self.assertEqual(actual["organized_extra_correct_over_complete_path"],0)
        self.assertFalse(actual["parametric_memory_training_qualified"])


if __name__ == "__main__":
    unittest.main()
