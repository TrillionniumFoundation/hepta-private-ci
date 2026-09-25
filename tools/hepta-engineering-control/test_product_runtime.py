from dataclasses import replace
from pathlib import Path
import subprocess
import tempfile
import unittest

from control_engineering_v2 import (
    EngineeringCapacity,
    EngineeringControlProduct,
    EngineeringWorkPackage,
    HmacTrustStore,
    ReviewCapacity,
    WorkerProfile,
    WorkerRegistrationReceipt,
    WorkEnvelope,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class EngineeringControlProductTests(unittest.TestCase):
    def signed_registration(self, trust, now):
        value = WorkerRegistrationReceipt(
            "worker-a",
            "worker-key",
            ("engineering",),
            1,
            ("src",),
            "engineering_worker_identity",
            "identity-key",
            now,
            now + 10_000,
        )
        return replace(
            value,
            signature=trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_product_startup_reconciles_stale_claim_and_allows_bounded_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            database = Path(temporary) / "engineering.sqlite3"
            now = 1_000_000
            envelope = WorkEnvelope(
                "env-recovery",
                "a" * 40,
                "b" * 40,
                "c" * 64,
                "d" * 64,
                "developer-productivity",
                ("src",),
                tuple(sorted(DENIED_AUTHORITIES)),
                1,
                now + 10_000,
            )
            trust = HmacTrustStore(
                {
                    ("engineering_worker_identity", "identity-key"): b"identity",
                    ("worker-a", "worker-key"): b"worker",
                }
            )
            with EngineeringControlProduct(
                database,
                root,
                expected_repository="TrillionniumFoundation/hepta-private-ci",
                trust_store=trust,
            ) as product:
                product.store.issue_work_envelope(envelope, now_ns=now)
                plan = product.plan_work(
                    envelope,
                    (
                        EngineeringWorkPackage(
                            0,
                            "package-a",
                            (),
                            ("src/a",),
                            required_skills=("engineering",),
                            capacity_units=1,
                        ),
                    ),
                    (WorkerProfile("worker-a", ("engineering",), 1, ("src",)),),
                    (),
                    EngineeringCapacity(1, ()),
                    generation_id="generation-a",
                    now_ns=now,
                )
                product.register_worker(
                    self.signed_registration(trust, now),
                    now_ns=now,
                )
                lease = product.acquire_lease(
                    "lease-a",
                    envelope.envelope_id,
                    "worker-a",
                    ("src/a",),
                    authority_epoch=1,
                    expires_unix_ns=now + 5_000,
                    now_ns=now + 1,
                )
                with self.assertRaisesRegex(
                    ValueError, "product_startup_reconciliation_required"
                ):
                    product.claim(
                        plan.generation_id,
                        "package-a",
                        "worker-a",
                        lease.lease_id,
                        heartbeat_ttl_ns=100,
                        now_ns=now + 2,
                    )
                initial = product.startup_reconcile(now_ns=now + 2)
                self.assertEqual(initial.active_claims, ())
                self.assertEqual(initial.active_capacity_reservations, 0)
                claim = product.claim(
                    plan.generation_id,
                    "package-a",
                    "worker-a",
                    lease.lease_id,
                    heartbeat_ttl_ns=100,
                    now_ns=now + 2,
                )
                self.assertEqual(product.worker_capacity("worker-a").reserved_units, 1)

            with EngineeringControlProduct(
                database,
                root,
                expected_repository="TrillionniumFoundation/hepta-private-ci",
                trust_store=trust,
            ) as reopened:
                report = reopened.startup_reconcile(now_ns=now + 103)
                self.assertEqual(report.heartbeat_expired_claims, (claim.claim_id,))
                self.assertEqual(report.active_capacity_reservations, 0)
                self.assertEqual(reopened.claim_state(claim.claim_id).state, "retryable")
                retried = reopened.claim(
                    plan.generation_id,
                    "package-a",
                    "worker-a",
                    lease.lease_id,
                    heartbeat_ttl_ns=100,
                    now_ns=now + 104,
                )
                self.assertEqual(retried.attempt, 2)
                self.assertEqual(reopened.worker_capacity("worker-a").reserved_units, 1)
                stable = reopened.startup_reconcile(now_ns=now + 105)
                self.assertEqual(stable.heartbeat_expired_claims, ())
                self.assertEqual(stable.active_claims, (retried.claim_id,))

    def test_named_product_owner_composes_repository_store_and_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            git(root, "init")
            git(root, "config", "user.email", "test@example.invalid")
            git(root, "config", "user.name", "Engineering Product")
            git(root, "remote", "add", "origin", "https://github.com/TrillionniumFoundation/hepta-private-ci.git")
            (root / "src").mkdir()
            (root / "src" / "a.txt").write_text("a\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-m", "base")
            head = git(root, "rev-parse", "HEAD")
            tree = git(root, "rev-parse", "HEAD^{tree}")
            now = 1_000_000
            envelope = WorkEnvelope(
                "env",
                head,
                tree,
                "c" * 64,
                "d" * 64,
                "developer-productivity",
                ("src",),
                tuple(sorted(DENIED_AUTHORITIES)),
                1,
                now + 1_000_000,
            )
            database = Path(temporary) / "engineering.sqlite3"
            with EngineeringControlProduct(
                database,
                root,
                expected_repository="TrillionniumFoundation/hepta-private-ci",
                trust_store=HmacTrustStore({}),
            ) as product:
                product.admit_repository_envelope(envelope, now_ns=now)
                plan = product.plan_work(
                    envelope,
                    (
                        EngineeringWorkPackage(
                            0,
                            "package-a",
                            (),
                            ("src/a.txt",),
                            required_skills=("engineering",),
                            review_roles=("architecture",),
                        ),
                    ),
                    (WorkerProfile("worker-a", ("engineering",), 1, ("src",)),),
                    (),
                    EngineeringCapacity(1, (ReviewCapacity("architecture", 1),)),
                    generation_id="generation-a",
                    now_ns=now,
                )
                self.assertEqual(plan.assignments[0].worker_id, "worker-a")
                self.assertEqual(
                    product.store.connection.execute("PRAGMA user_version").fetchone()[0],
                    10,
                )
            self.assertTrue(database.exists())


if __name__ == "__main__":
    unittest.main()
