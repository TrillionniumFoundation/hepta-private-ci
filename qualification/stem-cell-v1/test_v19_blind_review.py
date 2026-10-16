"""Bounded private review contract tests; do not expose source/text in CI."""
import unittest
from v19_blind_review_tickets import prepare
class BlindedReviewIntake(unittest.TestCase):
    def test_reject_short_seed(self):
        with self.assertRaises(ValueError):prepare({}, {}, {}, {}, {}, {}, {}, b'short')
    def test_reject_fake_unsealed_plan(self):
        with self.assertRaises(ValueError):prepare({}, {}, {}, {}, {}, {}, {}, b'z'*32)
    def test_require_exact_readers(self):
        with self.assertRaises(ValueError):prepare({'cases':[{}]*32}, {}, {}, {'plan_sha256':'fake'}, {}, {}, {}, b'z'*32)
    def test_reject_empty_secret(self):
        with self.assertRaises(ValueError):prepare({}, {}, {}, {}, {}, {}, {}, b'')
if __name__=='__main__':unittest.main()
