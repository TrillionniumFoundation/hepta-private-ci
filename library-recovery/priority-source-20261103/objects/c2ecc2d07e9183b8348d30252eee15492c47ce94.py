#!/usr/bin/env python3
"""Deterministic design checks, NOT execution of AuthBus Rust or a protected clock.

Threshold values below are explicit fixture values only. Production values and
protected-clock provisioning remain operator choices; no fallback is modeled.
"""
from dataclasses import dataclass
import unittest

MAX_U64 = (1 << 64) - 1


@dataclass(frozen=True)
class FreshnessPolicy:
    max_age_ms: int
    max_future_skew_ms: int

    def __post_init__(self):
        if not 0 < self.max_age_ms <= MAX_U64 or not 0 <= self.max_future_skew_ms <= MAX_U64:
            raise ValueError('invalid explicitly supplied policy')

    def accepts(self, signed_time_ms, protected_now_ms):
        if protected_now_ms is None:
            return False
        if not 0 < signed_time_ms <= MAX_U64 or not 0 < protected_now_ms <= MAX_U64:
            return False
        if signed_time_ms > protected_now_ms:
            return signed_time_ms - protected_now_ms <= self.max_future_skew_ms
        return protected_now_ms - signed_time_ms < self.max_age_ms


def authority_window_accepts(policy, signed_time_ms, protected_now_ms, retained_floor_ms,
                             not_before_ms, expires_at_ms):
    if not policy.accepts(signed_time_ms, protected_now_ms):
        return False
    if not 0 <= retained_floor_ms <= signed_time_ms <= MAX_U64:
        return False
    if not 0 < not_before_ms < expires_at_ms <= MAX_U64:
        return False
    # An upper effective time protects expiration but must not be used alone
    # to satisfy not-before when a permitted signed sample is slightly ahead.
    lower_now = min(protected_now_ms, signed_time_ms)
    upper_now = max(protected_now_ms, signed_time_ms, retained_floor_ms)
    return lower_now >= not_before_ms and upper_now < expires_at_ms


class FreshnessContractTests(unittest.TestCase):
    def setUp(self):
        self.policy = FreshnessPolicy(max_age_ms=50, max_future_skew_ms=3)

    def test_signature_and_monotonic_revision_alone_do_not_prove_freshness(self):
        # This predicate is the numeric part of current advance_time. Equality
        # is accepted, irrespective of time outside the signed observation.
        previous = (1000, 7, 'same-source-digest')
        sample = previous
        current_numeric_gate = sample[0] >= previous[0] and sample[1] >= previous[1]
        self.assertTrue(current_numeric_gate)
        self.assertFalse(self.policy.accepts(sample[0], 1100))

    def test_age_boundary_is_exclusive_and_operator_supplied(self):
        self.assertTrue(self.policy.accepts(1000, 1049))
        self.assertFalse(self.policy.accepts(1000, 1050))
        self.assertTrue(FreshnessPolicy(100, 3).accepts(1000, 1050))

    def test_future_skew_is_bounded_without_saturating_arithmetic(self):
        self.assertTrue(self.policy.accepts(1003, 1000))
        self.assertFalse(self.policy.accepts(1004, 1000))
        self.assertFalse(FreshnessPolicy(50, 0).accepts(1001, 1000))
        self.assertTrue(self.policy.accepts(MAX_U64, MAX_U64))
        self.assertFalse(self.policy.accepts(1, MAX_U64))

    def test_repeated_verification_does_not_refresh_signed_instant(self):
        for verification_attempt in range(100):
            self.assertFalse(self.policy.accepts(1000, 1100 + verification_attempt))

    def test_consumer_rechecks_after_gate_queue_and_checkpoint_await(self):
        signed_time = 1000
        self.assertTrue(self.policy.accepts(signed_time, 1001))
        # Reusing the earlier boolean would pass. Rechecking at the consuming
        # mutation must use the protected owner's new observation instead.
        self.assertFalse(self.policy.accepts(signed_time, 1100))

    def test_restart_never_reconstructs_fresh_authority_from_persisted_floor(self):
        historical_floor = 1000
        protected_now_after_restart = 2000
        self.assertFalse(self.policy.accepts(historical_floor, protected_now_after_restart))
        # The retained historical observation remains readable; freshness
        # rejection does not rewrite, delete or lower it.
        self.assertEqual(historical_floor, 1000)

    def test_missing_failed_or_invalid_clock_has_no_system_clock_fallback(self):
        for unavailable in [None, 0, -1, MAX_U64 + 1]:
            self.assertFalse(self.policy.accepts(1000, unavailable))

    def test_fresh_sample_does_not_extend_an_already_expired_lease(self):
        self.assertTrue(self.policy.accepts(1000, 1030))
        self.assertFalse(authority_window_accepts(self.policy, 1000, 1030, 999, 900, 1025))

    def test_expiration_at_protected_clock_boundary_is_denied(self):
        self.assertTrue(self.policy.accepts(1000, 1025))
        self.assertFalse(authority_window_accepts(self.policy, 1000, 1025, 1000, 900, 1025))
        self.assertTrue(authority_window_accepts(self.policy, 1000, 1024, 1000, 900, 1025))

    def test_permitted_future_skew_cannot_activate_not_before_early(self):
        self.assertTrue(self.policy.accepts(1003, 1000))
        self.assertFalse(authority_window_accepts(self.policy, 1003, 1000, 999, 1002, 2000))
        self.assertTrue(authority_window_accepts(self.policy, 1003, 1002, 999, 1002, 2000))

    def test_freshness_does_not_override_retained_floor_regression(self):
        self.assertTrue(self.policy.accepts(1000, 1030))
        self.assertFalse(authority_window_accepts(self.policy, 1000, 1030, 1100, 900, 2000))

    def test_no_default_policy_is_invented(self):
        for maximum_age, skew in [(0, 0), (-1, 0), (50, -1), (MAX_U64 + 1, 0)]:
            with self.assertRaises(ValueError): FreshnessPolicy(maximum_age, skew)


if __name__ == '__main__':
    unittest.main(verbosity=2)
