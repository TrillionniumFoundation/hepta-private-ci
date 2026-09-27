from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2.clock import ClockPolicy, FixedClock
from control_engineering_v2.control_plane import EngineeringStore
from control_engineering_v2.evidence import HmacTrustStore
from control_engineering_v2.worker_lifecycle import (
    WorkerRegistrationReceipt,
    register_worker,
)
from control_engineering_v2.worker_registration_governance import (
    WorkerKeyRotationReceipt,
    WorkerRegistrationRenewalReceipt,
    renew_worker_registration,
    rotate_worker_signing_identity,
)


class WorkerRegistrationGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000
        self.clock = FixedClock(self.now)
        self.policy = ClockPolicy(10, 1_000, 10_000_000)
        self.trust = HmacTrustStore(
            {("engineering_worker_identity", "authority-key"): b"authority"}
        )

    def _sign(self, value):
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_renewal_and_idle_key_rotation_are_revision_bound_and_replay_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                initial = WorkerRegistrationReceipt(
                    "worker-a",
                    "worker-key-v1",
                    ("python",),
                    2,
                    ("src",),
                    "engineering_worker_identity",
                    "authority-key",
                    self.now,
                    self.now + 2_000_000,
                )
                register_worker(
                    store,
                    self._sign(initial),
                    self.trust,
                    now_ns=self.now,
                )
                current = store.connection.execute(
                    "SELECT profile_digest FROM worker_registrations WHERE worker_id='worker-a'"
                ).fetchone()
                renewal = WorkerRegistrationRenewalReceipt(
                    "worker-a",
                    "worker-key-v1",
                    1,
                    str(current[0]),
                    ("python", "review"),
                    3,
                    ("src",),
                    "engineering_worker_identity",
                    "authority-key",
                    self.now,
                    self.now + 3_000_000,
                )
                renewed = renew_worker_registration(
                    store,
                    self._sign(renewal),
                    self.trust,
                    self.policy,
                    clock=self.clock,
                )
                self.assertEqual((renewed.revision, renewed.capacity_units), (2, 3))
                self.assertEqual(
                    renew_worker_registration(
                        store,
                        self._sign(renewal),
                        self.trust,
                        self.policy,
                        clock=self.clock,
                    ),
                    renewed,
                )
                rotation = WorkerKeyRotationReceipt(
                    "worker-a",
                    2,
                    renewed.profile_digest,
                    "worker-key-v1",
                    "worker-key-v2",
                    "engineering_worker_identity",
                    "authority-key",
                    self.now,
                    self.now + 3_000_000,
                )
                rotated = rotate_worker_signing_identity(
                    store,
                    self._sign(rotation),
                    self.trust,
                    self.policy,
                    clock=self.clock,
                )
                self.assertEqual(rotated.revision, 3)
                self.assertEqual(rotated.worker_signing_identity, "worker-key-v2")


if __name__ == "__main__":
    unittest.main()
