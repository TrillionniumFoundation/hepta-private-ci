"""Deterministic SPECIFICATION tests, not production clock/issuer verification.

All policy values and tokens below are fixtures. The model assumes the issuer
samples between challenge send and response receipt, and that the independently
qualified monotonic source satisfies the explicit error/rate contract.
"""
from dataclasses import dataclass
from fractions import Fraction
from itertools import product
import unittest

MAX = 2**64 - 1


@dataclass(frozen=True)
class Policy:
    minimum_ticks_per_ms: Fraction
    maximum_ticks_per_ms: Fraction
    measurement_error_ticks: Fraction
    issuer_uncertainty_ms: int
    maximum_roundtrip_ms: int
    maximum_anchor_age_ms: int

    def validate(self):
        if not (0 < self.minimum_ticks_per_ms <= self.maximum_ticks_per_ms):
            raise ValueError('invalid rate bounds')
        if self.measurement_error_ticks < 0 or self.issuer_uncertainty_ms < 0:
            raise ValueError('negative error bound')
        if self.maximum_roundtrip_ms <= 0 or self.maximum_anchor_age_ms <= 0:
            raise ValueError('missing positive duration policy')


def floor(value):
    return value.numerator // value.denominator


def ceil(value):
    return -((-value.numerator) // value.denominator)


def elapsed(start, end, policy):
    policy.validate()
    if end < start:
        raise ValueError('monotonic rollback')
    delta = end - start
    error = 2 * policy.measurement_error_ticks
    # Zero is a physical elapsed-time lower bound, not overflow saturation.
    lower = floor(max(Fraction(0), delta - error) / policy.maximum_ticks_per_ms)
    upper = ceil((delta + error) / policy.minimum_ticks_per_ms)
    return lower, upper


def bounds(sample, m0, m1, now, policy, committed_expiry_floor=0):
    if now < m1 or m1 < m0:
        raise ValueError('rollback or reordered samples')
    if elapsed(m0, m1, policy)[1] > policy.maximum_roundtrip_ms:
        raise ValueError('roundtrip bound exceeded')
    # Age starts at challenge issuance, not response arrival or acceptance.
    if elapsed(m0, now, policy)[1] > policy.maximum_anchor_age_ms:
        raise ValueError('anchor stale')
    earliest = sample - policy.issuer_uncertainty_ms + elapsed(m1, now, policy)[0]
    latest = sample + policy.issuer_uncertainty_ms + elapsed(m0, now, policy)[1]
    if not (0 <= earliest <= latest <= MAX and 0 <= committed_expiry_floor <= MAX):
        raise ValueError('invalid arithmetic range')
    return earliest, max(latest, committed_expiry_floor)


def admits(interval, not_before, expires):
    earliest, latest = interval
    return earliest >= not_before and latest < expires


class ProjectionState:
    """Only the publication-token/floor distinction; no persistence engine."""
    def __init__(self, durable_floor):
        self.durable_floor = durable_floor
        self.volatile_floor = durable_floor
        self.generation = 0
        self.usable = False
        self.unknown = False
        self.pending = False

    def begin_publication(self):
        if self.unknown:
            raise ValueError('owner reconciliation required')
        if self.pending:
            raise ValueError('publication already pending')
        self.generation += 1
        self.usable = False
        self.pending = True
        return self.generation

    def accept(self, token, committed_floor):
        if token != self.generation or self.unknown or not self.pending:
            return False
        self.durable_floor = max(self.durable_floor, committed_floor)
        self.volatile_floor = max(self.volatile_floor, self.durable_floor)
        self.usable = True
        self.pending = False
        return True

    def invalidate(self, token, unknown=False):
        if token != self.generation or not self.pending:
            return False
        self.usable = False
        self.unknown = unknown
        self.pending = False
        return True

    def observe(self, projected_upper):
        if not self.usable:
            raise ValueError('not usable')
        self.volatile_floor = max(self.volatile_floor, projected_upper)
        return self.volatile_floor

    def commit_effective_floor(self):
        if not self.usable:
            raise ValueError('not usable')
        self.durable_floor = self.volatile_floor

    def restart(self):
        self.generation += 1
        self.volatile_floor = self.durable_floor
        self.usable = False
        # Publication includes attempted durable work; restart cannot reconcile it.
        self.unknown = self.unknown or self.pending
        self.pending = False


class IntervalContractTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy(Fraction(1), Fraction(1), Fraction(0), 2, 20, 40)

    def test_true_time_containment_under_explicit_bounds(self):
        checked = 0
        for rtt, after, fraction, uncertainty, signed_error, error, rate, e0, e1, en in product(
            (2, 8, 20), (0, 1, 11), (Fraction(0), Fraction(1, 2), Fraction(1)),
            (0, 2), (-1, 0, 1), (0, 1), (Fraction(3, 4), Fraction(1), Fraction(5, 4)),
            (-1, 0, 1), (-1, 0, 1), (-1, 0, 1),
        ):
            m0 = Fraction(e0 * error)
            m1 = rate * rtt + e1 * error
            current = rate * (rtt + after) + en * error
            if current < m1 or m1 < m0:
                continue
            sample = Fraction(1_000_000) + fraction * rtt + signed_error * uncertainty
            policy = Policy(Fraction(3, 4), Fraction(5, 4), Fraction(error), uncertainty, 1000, 1000)
            low, high = bounds(sample, m0, m1, current, policy)
            truth = 1_000_000 + rtt + after
            self.assertLessEqual(low, truth)
            self.assertGreaterEqual(high, truth)
            checked += 1
        self.assertGreater(checked, 20000)

    def test_outward_rounding(self):
        p = Policy(Fraction(2), Fraction(3), Fraction(0), 0, 20, 40)
        self.assertEqual(elapsed(Fraction(0), Fraction(5), p), (1, 3))

    def test_upper_bound_cannot_satisfy_future_not_before(self):
        interval = (990, 1010)
        self.assertTrue(1010 >= 1005)  # Unsafe scalar-upper-bound conversion.
        self.assertFalse(admits(interval, 1005, 2000))

    def test_fresh_sample_does_not_extend_expired_lease(self):
        interval = bounds(1000, Fraction(0), Fraction(2), Fraction(8), self.policy)
        self.assertFalse(admits(interval, 900, 1007))

    def test_committed_expiry_floor_does_not_raise_earliest(self):
        interval = bounds(1000, Fraction(0), Fraction(2), Fraction(3), self.policy, 1100)
        self.assertEqual(interval[1], 1100)
        self.assertLess(interval[0], 1010)
        self.assertFalse(admits(interval, 1010, 2000))

    def test_roundtrip_uses_upper_elapsed(self):
        p = Policy(Fraction(1, 2), Fraction(2), Fraction(0), 0, 15, 100)
        with self.assertRaisesRegex(ValueError, 'roundtrip'):
            bounds(1000, Fraction(0), Fraction(10), Fraction(10), p)

    def test_age_includes_roundtrip_from_m0(self):
        p = Policy(Fraction(1), Fraction(1), Fraction(0), 0, 20, 10)
        with self.assertRaisesRegex(ValueError, 'stale'):
            bounds(1000, Fraction(0), Fraction(8), Fraction(11), p)

    def test_age_uses_upper_elapsed(self):
        p = Policy(Fraction(1, 2), Fraction(2), Fraction(0), 0, 20, 15)
        with self.assertRaisesRegex(ValueError, 'stale'):
            bounds(1000, Fraction(0), Fraction(2), Fraction(10), p)

    def test_rollback_and_invalid_rates_fail_closed(self):
        with self.assertRaises(ValueError):
            bounds(1000, Fraction(0), Fraction(2), Fraction(1), self.policy)
        with self.assertRaises(ValueError):
            elapsed(Fraction(0), Fraction(1), Policy(Fraction(0), Fraction(1), Fraction(0), 0, 1, 1))

    def test_overflow_and_underflow_are_unavailable(self):
        for sample in (1, MAX):
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                bounds(sample, Fraction(0), Fraction(1), Fraction(1), self.policy)

    def test_stale_completion_cannot_clear_newer_anchor(self):
        state = ProjectionState(100)
        old = state.begin_publication()
        state.invalidate(old)
        newer = state.begin_publication()
        self.assertTrue(state.accept(newer, 120))
        self.assertFalse(state.invalidate(old, unknown=True))
        self.assertTrue(state.usable)
        self.assertEqual(state.durable_floor, 120)

    def test_publications_are_serialized_separately_from_network_challenges(self):
        state = ProjectionState(100)
        token = state.begin_publication()
        with self.assertRaisesRegex(ValueError, 'already pending'):
            state.begin_publication()
        self.assertTrue(state.invalidate(token, unknown=True))
        self.assertFalse(state.usable)
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            state.begin_publication()

    def test_restart_during_publication_requires_reconciliation(self):
        state = ProjectionState(100)
        token = state.begin_publication()
        state.restart()
        self.assertFalse(state.accept(token, 120))
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            state.begin_publication()
        self.assertEqual(state.durable_floor, 100)

    def test_duplicate_completion_neither_refreshes_nor_invalidates_anchor(self):
        state = ProjectionState(100)
        token = state.begin_publication()
        self.assertTrue(state.accept(token, 120))
        self.assertFalse(state.accept(token, 150))
        self.assertFalse(state.invalidate(token))
        self.assertEqual(state.durable_floor, 120)
        self.assertTrue(state.usable)

    def test_unknown_publication_blocks_new_use(self):
        state = ProjectionState(100)
        token = state.begin_publication()
        state.invalidate(token, unknown=True)
        with self.assertRaises(ValueError):
            state.begin_publication()
        self.assertFalse(state.accept(token, 120))
        state.restart()
        with self.assertRaises(ValueError):
            state.begin_publication()

    def test_restart_does_not_claim_volatile_reads_are_durable(self):
        state = ProjectionState(100)
        token = state.begin_publication()
        state.accept(token, 110)
        state.observe(150)
        self.assertEqual(state.durable_floor, 110)
        state.restart()
        self.assertEqual(state.volatile_floor, 110)
        with self.assertRaises(ValueError):
            state.observe(151)
        state.accept(state.begin_publication(), 120)
        self.assertEqual(state.observe(125), 125)

    def test_successful_transition_persists_floor_but_rejection_does_not(self):
        state = ProjectionState(100)
        state.accept(state.begin_publication(), 110)
        state.observe(150)
        # A rejected mutation does not call commit_effective_floor.
        self.assertEqual(state.durable_floor, 110)
        state.commit_effective_floor()
        state.restart()
        self.assertEqual(state.durable_floor, 150)
        self.assertFalse(state.usable)


if __name__ == '__main__':
    unittest.main(verbosity=2)
