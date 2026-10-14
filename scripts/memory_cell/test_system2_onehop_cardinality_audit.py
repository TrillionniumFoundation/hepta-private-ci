"""Immutable same-question Reader-cardinality auditing, including unknown failures."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_onehop_cardinality import ARMS, REPEATED, cases, run
from system2_onehop_reader import select as legacy_select
from system2_onehop_cardinality_audit import (
    METRICS,
    PAIR_CONTRASTS,
    audit,
    entries,
    independent_verdict,
    verify_registered_pair_design,
)
from test_system2_onehop_cardinality import FakeReader


SOURCE_COMMIT = "a" * 40
PARENT = Path("historical-pinned.zip")


def parent():
    return dict(
        manifest_entries=28,
        rows={
            (case.question.identity, arm): dict(
                qid=case.question.identity,
                arm=arm,
                answer="E1",
                selected=[
                    d.identity
                    for d in legacy_select(case.question, case.documents, arm)
                ],
            )
            for case in cases()
            for arm in REPEATED
        },
    )


class ReceiptReader(FakeReader):
    """Mock responses plus receipts; never used as evidence of neural quality."""

    def answer(self, q, bundle, originals, *, frontier, revoked, token_limit):
        output, receipt = super().answer(
            q,
            bundle,
            originals,
            frontier=frontier,
            revoked=revoked,
            token_limit=token_limit,
        )
        receipt.update(
            input_ids_digest="a" * 64, generated_ids_digest="b" * 64, seconds=0.01
        )
        return output, receipt


def create_trial(root, *, count=2, fail_at=None):
    trial = root / "trial"
    with patch("system2_onehop_cardinality.load_parent", return_value=parent()):
        try:
            run(
                trial,
                ReceiptReader(fail_at=fail_at),
                PARENT,
                source_commit=SOURCE_COMMIT,
                count=count,
            )
        except RuntimeError:
            if fail_at is None:
                raise
    return trial


def replay(root, trial, *, count=2):
    with patch("system2_onehop_cardinality_audit.load_parent", return_value=parent()):
        return audit(
            PARENT, trial, root / "audit", source_commit=SOURCE_COMMIT, count=count
        )


class AuditTests(unittest.TestCase):
    def test_cold_replay_two_questions_no_new_reader_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = create_trial(root)
            result = replay(root, trial)
            self.assertEqual(
                (result["new_planned"], result["new_recorded"], result["new_failures"]),
                (14, 14, 0),
            )
            self.assertEqual(len(result["paired_contrasts"]), len(PAIR_CONTRASTS))
            self.assertEqual(len(result["arms"]), len(ARMS))
            self.assertEqual(result["original_reader_call_replay_count"], 0)
            self.assertTrue(result["unknown_failed_cost_not_zero"])
            self.assertEqual(len(entries(trial / "starts.jsonl")), 14)
            self.assertTrue((root / "audit" / "audit-summary.json").is_file())

    def test_exact_position_pair_and_legacy_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = create_trial(root)
            out = replay(root, trial)
            pair = out["paired_contrasts"][0]
            self.assertEqual(pair["name"], "same_two_facts_swap")
            self.assertEqual(pair["metrics"]["grounded_answer_success"]["paired"], 2)
            self.assertEqual(pair["metrics"]["grounded_answer_success"]["gain"], 0)
            self.assertEqual(out["new_failures"], 0)

    def test_unsupported_answer_copy_not_grounded(self):
        c = cases()[0]
        doc = legacy_select(c.question, c.documents, "distractors_only")
        row = dict(selected=[d.identity for d in doc], answer=c.answer + " [E1]")
        result = independent_verdict(c, "distractors_only", row)
        self.assertTrue(result["unsupported_token_copy"])
        self.assertFalse(result["grounded_answer_success"])

    def test_registered_pair_membership_and_source_counts(self):
        for case in cases():
            verify_registered_pair_design(case)

    def test_reader_label_echo_never_grounded(self):
        c = cases()[0]
        doc = legacy_select(c.question, c.documents, "fact_plus_distractors")
        answer = "E1\n\nE2\n\nE3"
        result = independent_verdict(
            c,
            "fact_plus_distractors",
            dict(selected=[d.identity for d in doc], answer=answer),
        )
        self.assertTrue(result["label_only_answer"])
        self.assertFalse(result["grounded_answer_success"])

    def test_detect_mutated_sealed_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = create_trial(root)
            with (trial / "raw-answers.jsonl").open("ab") as f:
                f.write(b"{}\n")
            with self.assertRaisesRegex(ValueError, "seal"):
                replay(root, trial)

    def test_forged_scored_output_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = create_trial(root)
            score_path = trial / "scored.json"
            rows = json.loads(score_path.read_text())
            rows[0]["grounded_answer_success"] = not rows[0]["grounded_answer_success"]
            score_path.write_text(json.dumps(rows) + "\n")
            with self.assertRaisesRegex(ValueError, "scoring field"):
                replay(root, trial)

    def test_forged_input_hash_even_when_raw_resealed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = create_trial(root)
            path = trial / "raw-answers.jsonl"
            rows = entries(path)
            rows[0]["reader"]["input_ids_digest"] = "broken"
            raw = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
            path.write_bytes(raw)
            (trial / "raw-seal.json").write_text(
                json.dumps(
                    dict(
                        sha256=hashlib.sha256(raw).hexdigest(),
                        rows=14,
                        scoring_started=False,
                    )
                )
                + "\n"
            )
            with self.assertRaisesRegex(ValueError, "unbound"):
                replay(root, trial)

    def test_failed_reader_keeps_unknown_bounds_and_cpu(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = create_trial(root, fail_at=3)
            result = replay(root, trial)
            self.assertEqual(result["new_failures"], 1)
            arm = next(
                x
                for x in result["arms"]
                if x["outcome_bounds"]["grounded_answer_success"]["unknown"]
            )
            self.assertEqual(
                arm["outcome_bounds"]["grounded_answer_success"]["unknown"], 1
            )
            self.assertEqual(arm["unknown_failed_cpu_and_tokens"], 1)
            self.assertEqual(result["new_recorded"], result["new_planned"])

    def test_start_journal_missing_position_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = create_trial(root)
            lines = (trial / "starts.jsonl").read_text().splitlines()
            (trial / "starts.jsonl").write_text("\n".join(lines[:-1]) + "\n")
            with self.assertRaisesRegex(ValueError, "census|start"):
                replay(root, trial)

    def test_reader_identity_or_evidence_order_spoof_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = create_trial(root)
            path = trial / "raw-answers.jsonl"
            rows = entries(path)
            rows[0]["selected"].reverse()
            raw = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
            path.write_bytes(raw)
            (trial / "raw-seal.json").write_text(
                json.dumps(
                    dict(
                        sha256=hashlib.sha256(raw).hexdigest(),
                        rows=14,
                        scoring_started=False,
                    )
                )
                + "\n"
            )
            with self.assertRaises(ValueError):
                replay(root, trial)

    def test_reject_wrong_generating_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = create_trial(root)
            with patch(
                "system2_onehop_cardinality_audit.load_parent", return_value=parent()
            ):
                with self.assertRaisesRegex(ValueError, "registered"):
                    audit(
                        PARENT, trial, root / "audit", source_commit="b" * 40, count=2
                    )

    def test_reject_duplicate_or_nonnumeric_json_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = create_trial(root)
            with (trial / "starts.jsonl").open("a") as f:
                f.write("{}\n")
            with self.assertRaises(ValueError):
                replay(root, trial)

    def test_exact_score_independent_of_answer_token_when_missing_sources(self):
        c = cases()[0]
        a = independent_verdict(c, "no_evidence", dict(selected=[], answer="E1"))
        b = independent_verdict(
            c, "no_evidence", dict(selected=[], answer="I do not have enough evidence.")
        )
        self.assertFalse(a["grounded_answer_success"])
        self.assertFalse(b["grounded_answer_success"])
        self.assertFalse(a["strict_abstention"])
        self.assertTrue(b["strict_abstention"])

    def test_metrics_include_unsupported_and_label_echo(self):
        self.assertIn("unsupported_token_copy", METRICS)
        self.assertIn("label_only_answer", METRICS)
        self.assertEqual(len(PAIR_CONTRASTS), 5)


if __name__ == "__main__":
    unittest.main()
