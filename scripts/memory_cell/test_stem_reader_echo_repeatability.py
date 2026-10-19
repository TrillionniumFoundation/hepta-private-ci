"""No-model regressions; these fixtures are NOT pretrained task evidence."""

from copy import deepcopy
import hashlib
import json
import unittest

from stem_audit_archive import AuditError
from stem_reader_echo_repeatability import ARMS, PHASES, STAGES, compare_reader_outputs


def _receipt(qid, *, no_evidence=False):
    source = (
        []
        if no_evidence
        else [
            dict(
                id="original-source",
                root="root",
                scope="scope-" + qid,
                label="E1",
                observed_at="2024-01-01",
                excerpt="Original source.",
            )
        ]
    )
    query = dict(
        identity=qid,
        family="family",
        scope="scope-" + qid,
        content="What happened?",
        observed_at="2024-01-02",
    )
    identity, profile = "reader-pin", "prompt-pin"
    canonical = hashlib.sha256(
        json.dumps(
            (identity, profile, query, source),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return dict(
        observable_query=query,
        delivered_evidence=source,
        generator_identity=identity,
        generator_profile=profile,
        canonical_request_digest=canonical,
        input_ids_digest="a" * 64,
        generated_ids_digest="b" * 64,
        generated_tokens=4,
        reached_token_ceiling=False,
    )


def fixture():
    questions = {"train": ["train-" + str(i) for i in range(48)]}
    questions.update({p: [p + "-" + str(i) for i in range(8)] for p in PHASES})
    plan = dict(
        questions=questions,
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
        generator_config=dict(max_new_tokens=96, do_sample=False),
        generator_template_digest="prompt-pin",
        reader_inventory="reader-pin",
        dataset_sha256="source-pin",
        retriever_inventory="retriever-pin",
        ranker_inventory="ranker-pin",
        window_budget=dict(candidates=32),
        primary_policy="forced-top1",
    )
    raw = []
    no_evidence = []
    for phase in PHASES:
        for qid in questions[phase]:
            for stage in STAGES:
                for arm in ARMS:
                    raw.append(
                        dict(
                            stage=stage,
                            phase=phase,
                            question_id=qid,
                            arm=arm,
                            status="succeeded",
                            answer="Fixture answer.",
                            receipt=_receipt(qid),
                        )
                    )
            no_evidence.append(
                dict(
                    phase=phase,
                    question_id=qid,
                    status="succeeded",
                    answer="Fixture answer.",
                    receipt=_receipt(qid, no_evidence=True),
                )
            )
    report = dict(
        census=dict(complete=True),
        logical_policy_attempts=576,
        production_accepted=False,
        semantic_citation_precision=None,
    )
    return dict(plan=plan, raw=raw, empty=no_evidence, report=report)


class RepeatabilityTests(unittest.TestCase):
    def test_fixed_32_question_controls_not_576_independent_examples(self):
        a = fixture()
        result = compare_reader_outputs(a, deepcopy(a))
        self.assertEqual(result["independent_question_ids"], 32)
        self.assertTrue(result["two_run_repeats_are_not_independent_examples"])
        self.assertEqual(
            result["controls"]["original_evidence"]["unique_questions"], 32
        )
        self.assertEqual(
            result["controls"]["zero_evidence"]["emitted_structural_citation_markers"],
            0,
        )
        self.assertFalse(result["scale_out_permitted"])
        self.assertFalse(result["production_accepted"])

    def test_json_echo_is_reported_not_promoted_as_answer_quality(self):
        a = fixture()
        frozen = next(
            row
            for row in a["raw"]
            if (row["stage"], row["phase"], row["arm"]) == (48, "test", "frozen_rerank")
        )
        frozen["answer"] = json.dumps(
            dict(
                question="What happened?",
                question_time="2024-01-02",
                evidence=[
                    dict(label="E1", observed_at="2024-01-01", text="Original source.")
                ],
            ),
            ensure_ascii=False,
        )[:60]
        result = compare_reader_outputs(a, deepcopy(a))
        out = result["controls"]["original_evidence"]
        self.assertEqual(out["generated_json_question_prefix"], 1)
        self.assertEqual(out["exact_user_prompt_prefix"], 1)
        self.assertFalse(result["citation_quality_qualification"])
        self.assertFalse(result["independent_reader_sufficiency_verified"])
        self.assertNotIn("What happened?", json.dumps(result))

    def test_modified_answer_or_generated_tokens_across_runs_reject(self):
        for key in ("answer", "generated_ids_digest"):
            a = fixture()
            b = deepcopy(a)
            row = next(
                x for x in b["raw"] if x["stage"] == 48 and x["arm"] == "frozen_rerank"
            )
            if key == "answer":
                row[key] = "Changed result"
            else:
                row["receipt"][key] = "c" * 64
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(AuditError, "changed across runs"),
            ):
                compare_reader_outputs(a, b)

    def test_misaligned_model_or_question_receipts_reject(self):
        for field in (
            "generator_identity",
            "generator_profile",
            "canonical_request_digest",
        ):
            a = fixture()
            row = next(
                x for x in a["raw"] if x["stage"] == 48 and x["arm"] == "frozen_rerank"
            )
            row["receipt"][field] = "forged"
            with self.subTest(field=field), self.assertRaises(AuditError):
                compare_reader_outputs(a, deepcopy(a))

    def test_missing_or_duplicate_policy_or_no_evidence_fails_closed(self):
        for target in ("raw", "empty"):
            for action in ("remove", "duplicate"):
                a = fixture()
                if action == "remove":
                    a[target].pop()
                else:
                    a[target].append(deepcopy(a[target][0]))
                with (
                    self.subTest(target=target, action=action),
                    self.assertRaises(AuditError),
                ):
                    compare_reader_outputs(a, deepcopy(a))

    def test_noncanonical_token_ceiling_and_source_evidence_reject(self):
        for action in ("ceiling", "leakage"):
            a = fixture()
            row = a["empty"][0]
            if action == "ceiling":
                row["receipt"]["reached_token_ceiling"] = True
            else:
                row["receipt"]["delivered_evidence"] = [dict(label="E1")]
            with self.subTest(action=action), self.assertRaises(AuditError):
                compare_reader_outputs(a, deepcopy(a))

    def test_changed_reader_or_source_registration_fails_before_comparison(self):
        for key in ("reader_inventory", "source_visibility_policy", "questions"):
            a = fixture()
            b = deepcopy(a)
            if key == "questions":
                b["plan"][key]["test"][0] = "other"
            else:
                b["plan"][key] = "not same"
            with self.subTest(key=key), self.assertRaises(AuditError):
                compare_reader_outputs(a, b)


if __name__ == "__main__":
    unittest.main()
