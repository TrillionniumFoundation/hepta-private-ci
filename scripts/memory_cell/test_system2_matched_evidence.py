"""Bounded selection mechanics with explicit fake-tokenizer fixtures."""

import hashlib
import unittest

from system2_matched_evidence import choose, summarize, verify_receipt


def token_receipt(indices, lengths=(10, 10, 10, 40)):
    tokens = 100 + sum(lengths[i] for i in indices)
    return dict(
        input_tokens=tokens,
        input_ids_digest=hashlib.sha256(repr(indices).encode()).hexdigest()
        if tokens <= 4096
        else None,
    )


class MatchedEvidenceTests(unittest.TestCase):
    def select(self, scores, lengths=(10, 10, 10, 40)):
        return choose(
            ["a", "b", "c", "d"],
            [4.0, 3.0, 2.0, 1.0],
            scores,
            lambda indices: token_receipt(indices, lengths),
        )

    def test_better_scoring_but_longer_evidence_cannot_exceed_reference(self):
        chosen, receipt = self.select([0.0, 1.0, 2.0, 100.0])
        self.assertEqual(chosen, [0, 1, 2])
        self.assertEqual(receipt["compiled_alternatives"], 4)
        self.assertEqual(sum(r["feasible"] for r in receipt["alternatives"]), 1)

    def test_shorter_candidate_changes_set_without_changing_cardinality(self):
        chosen, receipt = self.select([0.0, 1.0, 2.0, 100.0], (10, 10, 10, 5))
        self.assertEqual(chosen, [1, 2, 3])
        self.assertEqual(receipt["cardinality"], 3)
        self.assertLess(
            receipt["selected_input_tokens"], receipt["baseline_input_tokens"]
        )

    def test_full_prompt_count_not_additive_fragment_estimate(self):
        def measure(indices):
            r = token_receipt(indices, (1, 1, 1, 1))
            r["input_tokens"] = 200 if 3 in indices else 150
            return r

        chosen, _ = choose(["a", "b", "c", "d"], [4, 3, 2, 1], [0, 1, 2, 99], measure)
        self.assertEqual(chosen, [0, 1, 2])

    def test_ties_keep_frozen_set_and_canonical_rendering_order(self):
        chosen, _ = self.select([1.0, 1.0, 1.0, 1.0], (10, 10, 10, 10))
        self.assertEqual(chosen, [0, 1, 2])
        chosen, _ = self.select([0.0, 99.0, 2.0, 100.0], (10, 10, 10, 10))
        self.assertEqual(chosen, [1, 2, 3])

    def test_constant_score_offset_does_not_change_fixed_size_ranking(self):
        self.assertEqual(
            self.select([0.0, 1.0, 2.0, 10.0], (5, 5, 5, 5))[0],
            self.select([-100.0, -99.0, -98.0, -90.0], (5, 5, 5, 5))[0],
        )

    def test_frozen_scores_reproduce_reference(self):
        self.assertEqual(self.select([4.0, 3.0, 2.0, 1.0], (5, 5, 5, 5))[0], [0, 1, 2])

    def test_no_candidate_and_small_pool_do_not_invent_fragments(self):
        for n in range(4):
            ids = [str(i) for i in range(n)]
            chosen, r = choose(ids, [0.0] * n, [1.0] * n, token_receipt)
            self.assertEqual(chosen, list(range(n)))
            self.assertEqual(r["compiled_alternatives"], 1)

    def test_pool_beyond_top_four_cannot_enter_selection(self):
        chosen, _ = choose(
            [str(i) for i in range(6)],
            [6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            [0.0, 1.0, 2.0, 3.0, 999.0, 999.0],
            lambda p: token_receipt(p, (1,) * 6),
        )
        self.assertEqual(chosen, [1, 2, 3])

    def test_baseline_overflow_fails_without_truncation(self):
        with self.assertRaisesRegex(ValueError, "reference prompt"):
            self.select([4.0, 3.0, 2.0, 1.0], (2000,) * 4)

    def test_oversized_alternative_is_retained_not_selected(self):
        chosen, r = self.select([0.0, 1.0, 2.0, 99.0], (1, 1, 1, 5000))
        self.assertEqual(chosen, [0, 1, 2])
        self.assertEqual(
            sum(x["input_ids_digest"] is None for x in r["alternatives"]), 3
        )

    def test_invalid_scores_ids_and_token_measurements_fail_closed(self):
        for scores in ([0.0, 1.0, float("nan"), 2.0], [True, 1, 2, 3], [1, 2]):
            with self.assertRaises(ValueError):
                self.select(scores)
        for ids in (["a", "a"], ["a", None]):
            with self.assertRaises(ValueError):
                choose(ids, [2, 1], [2, 1], token_receipt)
        for measured in (
            dict(input_tokens=True, input_ids_digest="0" * 64),
            dict(input_tokens=100, input_ids_digest=None),
        ):
            with self.assertRaises(ValueError):
                choose(["a"], [1], [1], lambda _: measured)

    def test_receipt_drift_or_silent_evidence_omission_rejects(self):
        _, detail = self.select([4.0, 3.0, 2.0, 1.0])
        receipt = dict(
            input_tokens=detail["selected_input_tokens"],
            input_ids_digest=detail["selected_input_ids_digest"],
            token_limit=4096,
            omitted_evidence_bytes=0,
            delivered_evidence=[1, 2, 3],
        )
        verify_receipt(detail, receipt)
        for changes in (
            dict(input_tokens=131),
            dict(input_ids_digest="0" * 64),
            dict(omitted_evidence_bytes=1),
            dict(delivered_evidence=[1, 2]),
        ):
            with self.assertRaises(ValueError):
                verify_receipt(detail, receipt | changes)
        row = dict(
            query_id="q",
            arm="frozen",
            status="succeeded",
            evidence_selection=detail,
            receipt=receipt,
        )
        self.assertEqual(summarize([row])["verified_evidence_answers"], 1)
        with self.assertRaises(ValueError):
            summarize(
                [
                    row,
                    row
                    | dict(
                        arm="shared",
                        evidence_selection=detail | dict(baseline_input_tokens=150),
                    ),
                ]
            )


if __name__ == "__main__":
    unittest.main()
