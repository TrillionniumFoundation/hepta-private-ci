"""Run-independent anti-forgery tests for the latest two STRICT Stem ZIPs."""

from copy import deepcopy
import unittest

from stem_latest_native_pair_audit import (
    EARLIER,
    LATER,
    equal_policy,
    ARMS,
    STAGES,
    PHASES,
)


def fixture():
    return dict(
        stage=48,
        phase="test",
        question_id="q-fixed",
        arm="gated",
        status="succeeded",
        family="locked-family",
        cell="general",
        selected=0,
        answer="Frozen Reader text.",
        pool_digest="pinned-pool",
        feature_digest="features",
        head_sha256="a" * 64,
        encoder_identity="locked-encoder",
        head_seconds=0.0001,
        inclusive_attempt_seconds=1.0,
        receipt=dict(
            generator_parameter_updates=0,
            generator_identity="locked-reader",
            generator_profile="locked-template",
            semantic_citation_precision=None,
            production_accepted=False,
            delivered_evidence=[dict(root="root", original_id="source", label="E1")],
            input_ids_digest="reader-input",
            generated_ids_digest="reader-output",
            actual_reader_execution=True,
            reused_from=None,
            generation_seconds=1.1,
            incremental_generation_seconds=1.1,
        ),
    )


class LatestMatchedAuditTests(unittest.TestCase):
    def test_only_real_clocks_can_differ_without_changing_policy(self):
        first = fixture()
        second = deepcopy(first)
        second["head_seconds"] = 0.0004
        second["inclusive_attempt_seconds"] = 1.5
        second["receipt"]["generation_seconds"] = 2.0
        second["receipt"]["incremental_generation_seconds"] = 2.0
        equal_policy(first, second)

    def test_source_choice_or_actual_answer_change_fails(self):
        for key, value in (
            ("selected", 1),
            ("answer", "Other frozen Reader text."),
            ("head_sha256", "b" * 64),
            ("pool_digest", "different-pool"),
            ("feature_digest", "different-features"),
            ("encoder_identity", "unregistered-encoder"),
            ("status", "failed"),
        ):
            a = fixture()
            b = deepcopy(a)
            b[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                equal_policy(a, b)

    def test_delivered_source_input_and_generated_tokens_must_match(self):
        for field, bad in (
            ("generator_identity", "different-reader"),
            ("generator_profile", "different-prompt"),
            ("delivered_evidence", []),
            ("input_ids_digest", "different-tokens"),
            ("generated_ids_digest", "different-answer-tokens"),
            ("actual_reader_execution", False),
            ("reused_from", "different-original-request"),
        ):
            a = fixture()
            b = deepcopy(a)
            b["receipt"][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                equal_policy(a, b)

    def test_missing_recorded_policy_or_false_production_claim_reject(self):
        for field, value in (
            ("generator_parameter_updates", 1),
            ("production_accepted", True),
            ("semantic_citation_precision", 1.0),
        ):
            a = fixture()
            b = deepcopy(a)
            b["receipt"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                equal_policy(a, b)
        a = fixture()
        b = deepcopy(a)
        b["receipt"].pop("generator_profile")
        with self.assertRaises(ValueError):
            equal_policy(a, b)

    def test_two_strict_original_execution_pins_are_distinct(self):
        self.assertEqual(len(ARMS), 6)
        self.assertEqual(STAGES, (16, 32, 48))
        self.assertEqual(len(PHASES), 4)
        self.assertEqual(EARLIER[3], LATER[3])
        self.assertEqual(EARLIER[3], 146)
        self.assertNotEqual(EARLIER[0], LATER[0])
        self.assertNotEqual(EARLIER[2], LATER[2])
        self.assertTrue(all(len(pin) == 64 for pin in (EARLIER[2], LATER[2])))


if __name__ == "__main__":
    unittest.main()
