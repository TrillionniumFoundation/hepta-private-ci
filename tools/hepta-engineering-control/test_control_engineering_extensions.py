from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    AuditCheckpoint,
    ClockSkewPolicy,
    EngineeringStore,
    FixedClock,
    HmacTrustStore,
    StoreCapacityPolicy,
    WorkerRegistrationReceipt,
    WorkerRegistrationRenewalReceipt,
    create_audit_checkpoint,
    evaluate_store_capacity,
    register_worker,
    renew_worker_registration,
    validate_signed_window,
    verify_audit_suffix,
)


class TimePolicyTests(unittest.TestCase):
    def test_future_skew_and_owner_window_are_explicit(self):
        validate_signed_window(105, 200, 100, policy=ClockSkewPolicy(5))
        with self.assertRaisesRegex(ValueError, "signed_observation_from_future"):
            validate_signed_window(106, 200, 100, policy=ClockSkewPolicy(5))
        with self.assertRaisesRegex(ValueError, "signed_observation_outlives_owner"):
            validate_signed_window(
                100, 201, 100, owner_expires_unix_ns=200
            )
        self.assertEqual(FixedClock(11, 7).wall_time_ns(), 11)


class RegistrationRenewalTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000
        self.trust = HmacTrustStore(
            {
                ("engineering_worker_identity", "authority-a"): b"a",
                ("engineering_worker_identity", "authority-b"): b"b",
            }
        )

    def initial(self):
        value = WorkerRegistrationReceipt(
            "worker-a",
            "worker-key-a",
            ("python",),
            2,
            ("src",),
            "engineering_worker_identity",
            "authority-a",
            self.now,
            self.now + 1000,
        )
        return replace(
            value,
            signature=self.trust.sign(
                value, value.issuer, value.signing_identity
            ),
        )

    def renewal(
        self,
        digest,
        revision=1,
        identity="worker-key-b",
        expires=None,
    ):
        value = WorkerRegistrationRenewalReceipt(
            "worker-a",
            revision,
            digest,
            identity,
            ("python",),
            3,
            ("src",),
            "engineering_worker_identity",
            "authority-b",
            self.now + 1,
            self.now + 2000 if expires is None else expires,
        )
        return replace(
            value,
            signature=self.trust.sign(
                value, value.issuer, value.signing_identity
            ),
        )

    def test_rotation_is_revision_bound_and_replay_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "owner.sqlite3") as store:
                predecessor = register_worker(
                    store, self.initial(), self.trust, now_ns=self.now
                )
                receipt = self.renewal(predecessor)
                result = renew_worker_registration(
                    store, receipt, self.trust, now_ns=self.now + 1
                )
                self.assertNotEqual(result, predecessor)
                self.assertEqual(
                    renew_worker_registration(
                        store, receipt, self.trust, now_ns=self.now + 1
                    ),
                    result,
                )
                row = store.connection.execute(
                    "SELECT revision,worker_signing_identity "
                    "FROM worker_registrations"
                ).fetchone()
                self.assertEqual(
                    (int(row[0]), str(row[1])), (2, "worker-key-b")
                )

    def test_stale_predecessor_and_expiry_regression_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "owner.sqlite3") as store:
                predecessor = register_worker(
                    store, self.initial(), self.trust, now_ns=self.now
                )
                with self.assertRaisesRegex(ValueError, "predecessor_mismatch"):
                    renew_worker_registration(
                        store,
                        self.renewal("f" * 64),
                        self.trust,
                        now_ns=self.now + 1,
                    )
                with self.assertRaisesRegex(ValueError, "expiry_regression"):
                    renew_worker_registration(
                        store,
                        self.renewal(
                            predecessor,
                            identity="worker-key-a",
                            expires=self.now + 999,
                        ),
                        self.trust,
                        now_ns=self.now + 1,
                    )


class CheckpointAndCapacityTests(unittest.TestCase):
    def test_suffix_verification_and_capacity_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "owner.sqlite3") as store:
                checkpoint = create_audit_checkpoint(store, now_ns=1)
                self.assertIsInstance(checkpoint, AuditCheckpoint)
                suffix = verify_audit_suffix(store, checkpoint)
                self.assertEqual(suffix["verifiedSuffixEvents"], 0)
                capacity = evaluate_store_capacity(
                    store, StoreCapacityPolicy()
                )
                self.assertEqual(capacity["hardFailures"], ())
                self.assertFalse(capacity["productionAccepted"])


if __name__ == "__main__":
    unittest.main()
