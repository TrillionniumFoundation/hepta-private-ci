"""Candidate-size counters cannot be mistaken for Head benefit."""

import unittest

from stem_audit_archive import AuditError
from stem_audit_candidate import candidate_capacity
from test_stem_audit import fixture


def sample():
    data = fixture()
    count = dict(select=1, retention=2, test=4, transfer=0)
    encoding = [
        dict(
            question_id=phase,
            backend="frozen",
            cost=dict(
                cache_hit=False, extraction=dict(encoder_identity="pinned", pairs=n)
            ),
        )
        for phase, n in count.items()
    ]
    return data, encoding


class CandidateCapacityTests(unittest.TestCase):
    def test_rankable_and_nonrankable_are_separate(self):
        data, encoding = sample()
        result = candidate_capacity(data["plan"], encoding, data["raw"], {})
        self.assertEqual(
            result["phase_census"]["select"]["forced_top1_no_competition"], 1
        )
        self.assertEqual(result["phase_census"]["retention"]["rankable_two_or_more"], 1)
        self.assertEqual(result["phase_census"]["test"]["rankable_two_or_more"], 1)
        self.assertEqual(result["phase_census"]["transfer"]["no_candidates"], 1)
        self.assertEqual(result["fresh_question_encodings"], 4)
        self.assertFalse(result["production_accepted"])

    def test_missing_without_original_failure_receipt_is_rejected(self):
        data, encoding = sample()
        with self.assertRaisesRegex(AuditError, "missing successful"):
            candidate_capacity(data["plan"], encoding[:-1], data["raw"], {})
        result = candidate_capacity(
            data["plan"],
            encoding[:-1],
            data["raw"],
            {"transfer": {"error_type": "ValueError"}},
        )
        self.assertEqual(
            result["phase_census"]["transfer"]["missing_or_failed_feature_encoding"], 1
        )

    def test_unregistered_and_changed_candidate_count_rejected(self):
        data, encoding = sample()
        copied = dict(encoding[0], question_id="unregistered")
        with self.assertRaisesRegex(AuditError, "unregistered"):
            candidate_capacity(data["plan"], encoding + [copied], data["raw"], {})
        copied = dict(
            question_id="select",
            backend="frozen",
            cost=dict(
                cache_hit=False, extraction=dict(encoder_identity="pinned", pairs=3)
            ),
        )
        with self.assertRaisesRegex(AuditError, "size changed"):
            candidate_capacity(data["plan"], encoding + [copied], data["raw"], {})

    def test_duplicate_frozen_cache_hit_is_not_a_new_question(self):
        data, encoding = sample()
        cache_hit = dict(
            question_id="select",
            backend="frozen",
            cost=dict(cache_hit=True, incremental_encoder_seconds=0),
        )
        report = candidate_capacity(
            data["plan"], encoding + [cache_hit], data["raw"], {}
        )
        self.assertEqual(report["fresh_question_encodings"], 4)
        self.assertEqual(report["repeated_pinned_frozen_misses"], 0)


if __name__ == "__main__":
    unittest.main()
