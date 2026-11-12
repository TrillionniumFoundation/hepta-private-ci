import unittest
from hashlib import sha256
from itertools import permutations
from study import ContractError, Eligibility, Feedback, time_aligned_credit, frozen_credit_from_prefix


def digest(s):
    return sha256(s.encode("utf-8")).hexdigest()


class CanonicalFeedbackOrderTests(unittest.TestCase):
    def setUp(self):
        self.actions = [
            Eligibility("a" + str(i), digest("s" + str(i)), i, (1.0,))
            for i in range(1, 4)
        ]
        self.feedback = [
            Feedback(digest("f" + str(i)), "a" + str(i), 4, (m,))
            for i, m in ((1, 1.0), (2, 1e-16), (3, -1.0))
        ]

    def run_credit(self, values):
        return time_aligned_credit(
            self.actions, values, arm="routed", cutoff_sequence=4,
            decay=1.0, max_lag=4, per_group_limit=1e-17,
            global_l1_limit=1e-17,
        )

    def test_same_digest_must_imply_same_numerical_delta(self):
        results = [self.run_credit(p) for p in permutations(self.feedback)]
        self.assertEqual(len({r.transcript_digest for r in results}), 1)
        self.assertEqual(len({r.causal_training_digest for r in results}), 1)
        self.assertEqual(len({r.deltas for r in results}), 1)

    def test_frozen_prefix_order_invariant(self):
        results = [
            frozen_credit_from_prefix(
                self.actions, p, arm="routed", cutoff_sequence=4,
                decay=1.0, max_lag=4, per_group_limit=1e-17,
                global_l1_limit=1e-17,
            ) for p in permutations(self.feedback)
        ]
        self.assertEqual(len({r.deltas for r in results}), 1)

    def test_bad_receipt_still_rejected(self):
        broken = list(self.feedback)
        broken[1] = Feedback(
            "invalid", broken[1].action_id, 4, broken[1].modulator
        )
        with self.assertRaises(ContractError):
            self.run_credit(broken)


if __name__ == "__main__":
    unittest.main()

