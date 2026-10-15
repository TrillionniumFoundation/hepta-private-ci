"""Source-bound and fail-closed tests for lexical Qwen2.5 factorial."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_multihop_trial import ABSTAIN, evidence
from system2_reader_paired_capacity_audit import STRONG_READER_ID
from system2_reader_lexical_factorial import (
    ARMS,
    CALLS,
    NEW_INDICES,
    POSITIVE,
    PROFILES,
    base_cases,
    delivery,
    factors,
    messages,
    run,
    score,
    system_instruction,
    transform,
)


class FakeReader:
    identity = STRONG_READER_ID
    inventory = {"model.safetensors": {"sha256": "example"}}
    verified = False

    def verify_frozen(self):
        self.verified = True


def stub_parent(_):
    files = {
        "reference-inventory.json": json.dumps(
            dict(
                model_snapshot_inventory=FakeReader.inventory,
                revision="a338b55dd21219a5f4da42bc11a9313d1a27d4cc",
                model_id="Qwen/Qwen2.5-0.5B-Instruct",
            )
        ).encode()
    }
    return (
        files,
        dict(reference_reader_identity=STRONG_READER_ID),
        {("prior" + str(i), "fake"): {} for i in range(160)},
    )


def stub_answer(reader, case, docs, arm, profile):
    variant, _ = delivery(case, arm, profile)
    b, _, _ = evidence(variant, docs, "lexical:" + profile + ":" + arm)
    return ABSTAIN, dict(
        reader_identity=reader.identity,
        bundle_digest=b.seal(),
        input_tokens=80,
        generated_tokens=8,
        cpu_time_ns=1,
    )


class LexicalFactorialTests(unittest.TestCase):
    def test_bounded_new_cohort(self):
        cases = base_cases()
        self.assertEqual(
            (len(cases), list(NEW_INDICES)[0], list(NEW_INDICES)[-1]), (20, 60, 79)
        )
        self.assertEqual(len({c.question.identity for c in cases}), 20)
        self.assertEqual(CALLS, 320)

    def test_profiles_have_registered_2_by_2_cross(self):
        self.assertEqual(
            set(factors(p) for p in PROFILES),
            {(False, False), (True, False), (False, True), (True, True)},
        )
        for bad in ("", "other", None):
            with self.assertRaises(ValueError):
                factors(bad)

    def test_every_transformed_question_has_exact_source_id_and_bytes(self):
        case = base_cases()[0]
        for profile in PROFILES:
            variant, mapping = transform(case, profile)
            self.assertEqual(len(variant.documents), len(case.documents))
            self.assertEqual(
                len({d.identity for d in variant.documents}), len(case.documents)
            )
            self.assertEqual(variant.required_id, mapping[case.required_id].identity)
            self.assertTrue(
                variant.answer.startswith("TAG-" if profile.endswith("tag") else "TOK-")
            )
            self.assertEqual(variant.question.scope, case.question.scope)

    def test_selection_receives_redacted_gold_label(self):
        case = base_cases()[0]

        def inspect(source, arm):
            self.assertEqual(source.answer, "<redacted-gold>")
            return (
                tuple(d for d in source.documents if d.identity == source.required_id)
                if arm == "no_evidence"
                else ()
            )

        # Patching into the selection function verifies that no gold is
        # passed to the online source choice. The fake return must still
        # fail the predeclared support/cardinality condition.
        with patch("system2_reader_lexical_factorial.selected", side_effect=inspect):
            with self.assertRaises(ValueError):
                delivery(case, "no_evidence", "inventory_tag")

    def test_complete_and_incomplete_sources_per_arm(self):
        case = base_cases()[0]
        for profile in PROFILES:
            for arm in ARMS:
                variant, selected = delivery(case, arm, profile)
                self.assertEqual(
                    variant.required_id in {x.identity for x in selected},
                    arm in POSITIVE,
                )
                b, originals, frontier = evidence(
                    variant, selected, "lexical:" + profile + ":" + arm
                )
                b.validate(
                    variant.question, originals, frontier=frontier, revoked=set()
                )

    def test_only_registered_system_instruction_and_quoted_sources(self):
        case = base_cases()[0]
        for profile in PROFILES:
            variant, chosen = delivery(case, "single_fact", profile)
            b, _, _ = evidence(variant, chosen, "lexical:" + profile + ":single_fact")
            lines = messages(variant, b.delivered(), profile)
            self.assertIn("I do not have enough evidence.", lines[0]["content"])
            self.assertEqual(lines[0]["content"], system_instruction(profile))
            body = json.loads(lines[1]["content"])
            self.assertNotIn("gold", body)
            self.assertEqual(body["evidence"][0]["text"], chosen[0].content)
            self.assertEqual(body["evidence"][0]["label"], "E1")

    def test_full_source_refusal_is_not_counted_as_correct(self):
        case = base_cases()[0]
        for profile in PROFILES:
            positive = score(case, "single_fact", profile, ABSTAIN)
            self.assertTrue(positive["over_refusal"])
            self.assertFalse(positive["task_success"])
            negative = score(case, "decoy_one", profile, ABSTAIN)
            self.assertTrue(negative["task_success"])
            self.assertFalse(negative["over_refusal"])
            output = score(
                case, "single_fact", profile, transform(case, profile)[0].answer
            )
            self.assertTrue(output["task_success"])

    def test_unsupported_token_copy_is_not_negative_success(self):
        case = base_cases()[0]
        for profile in PROFILES:
            fake = score(case, "decoy_one", profile, transform(case, profile)[0].answer)
            self.assertFalse(fake["task_success"])
            self.assertTrue(fake["unsupported_token_copy"])

    def test_small_full_runner_seals_results_before_scoring(self):
        fake = FakeReader()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trial"
            (Path(tmp) / "parent.zip").write_bytes(b"mock-pinned-source")
            with (
                patch(
                    "system2_reader_lexical_factorial.base_cases",
                    return_value=(base_cases()[0],) * 20,
                ),
                patch(
                    "system2_reader_lexical_factorial.open_strong",
                    side_effect=stub_parent,
                ),
                patch(
                    "system2_reader_lexical_factorial.run_frozen",
                    side_effect=stub_answer,
                ),
            ):
                # Duplicate qids are invalid and detected in complete census,
                # even when the mock source supplies repeated objects.
                with self.assertRaises(ValueError):
                    run(
                        out,
                        fake,
                        parent_archive=Path(tmp) / "parent.zip",
                        source_commit="a" * 40,
                    )
            self.assertFalse((out / "summary.json").exists())
            self.assertTrue((out / "failure.json").exists())

    def test_injected_reader_failure_retains_started_and_failed_rows(self):
        fake = FakeReader()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trial"
            (Path(tmp) / "parent.zip").write_bytes(b"mock-pinned-source")
            with (
                patch(
                    "system2_reader_lexical_factorial.open_strong",
                    side_effect=stub_parent,
                ),
                patch(
                    "system2_reader_lexical_factorial.run_frozen",
                    side_effect=RuntimeError("injected"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    run(
                        out,
                        fake,
                        parent_archive=Path(tmp) / "parent.zip",
                        source_commit="b" * 40,
                    )
            self.assertTrue((out / "failure.json").is_file())
            self.assertEqual(len((out / "starts.jsonl").read_text().splitlines()), 1)
            self.assertEqual(
                len((out / "raw-answers.jsonl").read_text().splitlines()), 1
            )
            self.assertFalse((out / "raw-seal.json").exists())

    def test_empty_or_non_sha_generating_identity_rejected(self):
        fake = FakeReader()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trial"
            with self.assertRaises(ValueError):
                run(
                    out,
                    fake,
                    parent_archive=Path(tmp) / "parent.zip",
                    source_commit="no-commit",
                )
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
