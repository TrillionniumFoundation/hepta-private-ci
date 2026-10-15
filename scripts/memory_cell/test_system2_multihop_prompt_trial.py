"""Frozen-Reader prompt controls, archive replay and failure census tests."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from system2_multihop_completed_audit import (
    READER_IDENTITY,
    READER_PROFILE,
    read_completed,
)
from system2_multihop_evidence import fixed_cases, choose
from system2_multihop_prompt_trial import (
    ALL_PROMPT_VARIANTS,
    DEMONSTRATIONS,
    GENERATION_LIMIT,
    PROMPT_VARIANTS,
    SOURCE_ARMS,
    PromptVariantReader,
    prompt_messages,
    run,
    summarize,
    verify_control_inputs,
)

ARCHIVE = Path(
    os.environ.get(
        "HEPTA_SYSTEM2_COMPLETED_MULTIHOP_ARCHIVE",
        str(Path(__file__).parent / "_completed100_archive.zip"),
    )
)


class FakeBudgetError(ValueError):
    pass


class FakeTokenizer:
    chat_template = "fixed-reader-chat-template"

    def __init__(self):
        self.max_length_override = None

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize and add_generation_prompt
        content = " ".join(x["content"] for x in messages)
        return (
            [17] * self.max_length_override
            if self.max_length_override is not None
            else [max(1, len(w) % 251) for w in re.findall(r"\S+", content)]
        )


class FakeModel:
    training = False

    def parameters(self):
        return ()


class FakeShared:
    identity = READER_IDENTITY
    profile = READER_PROFILE
    inventory = {"pinned": True}
    base_digest = "frozen"

    def __init__(self):
        self.tokenizer = FakeTokenizer()
        self.model = FakeModel()
        self.checked = 0

    def verify_frozen(self):
        self.checked += 1


@dataclass(frozen=True)
class FakeBundle:
    selected: tuple

    def validate(self, query, originals, *, frontier, revoked):
        if (
            any(
                d.identity not in originals
                or d.scope != query.scope
                or d.root in revoked
                for d in self.selected
            )
            or frontier != "test-frontier"
        ):
            raise ValueError("invalid query/scope")

    def delivered(self):
        return [
            dict(
                label=f"E{i}",
                original_id=d.identity,
                excerpt=d.content,
                observed_at=d.observed_at,
            )
            for i, d in enumerate(self.selected, 1)
        ]

    def seal(self):
        return "fake-bundle:" + ":".join(d.identity for d in self.selected)


def fake_evidence(case, selected, _arm):
    return (
        FakeBundle(tuple(selected)),
        {d.identity: d for d in case.documents},
        "test-frontier",
    )


class FakeFrozenReader:
    calls = 0
    fail_after = None

    def answer(self, query, bundle, originals, *, frontier, revoked, token_limit):
        FakeFrozenReader.calls += 1
        if (
            FakeFrozenReader.fail_after
            and FakeFrozenReader.calls >= FakeFrozenReader.fail_after
        ):
            raise RuntimeError("injected Reader execution failure")
        ids, receipt = self.compile_input(
            query,
            bundle,
            originals,
            frontier=frontier,
            revoked=revoked,
            token_limit=token_limit,
        )
        answer = "I do not have enough evidence."
        return answer, receipt | dict(
            reader_identity=self.identity,
            reader_profile=self.profile,
            generated_tokens=9,
            generated_ids_digest=hashlib.sha256(answer.encode()).hexdigest(),
            seconds=0.001,
            trainable_parameters=0,
            answer_postprocessed=False,
            production_accepted=False,
        )


@contextmanager
def mock_bundle_reader():
    obj = types.ModuleType("bundle_reader")
    obj.GENERATION = dict(
        max_new_tokens=GENERATION_LIMIT, do_sample=False, num_beams=1, use_cache=True
    )
    obj.PromptBudgetError = FakeBudgetError
    obj.FrozenBundleReader = FakeFrozenReader
    with patch.dict(sys.modules, {"bundle_reader": obj}):
        yield obj


class PromptReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ARCHIVE.is_file():
            raise unittest.SkipTest("old hosted archive not staged in source slice")
        cls.audited = read_completed(ARCHIVE)

    def setUp(self):
        FakeFrozenReader.calls = 0
        FakeFrozenReader.fail_after = None

    def test_prompt_variants_use_same_question_and_do_not_get_gold(self):
        c = fixed_cases(1)[0]
        selected = choose("joined_top3", c.question, c.documents)
        delivered = FakeBundle(selected).delivered()
        for variant in PROMPT_VARIANTS:
            messages = prompt_messages(variant, c.question, delivered)
            self.assertEqual([x["role"] for x in messages], ["system", "user"])
            self.assertIn(c.question.content, messages[1]["content"])
            self.assertNotIn(c.answer, messages[0]["content"])
            self.assertTrue(all(d.content in messages[1]["content"] for d in selected))
            self.assertIn("I do not have enough evidence.", messages[0]["content"])
        self.assertIn("Examples of the output contract", DEMONSTRATIONS)
        self.assertEqual(len(ALL_PROMPT_VARIANTS), 4)
        with self.assertRaises(ValueError):
            prompt_messages("oracle", c.question, delivered)

    def test_prompt_reader_shared_model_and_no_postprocessing(self):
        with mock_bundle_reader():
            shared = FakeShared()
            wrapper = PromptVariantReader(shared, "direct")
            self.assertIs(wrapper.model, shared.model)
            self.assertIs(wrapper.tokenizer, shared.tokenizer)
            self.assertEqual(wrapper.identity, shared.identity)
            self.assertNotEqual(wrapper.profile, shared.profile)
            c = fixed_cases(1)[0]
            selected = choose("joined_top3", c.question, c.documents)
            bundle, orig, frontier = fake_evidence(c, selected, "joined_top3")
            answer, r = wrapper.answer(
                c.question,
                bundle,
                orig,
                frontier=frontier,
                revoked=set(),
                token_limit=1024,
            )
            self.assertEqual(answer, "I do not have enough evidence.")
            self.assertFalse(r["answer_postprocessed"])
            self.assertEqual(r["delivered_evidence"], bundle.delivered())

    def test_prompt_cap_hard_fail_no_truncation(self):
        with mock_bundle_reader():
            shared = FakeShared()
            wrapper = PromptVariantReader(shared, "demonstrated")
            c = fixed_cases(1)[0]
            bundle, orig, frontier = fake_evidence(c, (), "no_evidence")
            shared.tokenizer.max_length_override = 1025
            with self.assertRaises(FakeBudgetError):
                wrapper.compile_input(
                    c.question,
                    bundle,
                    orig,
                    frontier=frontier,
                    revoked=set(),
                    token_limit=1024,
                )
            with self.assertRaises(ValueError):
                wrapper.compile_input(
                    c.question,
                    bundle,
                    orig,
                    frontier=frontier,
                    revoked=set(),
                    token_limit=2048,
                )

    def test_training_and_identity_mutation_fail_closed(self):
        with mock_bundle_reader():
            shared = FakeShared()
            shared.identity = "different"
            with self.assertRaises(ValueError):
                PromptVariantReader(shared, "direct")
            shared.identity = READER_IDENTITY
            shared.model.training = True
            with self.assertRaises(ValueError):
                PromptVariantReader(shared, "direct")
            shared.model.training = False
            with self.assertRaises(ValueError):
                PromptVariantReader(shared, "unknown")

    def test_historical_controls_require_actual_token_input_seal(self):
        # A fake compile_input is wired to the archived exact receipt for each
        # source condition; a mutated model tokenizer digest must fail.
        archived = self.audited
        # Duplicate selections can exist across different arms: use a stable
        # lookup by original bundle digest instead of an ambiguous arm key.
        recs = {}
        for row in archived["rows"]:
            if row["arm"] in SOURCE_ARMS:
                recs[row["qid"], tuple(row["selected"])] = row["reader"]

        class ExactControls(FakeShared):
            def compile_input(
                self, query, bundle, _orig, *, frontier, revoked, token_limit
            ):
                r = recs[query.identity, tuple(d.identity for d in bundle.selected)]
                return [1] * r["input_tokens"], {
                    k: r[k]
                    for k in (
                        "input_ids_digest",
                        "query_digest",
                        "bundle_digest",
                        "input_tokens",
                    )
                }

        with patch("system2_multihop_prompt_trial.evidence", side_effect=fake_evidence):
            self.assertEqual(verify_control_inputs(ExactControls(), archived), 60)
            key = next(iter(recs))
            recs[key] = recs[key] | dict(input_ids_digest="wrong")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                verify_control_inputs(ExactControls(), archived)

    def test_full_fake_reader_trial_and_postseal_scoring(self):
        with mock_bundle_reader(), tempfile.TemporaryDirectory() as tmp:
            shared = FakeShared()
            out = Path(tmp) / "trial"
            with (
                patch(
                    "system2_multihop_prompt_trial.evidence", side_effect=fake_evidence
                ),
                patch(
                    "system2_multihop_prompt_trial.verify_control_inputs",
                    return_value=60,
                ),
            ):
                result = run(out, shared, ARCHIVE, source_commit="a" * 40, count=2)
            self.assertEqual(FakeFrozenReader.calls, 18)
            self.assertEqual(
                (out / "new-raw-answers.jsonl").read_text().count("\n"), 18
            )
            self.assertEqual(len(result["scored"]), 24)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(
                (summary["new_calls"], summary["reused_old_calls"]), (18, 6)
            )
            raw = (out / "new-raw-answers.jsonl").read_bytes()
            self.assertEqual(
                hashlib.sha256(raw).hexdigest(),
                json.loads((out / "new-answer-seal.json").read_text())["sha256"],
            )
            self.assertEqual(shared.checked, 2)
            self.assertEqual(
                result["candidate_disposition"], "reader_prompt_preflight_not_qualified"
            )

    def test_failure_retains_attempt_without_fake_negative_labels(self):
        with mock_bundle_reader(), tempfile.TemporaryDirectory() as tmp:
            shared = FakeShared()
            FakeFrozenReader.fail_after = 2
            out = Path(tmp) / "trial"
            with (
                patch(
                    "system2_multihop_prompt_trial.evidence", side_effect=fake_evidence
                ),
                patch(
                    "system2_multihop_prompt_trial.verify_control_inputs",
                    return_value=60,
                ),
            ):
                with self.assertRaises(RuntimeError):
                    run(out, shared, ARCHIVE, source_commit="b" * 40, count=1)
            r = json.loads((out / "run-failure.json").read_text())
            self.assertFalse(r["complete"])
            self.assertTrue(r["missing_work_not_imputed"])
            lines = list(
                map(
                    json.loads, (out / "new-raw-answers.jsonl").read_text().splitlines()
                )
            )
            self.assertEqual([r["status"] for r in lines], ["succeeded", "failed"])
            self.assertFalse((out / "new-answer-seal.json").exists())
            self.assertFalse((out / "summary.json").exists())

    def test_prompt_scoring_rejects_duplicate_or_missing_arm(self):
        c = fixed_cases(1)[0]
        rows = []
        for arm in SOURCE_ARMS:
            for variant in ALL_PROMPT_VARIANTS:
                docs = choose(arm, c.question, c.documents)
                rows.append(
                    dict(
                        qid=c.question.identity,
                        arm=arm,
                        prompt_variant=variant,
                        selected=[d.identity for d in docs],
                        answer="I do not have enough evidence.",
                        status="succeeded",
                        reader=dict(generated_tokens=10, input_tokens=60),
                    )
                )
        self.assertEqual(len(summarize(rows, (c,))["groups"]), 12)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            summarize(rows[:-1], (c,))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            summarize(rows + rows[:1], (c,))


if __name__ == "__main__":
    unittest.main()
