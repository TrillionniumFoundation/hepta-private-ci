from dataclasses import replace
import unittest

from control_engineering_v2.clock import ClockPolicy, FixedClock
from control_engineering_v2.evidence import HmacTrustStore
from control_engineering_v2.operator_acceptance import (
    OperatorAcceptanceReceipt,
    verify_operator_acceptance,
)


class OperatorAcceptanceTests(unittest.TestCase):
    def test_acceptance_requires_external_signature_and_complete_observations(self):
        now = 1_000_000
        trust = HmacTrustStore({("control_engineering_operator", "operator-key"): b"key"})
        value = OperatorAcceptanceReceipt(
            "target-a",
            "a" * 40,
            "b" * 40,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            "f" * 64,
            "1" * 64,
            "2" * 64,
            True,
            True,
            "control_engineering_operator",
            "operator-key",
            now,
            now + 1_000_000,
        )
        value = replace(
            value,
            signature=trust.sign(value, value.issuer, value.signing_identity),
        )
        digest = verify_operator_acceptance(
            value,
            trust,
            ClockPolicy(10, 10_000, 2_000_000),
            expected_target_id="target-a",
            expected_source_commit="a" * 40,
            expected_source_tree="b" * 40,
            expected_provider_bundle_digest="c" * 64,
            expected_recovery_rehearsal_digest="d" * 64,
            clock=FixedClock(now),
        )
        self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
