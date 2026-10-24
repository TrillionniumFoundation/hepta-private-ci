"""Authenticated 180-call Qwen TAG audit: fixed cohort, source, seal and costs."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native import digest as native_digest
from system2_multihop_trial import ABSTAIN, evidence
from system2_reader_lexical_factorial import transform
from system2_reader_paired_capacity_audit import STRONG_READER_ID
from system2_reader_tag_label_order import (
    ARMS,
    MAX_NEW_TOKENS,
    PARENT_SHA,
    PLANNED,
    POSITIONS,
    PRESENTATIONS,
    PROFILE,
    SCHEMA,
    cohort,
    context,
    contrasts,
)
import system2_reader_tag_label_audit as audit


def fixture():
    cases = cohort()
    rows = []
    for case in cases:
        target, _ = transform(case, PROFILE)
        for arm, view in POSITIONS:
            source, docs = context(case, arm)
            bundle, originals, frontier = evidence(
                source, docs, "tag-label:" + arm + ":" + view
            )
            bundle.validate(
                source.question, originals, frontier=frontier, revoked=set()
            )
            rows.append(
                dict(
                    qid=case.question.identity,
                    arm=arm,
                    presentation=view,
                    status="succeeded",
                    selected=[d.identity for d in docs],
                    answer=target.answer if arm in ARMS[:3] else ABSTAIN,
                    reader=dict(
                        reader_identity=STRONG_READER_ID,
                        reader_profile="p" * 64,
                        model_id=audit.MODEL_ID,
                        revision=audit.MODEL_REV,
                        question_digest=native_digest(asdict(source.question)),
                        bundle_digest=bundle.seal(),
                        delivered_evidence=bundle.delivered(),
                        input_ids_digest="a" * 64,
                        generated_ids_digest="b" * 64,
                        input_tokens=90 if view == "labeled" else 82,
                        generated_tokens=12,
                        cpu_time_ns=1000,
                        wall_time_ns=1100,
                        answer_postprocessed=False,
                        trainable_parameters=0,
                        production_accepted=False,
                    ),
                )
            )
    by_arm, pair, disposition = contrasts(rows, cases)
    raw = b"".join(
        (json.dumps(r, sort_keys=True, allow_nan=False) + "\n").encode() for r in rows
    )
    raw_sha = hashlib.sha256(raw).hexdigest()
    doc = b"original-research-source-test"
    blob = audit.git_blob_sha(doc)
    files = dict(
        **{
            "tested-commit.txt": (audit.GENERATING_COMMIT + "\n").encode(),
            "tested-tree.txt": (audit.GENERATING_TREE + "\n").encode(),
            "source/system2_reader_tag_label_order.py": doc,
            "reader-inventory.json": json.dumps(
                dict(model=audit.MODEL_ID, revision=audit.MODEL_REV)
            ).encode(),
            "trial/plan.json": json.dumps(
                dict(
                    schema=SCHEMA,
                    source_commit=audit.GENERATING_COMMIT,
                    original_archive_sha256=PARENT_SHA,
                    original_model_identity=STRONG_READER_ID,
                    questions=[c.question.identity for c in cases],
                    arms=list(ARMS),
                    presentations=list(PRESENTATIONS),
                    positions=[list(x) for x in POSITIONS],
                    planned_model_calls=PLANNED,
                    production_accepted=False,
                    compute_matched=False,
                )
            ).encode(),
            "trial/raw-answers.jsonl": raw,
            "trial/starts.jsonl": b"".join(
                (
                    json.dumps(
                        dict(
                            qid=r["qid"],
                            arm=r["arm"],
                            presentation=r["presentation"],
                            status="started",
                        )
                    )
                    + "\n"
                ).encode()
                for r in rows
            ),
            "trial/raw-seal.json": json.dumps(
                dict(sha256=raw_sha, rows=PLANNED, scoring_started=False)
            ).encode(),
            "trial/scored-summary.json": json.dumps(
                dict(
                    source_commit=audit.GENERATING_COMMIT,
                    raw_sha256=raw_sha,
                    model_calls=PLANNED,
                    completed=PLANNED,
                    failed=0,
                    by_arm=by_arm,
                    paired_effects=pair,
                    candidate_disposition=disposition,
                    production_accepted=False,
                    compute_matched=False,
                )
            ).encode(),
            "SHA256SUMS": b"original archive verification occurs before audit_files",
        }
    )
    return rows, files, blob


class SealedTagAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_rows, cls.original_files, cls.source_blob = fixture()

    def setUp(self):
        self.rows = deepcopy(self.original_rows)
        self.files = deepcopy(self.original_files)
        self.blob_guard = patch.object(audit, "GENERATING_CODE_BLOB", self.source_blob)
        self.blob_guard.start()
        self.addCleanup(self.blob_guard.stop)

    def test_complete_planned_positions_and_separate_answer_yield(self):
        output = audit.audit_files(self.files)
        self.assertEqual(
            (
                output["question_count"],
                output["complete_model_attempts"],
                output["failed"],
            ),
            (20, 180, 0),
        )
        self.assertEqual(output["per_condition"]["single_fact/labeled"]["exact"], 20)
        self.assertEqual(
            output["per_condition"]["target_decoy_first/unlabeled"]["exact"], 20
        )
        self.assertEqual(output["per_condition"]["decoy_only/unlabeled"]["refused"], 20)
        self.assertEqual(
            output["per_condition"]["no_evidence/unlabeled"]["refused"], 20
        )
        self.assertFalse(output["compute_matched"])
        self.assertEqual(output["new_neural_calls"], 0)

    def test_real_token_gaps_are_not_assumed_zero(self):
        output = audit.audit_files(self.files)
        paired = output["per_pair_discordance"]["target_decoy_last/exact_answer"]
        self.assertEqual(
            (
                paired["both"],
                paired["unlabeled_only"],
                paired["labeled_only"],
                paired["neither"],
            ),
            (20, 0, 0, 0),
        )
        self.assertTrue(all(x == -8 for x in paired["prompt_token_gap_by_question"]))
        self.assertTrue(output["labels_and_prompt_tokens_confounded"])

    def test_unchanged_source_bytes_and_identical_originals(self):
        case = cohort()[0]
        for arm, view in POSITIONS:
            row = next(
                r
                for r in self.rows
                if r["qid"] == case.question.identity
                and r["arm"] == arm
                and r["presentation"] == view
            )
            outcome = audit.verify_receipt(row, case, arm, view)
            self.assertTrue(outcome["strict_success"])

    def test_refuses_forged_answer_or_source_identity(self):
        case = cohort()[0]
        row = next(r for r in self.rows if r["qid"] == case.question.identity)
        row["selected"] = ["fabricated"]
        with self.assertRaisesRegex(ValueError, "source"):
            audit.verify_receipt(row, case, row["arm"], row["presentation"])

    def test_refuses_detached_original_excerpt(self):
        case = cohort()[0]
        row = next(r for r in self.rows if r["qid"] == case.question.identity)
        row["reader"]["delivered_evidence"][0]["excerpt"] = "changed without origin"
        with self.assertRaisesRegex(ValueError, "receipt"):
            audit.verify_receipt(row, case, row["arm"], row["presentation"])

    def test_refuses_fake_reader_or_training_flag(self):
        case = cohort()[0]
        row = next(r for r in self.rows if r["qid"] == case.question.identity)
        for field, value in (
            ("reader_identity", "not-pinned"),
            ("trainable_parameters", 1),
            ("answer_postprocessed", True),
        ):
            modified = deepcopy(row)
            modified["reader"][field] = value
            with self.assertRaisesRegex(ValueError, "receipt"):
                audit.verify_receipt(
                    modified, case, modified["arm"], modified["presentation"]
                )

    def test_refuses_unbounded_cost_and_token_receipts(self):
        case = cohort()[0]
        row = next(r for r in self.rows if r["qid"] == case.question.identity)
        for field, value in (
            ("input_tokens", 1025),
            ("generated_tokens", MAX_NEW_TOKENS + 1),
            ("cpu_time_ns", -1),
            ("input_ids_digest", "bad"),
        ):
            bad = deepcopy(row)
            bad["reader"][field] = value
            with self.assertRaises(ValueError):
                audit.verify_receipt(bad, case, bad["arm"], bad["presentation"])

    def test_rejects_missing_and_duplicate_model_positions(self):
        for changes in (self.rows[:-1], self.rows + self.rows[:1]):
            with self.assertRaisesRegex(ValueError, "(?:duplicate|incomplete)"):
                audit.paired_measure(changes, cohort())

    def test_failed_attempt_is_unknown_not_a_refusal(self):
        case = cohort()[0]
        row = next(r for r in self.rows if r["qid"] == case.question.identity)
        row["status"] = "failed"
        row.pop("answer")
        with self.assertRaisesRegex(ValueError, "status"):
            audit.verify_receipt(row, case, row["arm"], row["presentation"])

    def test_rejects_original_raw_seal_or_summary_tampering(self):
        broken = deepcopy(self.files)
        broken["trial/raw-answers.jsonl"] += b"{}\n"
        with self.assertRaisesRegex(ValueError, "seal"):
            audit.audit_files(broken)
        broken = deepcopy(self.files)
        old = json.loads(broken["trial/scored-summary.json"])
        old["completed"] = 179
        broken["trial/scored-summary.json"] = json.dumps(old).encode()
        with self.assertRaisesRegex(ValueError, "score"):
            audit.audit_files(broken)

    def test_rejects_incomplete_start_journal(self):
        broken = deepcopy(self.files)
        broken["trial/starts.jsonl"] = (
            b"\n".join(broken["trial/starts.jsonl"].splitlines()[:-1]) + b"\n"
        )
        with self.assertRaisesRegex(ValueError, "started"):
            audit.audit_files(broken)

    def test_rejects_wrong_source_commit_tree_or_blob(self):
        for field in (
            "tested-commit.txt",
            "tested-tree.txt",
            "source/system2_reader_tag_label_order.py",
        ):
            broken = deepcopy(self.files)
            broken[field] = b"drift"
            with self.assertRaisesRegex(ValueError, "(?:commit|tree|blob)"):
                audit.audit_files(broken)

    def test_rejects_cost_profile_promotion_without_evidence(self):
        broken = deepcopy(self.files)
        plan = json.loads(broken["trial/plan.json"])
        plan["compute_matched"] = True
        broken["trial/plan.json"] = json.dumps(plan).encode()
        with self.assertRaisesRegex(ValueError, "plan"):
            audit.audit_files(broken)

    def test_archive_loader_fails_closed_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "not-written.json"
            with self.assertRaises((ValueError, FileNotFoundError)):
                audit.run(Path(temp) / "unknown.zip", out)
            self.assertFalse(out.exists())

    def test_only_a_synthetic_and_no_model_call_claim(self):
        outcome = audit.audit_files(self.files)
        self.assertFalse(outcome["human_semantic_judgment"])
        self.assertFalse(outcome["production_accepted"])
        self.assertTrue(outcome["same_20_questions_not_independent"])


if __name__ == "__main__":
    unittest.main()
