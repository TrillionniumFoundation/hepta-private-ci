import unittest
from unittest.mock import patch

from control_engineering_v2 import CandidateEnvelope, EngineeringError
from control_engineering_v2.facade import (
    execute_candidate_bundle_sandbox,
    execute_candidate_sandbox,
)


class _Lease:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


class _Limiter:
    def __init__(self):
        self.acquisitions = 0

    def acquire(self, *, deadline_monotonic=None):
        self.acquisitions += 1
        return _Lease()


class ControlledSandboxFacadeTests(unittest.TestCase):
    def envelope(self, *, strong=True):
        return CandidateEnvelope(
            "env",
            "a" * 40,
            ("src",),
            require_network_isolation=strong,
            wall_time_seconds=30,
        )

    def test_strong_candidate_path_enforces_host_slot_and_two_infra_retries(self):
        limiter = _Limiter()
        with patch(
            "control_engineering_v2.facade.sandbox_candidate",
            side_effect=EngineeringError("network_isolation_unavailable"),
        ) as operation:
            with self.assertRaisesRegex(
                EngineeringError, "network_isolation_unavailable"
            ):
                execute_candidate_sandbox(
                    "/unused",
                    self.envelope(strong=True),
                    object(),
                    (("true",),),
                    limiter=limiter,
                )
        self.assertEqual(operation.call_count, 3)
        self.assertEqual(limiter.acquisitions, 3)

    def test_semantic_failure_never_retries(self):
        limiter = _Limiter()
        with patch(
            "control_engineering_v2.facade.sandbox_candidate",
            side_effect=EngineeringError("protected_oracle_path"),
        ) as operation:
            with self.assertRaisesRegex(EngineeringError, "protected_oracle_path"):
                execute_candidate_sandbox(
                    "/unused",
                    self.envelope(strong=True),
                    object(),
                    (("true",),),
                    limiter=limiter,
                )
        self.assertEqual(operation.call_count, 1)
        self.assertEqual(limiter.acquisitions, 1)

    def test_portable_fixture_path_cannot_invent_host_control(self):
        limiter = _Limiter()
        sentinel = (object(), object())
        with patch(
            "control_engineering_v2.facade.sandbox_candidate",
            return_value=sentinel,
        ) as operation:
            result = execute_candidate_sandbox(
                "/unused",
                self.envelope(strong=False),
                object(),
                (("true",),),
                limiter=limiter,
            )
        self.assertIs(result, sentinel)
        self.assertEqual(operation.call_count, 1)
        self.assertEqual(limiter.acquisitions, 0)

    def test_bundle_uses_the_same_controlled_execution_path(self):
        limiter = _Limiter()
        sentinel = (object(), object())
        with patch(
            "control_engineering_v2.facade.sandbox_candidate_bundle",
            return_value=sentinel,
        ) as operation:
            result = execute_candidate_bundle_sandbox(
                "/unused",
                self.envelope(strong=True),
                object(),
                (("true",),),
                limiter=limiter,
            )
        self.assertIs(result, sentinel)
        self.assertEqual(operation.call_count, 1)
        self.assertEqual(limiter.acquisitions, 1)

    def test_check_shape_is_preserved_for_low_level_validation(self):
        limiter = _Limiter()
        observed = {}

        def capture(_repository, _envelope, _candidate, checks):
            observed["checks"] = checks
            raise EngineeringError("invalid_check")

        with patch("control_engineering_v2.facade.sandbox_candidate", side_effect=capture):
            with self.assertRaisesRegex(EngineeringError, "invalid_check"):
                execute_candidate_sandbox(
                    "/unused",
                    self.envelope(strong=True),
                    object(),
                    ("not-an-argv-vector",),
                    limiter=limiter,
                    maximum_retries=0,
                )
        self.assertEqual(observed["checks"], ("not-an-argv-vector",))


if __name__ == "__main__":
    unittest.main()
