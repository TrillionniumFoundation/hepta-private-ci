"""Hermetic narrow label-code controls; archive integrity always checked."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_onehop_label_ablation import (
    prompt_messages as original_prompt,
    READER_IDENTITY,
)
from system2_onehop_label_lexeme import (
    ALL_ARMS,
    AnswerOnlyReader,
    PRESENTATIONS,
    cases,
    outcome,
    prompt_messages,
    run,
    score,
    selected,
)
from system2_multihop_trial import evidence
from system2_multihop_evidence import digest

PARENT = Path("/mnt/data/hepta-onehop-cardinality-hosted-0abf776c.zip")


class Tokenizer:
    chat_template = "frozen-test-template"

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        if not tokenize or not add_generation_prompt:
            raise ValueError("tokenizer contract")
        return list(("".join(m["role"] + m["content"] for m in messages)).encode())


class Model:
    training = False

    def parameters(self):
        return iter(())


class Frozen:
    identity = READER_IDENTITY
    model = Model()
    base_digest = "fixed-fake-tensors"
    tokenizer = Tokenizer()
    inventory = {"model": "frozen"}

    def verify_frozen(self):
        return None


def mocked_answer(self, query, bundle, originals, *, frontier, revoked, token_limit):
    ids, receipt = self.compile_input(
        query,
        bundle,
        originals,
        frontier=frontier,
        revoked=revoked,
        token_limit=token_limit,
    )
    assert ids
    return "I do not have enough evidence.", receipt | dict(
        reader_identity=READER_IDENTITY,
        reader_profile=self.profile,
        generated_tokens=7,
        generated_ids_digest=digest([1, 2, 3]),
        trainable_parameters=0,
        answer_postprocessed=False,
        production_accepted=False,
    )


class LexemeTests(unittest.TestCase):
    def test_exact_sixty_registered_positions(self):
        self.assertEqual(PRESENTATIONS, ("neutral_code",))
        self.assertEqual(len(cases()), 20)
        self.assertEqual(len(ALL_ARMS), 3)
        self.assertEqual(
            {arm for arm, _ in ALL_ARMS},
            {"single_fact", "target_decoy_two_first", "decoy_one"},
        )

    def test_labels_change_but_question_and_original_bytes_do_not(self):
        for case in cases()[:4]:
            for arm, _ in ALL_ARMS:
                docs = selected(case, arm)
                b, _, _ = evidence(case, docs, "answer-only:" + arm)
                old = original_prompt(case.question, b.delivered(), "labeled")
                new = prompt_messages(case.question, b.delivered(), "neutral_code")
                self.assertEqual(old[0], new[0])
                a = json.loads(old[1]["content"])
                c = json.loads(new[1]["content"])
                self.assertEqual(a["question"], c["question"])
                for i, (x, y) in enumerate(
                    zip(a["evidence"], c["evidence"], strict=True), 1
                ):
                    self.assertEqual((x["label"], y["label"]), (f"E{i}", f"R{i}"))
                    self.assertEqual(
                        {k: v for k, v in x.items() if k != "label"},
                        {k: v for k, v in y.items() if k != "label"},
                    )

    def test_original_reader_identity_and_actual_prompt_tokens_charged(self):
        c = cases()[0]
        docs = selected(c, "target_decoy_two_first")
        b, o, f = evidence(c, docs, "answer-only:target_decoy_two_first")
        reader = AnswerOnlyReader(Frozen(), "neutral_code")
        ids, rec = reader.compile_input(
            c.question, b, o, frontier=f, revoked=set(), token_limit=1024
        )
        self.assertEqual(rec["input_tokens"], len(ids))
        self.assertEqual(rec["token_count_delta"], 0)
        self.assertTrue(rec["equal_input_token_counts"])
        self.assertEqual(rec["delivered_evidence"], b.delivered())
        self.assertNotEqual(
            rec["input_ids_digest"], rec["reference_labeled_input_digest"]
        )
        with self.assertRaises(ValueError):
            reader.compile_input(
                c.question, b, o, frontier=f, revoked=set(), token_limit=2048
            )

    def test_no_online_gold_answer_in_prompt(self):
        c = cases()[0]
        b, _, _ = evidence(c, selected(c, "single_fact"), "answer-only:single_fact")
        user = prompt_messages(c.question, b.delivered(), "neutral_code")[1]["content"]
        self.assertNotIn("required_ids", user)
        self.assertNotIn("source_manifest", user)
        self.assertNotIn("answer", user)

    def test_true_refusal_is_separate_from_correct_extraction(self):
        c = cases()[0]
        self.assertTrue(outcome(c, "single_fact", "neutral_code", c.answer)["success"])
        self.assertFalse(
            outcome(c, "single_fact", "neutral_code", c.answer + " [E1]")["success"]
        )
        self.assertTrue(
            outcome(c, "decoy_one", "neutral_code", "I do not have enough evidence.")[
                "success"
            ]
        )
        self.assertTrue(
            outcome(c, "decoy_one", "neutral_code", c.answer)[
                "unsupported_token_output"
            ]
        )
        self.assertTrue(
            outcome(c, "single_fact", "neutral_code", "R1")["label_only_echo"]
        )

    def test_complete_runner_seals_all_sixty_calls(self):
        if not PARENT.exists():
            self.skipTest("GitHub-pinned 140-row parent not mounted")
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "run"
            with patch.object(AnswerOnlyReader, "answer", mocked_answer):
                r = run(out, Frozen(), PARENT, source_commit="a" * 40)
            self.assertEqual(r["planned"], 60)
            raw = (out / "raw-answers.jsonl").read_bytes()
            self.assertEqual(len(raw.splitlines()), 60)
            self.assertEqual(len((out / "starts.jsonl").read_text().splitlines()), 60)
            self.assertEqual(
                json.loads((out / "raw-seal.json").read_text())["sha256"],
                hashlib.sha256(raw).hexdigest(),
            )
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["recorded"], 60)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(
                summary["candidate_disposition"], "lexeme_control_only_no_selection"
            )
            self.assertEqual([g["completed"] for g in summary["groups"]], [20] * 3)

    def test_failed_calls_stay_unknown_not_negative_free_work(self):
        if not PARENT.exists():
            self.skipTest("GitHub-pinned 140-row parent not mounted")
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "run"
            with patch.object(
                AnswerOnlyReader, "answer", side_effect=RuntimeError("injected")
            ):
                with self.assertRaises(RuntimeError):
                    run(out, Frozen(), PARENT, source_commit="b" * 40)
            self.assertEqual(
                len((out / "raw-answers.jsonl").read_text().splitlines()), 60
            )
            self.assertEqual(
                json.loads((out / "summary.json").read_text())["failed"], 60
            )
            self.assertTrue((out / "run-failure.json").exists())

    def test_duplicate_or_missing_rows_rejected(self):
        c = cases()
        rows = [
            dict(
                qid=case.question.identity,
                arm=arm,
                presentation="neutral_code",
                status="failed",
            )
            for case in c
            for arm, _ in ALL_ARMS
        ]
        self.assertEqual(len(score(rows, c)[0]), 60)
        with self.assertRaises(ValueError):
            score(rows[:-1], c)
        with self.assertRaises(ValueError):
            score(rows + [rows[0]], c)

    def test_reject_unknown_mode_or_invalid_commit(self):
        with self.assertRaises(ValueError):
            AnswerOnlyReader(Frozen(), "unlabeled")
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "run"
            with self.assertRaises(ValueError):
                run(out, Frozen(), PARENT, source_commit="invalid")
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
