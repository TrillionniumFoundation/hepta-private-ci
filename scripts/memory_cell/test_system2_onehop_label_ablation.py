"""Strict protocol tests for a train-free, frozen Reader label-echo ablation."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from system2_onehop_label_ablation import (
    ABSTAIN,
    ALL_ARMS,
    AnswerOnlyReader,
    READER_IDENTITY,
    SYSTEM,
    TOKEN_LIMIT,
    load_previous,
    outcome,
    prompt_messages,
    run,
    score,
    selected,
)
from system2_onehop_reader import cases
from system2_multihop_trial import evidence

ARCHIVE = Path(
    os.environ.get(
        "HEPTA_SYSTEM2_CARDINALITY_ARCHIVE",
        "/tmp/hepta-cardinality-parent-not-staged.zip",
    )
)


class FrozenToyModel:
    training = False

    def parameters(self):
        return ()


class ToyTokenizer:
    chat_template = "pinned fake test chat template"
    eos_token_id = 2

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize and add_generation_prompt
        return list(json.dumps(messages, ensure_ascii=False).encode())


class ToyShared:
    identity = READER_IDENTITY
    inventory = {"test-only": True}
    model = FrozenToyModel()
    tokenizer = ToyTokenizer()
    base_digest = "fake-frozen-parameter-hash-only-for-tests"

    def verify_frozen(self):
        return True


class ReaderProtocolTests(unittest.TestCase):
    def test_seven_conditions_no_duplicate(self):
        self.assertEqual(len(ALL_ARMS), 7)
        self.assertEqual(len(set(ALL_ARMS)), 7)
        self.assertEqual(sum(a == "no_evidence" for a, b in ALL_ARMS), 1)
        self.assertEqual(sum(a == "target_decoy_two_first" for a, b in ALL_ARMS), 2)

    @unittest.skipUnless(ARCHIVE.is_file(), "external pinned archive not staged")
    def test_exact_completed_parent_and_score_census(self):
        got = load_previous(ARCHIVE)
        self.assertEqual(got["verified_files"], 25)
        self.assertEqual(len(got["by_key"]), 140)
        self.assertEqual(
            got["sha256"] if "sha256" in got else got["raw_sha256"],
            "cc04bd7fd7ecc5aed4234f9512c344eb6feffe8dd0e858507bf1688dff4cda61",
        )

    @unittest.skipUnless(ARCHIVE.is_file(), "external pinned archive not staged")
    def test_tampered_parent_never_passes_external_sha(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "tampered.zip"
            raw = ARCHIVE.read_bytes()
            p.write_bytes(raw[:100] + b"X" + raw[101:])
            with self.assertRaises(ValueError):
                load_previous(p)

    def test_observable_source_choice_not_gold(self):
        one = cases()[0]
        fake = replace(one, answer="TOK-DEADDEE")
        for arm, _ in ALL_ARMS:
            self.assertEqual(selected(one, arm), selected(fake, arm))
        target = selected(one, "single_fact")
        competitors = selected(one, "target_decoy_two_first")
        self.assertEqual(len(target), 1)
        self.assertEqual(len(competitors), 2)
        self.assertEqual(target[0].identity, competitors[0].identity)

    def test_prompt_only_label_property_differs(self):
        c = cases()[0]
        docs = selected(c, "target_decoy_two_first")
        bundle, originals, frontier = evidence(c, docs, "test-label")
        bundle.validate(c.question, originals, frontier=frontier, revoked=set())
        labels = bundle.delivered()
        a = prompt_messages(c.question, labels, "labeled")
        b = prompt_messages(c.question, labels, "unlabeled")
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[0]["content"], SYSTEM)
        encoded_a = json.loads(a[1]["content"])
        encoded_b = json.loads(b[1]["content"])
        self.assertEqual(encoded_a["question"], encoded_b["question"])
        self.assertEqual(encoded_a["question_time"], encoded_b["question_time"])
        self.assertEqual(
            [
                dict(observed_at=x["observed_at"], text=x["text"])
                for x in encoded_a["evidence"]
            ],
            encoded_b["evidence"],
        )
        self.assertTrue(all("label" in item for item in encoded_a["evidence"]))
        self.assertTrue(all("label" not in item for item in encoded_b["evidence"]))
        self.assertEqual(
            [x["text"] for x in encoded_a["evidence"]],
            [x["excerpt"] for x in bundle.delivered()],
        )

    def test_invalid_presentation_and_bad_token_ceiling(self):
        c = cases()[0]
        with self.assertRaises(ValueError):
            prompt_messages(c.question, (), "unregistered")
        fake = ToyShared()
        module = types.ModuleType("bundle_reader")
        module.GENERATION = dict(
            max_new_tokens=64, do_sample=False, num_beams=1, use_cache=True
        )
        module.PromptBudgetError = ValueError
        with patch.dict(sys.modules, {"bundle_reader": module}):
            obj = AnswerOnlyReader(fake, "labeled")
            bundle, originals, frontier = evidence(
                c, selected(c, "single_fact"), "test"
            )
            with self.assertRaises(ValueError):
                obj.compile_input(
                    c.question,
                    bundle,
                    originals,
                    frontier=frontier,
                    revoked=set(),
                    token_limit=512,
                )
            with self.assertRaises(ValueError):
                AnswerOnlyReader(fake, "nope")
            ids, receipt = obj.compile_input(
                c.question,
                bundle,
                originals,
                frontier=frontier,
                revoked=set(),
                token_limit=TOKEN_LIMIT,
            )
            self.assertEqual(len(ids), receipt["input_tokens"])
            self.assertEqual(receipt["delivered_evidence"], bundle.delivered())

    def test_error_scoring_never_counts_missing_as_answer(self):
        cs = cases()[:1]
        good = cs[0]
        rows = []
        for arm, presentation in ALL_ARMS:
            docs = selected(good, arm)
            rows.append(
                dict(
                    qid=good.question.identity,
                    arm=arm,
                    presentation=presentation,
                    selected=[d.identity for d in docs],
                    status="succeeded",
                    answer=ABSTAIN,
                )
            )
        scores, groups = score(rows, cs)
        self.assertEqual(len(scores), 7)
        self.assertEqual(len(groups), 7)
        self.assertTrue(
            all(
                item["conditional_success"] == 1
                for item in groups
                if item["arm"] in ("decoy_one", "no_evidence")
            )
        )
        with self.assertRaises(ValueError):
            score(rows[:-1], cs)
        with self.assertRaises(ValueError):
            score(rows + rows[:1], cs)
        rows[0]["status"] = "failed"
        del rows[0]["answer"]
        scores, groups = score(rows, cs)
        self.assertIsNone(scores[0]["success"])
        self.assertEqual(sum(x["failed"] for x in groups), 1)

    def test_correct_token_without_evidence_is_not_success(self):
        c = cases()[0]
        self.assertTrue(outcome(c, "single_fact", "labeled", c.answer)["success"])
        self.assertFalse(outcome(c, "decoy_one", "labeled", c.answer)["success"])
        self.assertTrue(
            outcome(c, "decoy_one", "labeled", c.answer)["unsupported_token_output"]
        )
        self.assertTrue(outcome(c, "no_evidence", "unlabeled", ABSTAIN)["success"])
        self.assertFalse(outcome(c, "single_fact", "unlabeled", ABSTAIN)["success"])
        self.assertTrue(
            outcome(c, "target_decoy_two_first", "labeled", "E1 E2")["label_only_echo"]
        )

    def test_invalid_mocked_reader_stays_failed_and_raw_sealed(self):
        c = cases()[0]
        fake = ToyShared()

        def emit(self, query, bundle, originals, *, frontier, revoked, token_limit):
            del query, bundle, originals, frontier, revoked, token_limit
            raise RuntimeError("injected model failure")

        mocked = types.ModuleType("bundle_reader")
        mocked.GENERATION = dict(
            max_new_tokens=64, do_sample=False, num_beams=1, use_cache=True
        )
        mocked.PromptBudgetError = ValueError
        with (
            patch.dict(sys.modules, {"bundle_reader": mocked}),
            tempfile.TemporaryDirectory() as temp,
            patch(
                "system2_onehop_label_ablation.load_previous",
                return_value={"raw_sha256": "a" * 64, "verified_files": 25},
            ),
            patch.object(AnswerOnlyReader, "answer", emit),
            patch("system2_onehop_label_ablation.cases", return_value=(c,)),
        ):
            destination = Path(temp) / "run"
            with self.assertRaises(RuntimeError):
                run(destination, fake, ARCHIVE, source_commit="b" * 40, count=1)
            data = [
                json.loads(s)
                for s in (destination / "raw-answers.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(data), 7)
            self.assertTrue(
                all(
                    x["status"] == "failed" and x["cost_may_be_incomplete"]
                    for x in data
                )
            )
            seal = json.loads((destination / "raw-seal.json").read_text())
            self.assertEqual(
                seal["sha256"],
                hashlib.sha256(
                    (destination / "raw-answers.jsonl").read_bytes()
                ).hexdigest(),
            )
            self.assertTrue((destination / "summary.json").is_file())
            self.assertTrue((destination / "run-failure.json").is_file())

    def test_fake_full_run_plan_seal_and_scoring(self):
        case = cases()[0]
        fake = ToyShared()

        def emit(self, query, bundle, originals, *, frontier, revoked, token_limit):
            _, rec = self.compile_input(
                query,
                bundle,
                originals,
                frontier=frontier,
                revoked=revoked,
                token_limit=token_limit,
            )
            docs = bundle.delivered()
            answer = ABSTAIN if not docs else case.answer
            rec.update(
                reader_identity=READER_IDENTITY,
                reader_profile=self.profile,
                trainable_parameters=0,
                answer_postprocessed=False,
                generated_tokens=9,
            )
            return answer, rec

        mocked = types.ModuleType("bundle_reader")
        mocked.GENERATION = dict(
            max_new_tokens=64, do_sample=False, num_beams=1, use_cache=True
        )
        mocked.PromptBudgetError = ValueError
        with (
            patch.dict(sys.modules, {"bundle_reader": mocked}),
            tempfile.TemporaryDirectory() as temp,
            patch(
                "system2_onehop_label_ablation.load_previous",
                return_value={"raw_sha256": "a" * 64, "verified_files": 25},
            ),
            patch.object(AnswerOnlyReader, "answer", emit),
            patch("system2_onehop_label_ablation.cases", return_value=(case,)),
        ):
            result = run(
                Path(temp) / "run", fake, ARCHIVE, source_commit="b" * 40, count=1
            )
            self.assertEqual(result["planned"], 7)
            dest = Path(temp) / "run"
            seal = json.loads((dest / "raw-seal.json").read_text())
            self.assertFalse(seal["scoring_started"])
            self.assertEqual(seal["rows"], 7)
            self.assertTrue((dest / "scored.json").is_file())
            self.assertTrue((dest / "summary.json").is_file())
            self.assertFalse((dest / "run-failure.json").is_file())

    def test_source_identity_validation_rejects_mutated_original(self):
        c = cases()[0]
        docs = selected(c, "single_fact")
        bundle, orig, frontier = evidence(c, docs, "original")
        modified = orig.copy()
        modified[docs[0].identity] = replace(docs[0], content="different value")
        with self.assertRaises(ValueError):
            bundle.validate(c.question, modified, frontier=frontier, revoked=set())

    def test_gate_preregistered_not_picked_after_scoring(self):
        s = Path(__file__).with_name("system2_onehop_label_ablation.py").read_text()
        self.assertIn("min_unlabeled_competing_exact=15", s)
        self.assertIn("min_decoy_only_refusals=18", s)
        self.assertIn("min_empty_refusals=18", s)


if __name__ == "__main__":
    unittest.main()
