from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from control_engineering_v2 import (
    EngineeringCapacity,
    EngineeringControlProduct,
    EngineeringWorkPackage,
    HmacTrustStore,
    WorkerHeartbeatReceipt,
    WorkerProfile,
    WorkerRegistrationReceipt,
    WorkerResultReceipt,
    WorkEnvelope,
)
from control_engineering_v2 import orchestration
from control_engineering_v2.control_plane import DENIED_AUTHORITIES, EngineeringError


class ProductClaimAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        for arguments in (
            ("init",), ("config", "user.name", "Test"),
            ("config", "user.email", "test@example.invalid"),
            ("remote", "add", "origin", "https://github.com/acme/repository.git"),
        ):
            self.git(*arguments)
        (self.root / "src").mkdir()
        (self.root / "src/base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "base")
        self.now = 1_000_000
        self.database = self.root.parent / "engineering.sqlite3"
        self.trust = HmacTrustStore({
            ("engineering_worker_identity", "identity-key"): b"identity",
            ("worker", "worker-key"): b"worker",
        })
        self.envelope = WorkEnvelope(
            "env", self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD^{tree}"),
            "c" * 64, "d" * 64, "developer-productivity", ("src",),
            tuple(sorted(DENIED_AUTHORITIES)), 8, self.now + 1_000_000,
        )
        self.profile = WorkerProfile("worker", ("rust", "python"), 4, ("src",))
        self.product = self.open_product(self.now)
        self.addCleanup(lambda: self.product.close())
        self.product.admit_repository_envelope(self.envelope, now_ns=self.now)
        registration = WorkerRegistrationReceipt(
            "worker", "worker-key", self.profile.skills, 4, ("src",),
            "engineering_worker_identity", "identity-key", self.now,
            self.now + 1_000_000,
        )
        registration = replace(
            registration,
            signature=self.trust.sign(registration, registration.issuer, registration.signing_identity),
        )
        self.product.register_worker(registration, now_ns=self.now)

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments], check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def open_product(self, now):
        return EngineeringControlProduct.open_and_reconcile(
            self.database, self.root, expected_repository="acme/repository",
            trust_store=self.trust, now_ns=now,
        )

    def plan(self, package_id, path, profile=None):
        return self.product.plan_work(
            self.envelope,
            (EngineeringWorkPackage(0, package_id, (), (path,), required_skills=("python",)),),
            (profile or self.profile,), (), EngineeringCapacity(1, ()),
            generation_id="generation-" + package_id, now_ns=self.now,
        )

    def lease(self, path="src"):
        return self.product.acquire_lease(
            "lease", "env", "worker", (path,), authority_epoch=1,
            expires_unix_ns=self.now + 500_000, now_ns=self.now + 1,
        )

    def claim(self, plan, *, now=None, ttl=100):
        return self.product.claim(
            plan.generation_id, plan.assignments[0].package_id, "worker", "lease",
            heartbeat_ttl_ns=ttl, now_ns=self.now + 2 if now is None else now,
        )

    def test_multiskill_profile_order_is_canonical_and_claim_replay_survives_reopen(self):
        plan = self.plan("job", "src/job")
        anchor = self.product.audit_anchor()
        self.assertEqual(
            self.plan("job", "src/job", replace(self.profile, skills=tuple(reversed(self.profile.skills)))),
            plan,
        )
        self.assertEqual(self.product.audit_anchor(), anchor)
        self.lease()
        claim = self.claim(plan)
        self.assertEqual(claim.state, "claimed")
        self.assertEqual(self.product.worker_capacity("worker").reserved_units, 1)
        self.product.close()
        self.product = self.open_product(self.now + 3)
        anchor = self.product.audit_anchor()
        self.assertEqual(self.claim(plan, now=self.now + 4), claim)
        self.assertEqual(self.product.audit_anchor(), anchor)
        self.assertEqual(self.product.worker_capacity("worker").reserved_units, 1)

    def test_legacy_unsorted_immutable_plan_remains_claimable(self):
        def historical_sort(values, *arguments, **keywords):
            if isinstance(values, tuple) and values == self.profile.skills:
                return list(values)
            return sorted(values, *arguments, **keywords)

        # Reproduce the historical planner serialization through the real
        # durable publisher rather than rewriting an already sealed owner row.
        with mock.patch.object(orchestration, "sorted", side_effect=historical_sort, create=True):
            plan = self.plan("legacy", "src/legacy")
        row = self.product.store.connection.execute(
            "SELECT semantic_digest,plan_json FROM orchestration_generations WHERE generation_id=?",
            (plan.generation_id,),
        ).fetchone()
        persisted = (str(row["semantic_digest"]), bytes(row["plan_json"]))
        self.assertEqual(json.loads(persisted[1])["workers"][0]["skills"], ["rust", "python"])
        self.lease()
        claim = self.claim(plan)
        self.assertEqual(claim.state, "claimed")
        row = self.product.store.connection.execute(
            "SELECT semantic_digest,plan_json FROM orchestration_generations WHERE generation_id=?",
            (plan.generation_id,),
        ).fetchone()
        self.assertEqual((str(row["semantic_digest"]), bytes(row["plan_json"])), persisted)
        self.product.close()
        self.product = self.open_product(self.now + 3)
        self.assertEqual(self.claim(plan, now=self.now + 4), claim)

    def test_cross_generation_overlap_rejects_but_disjoint_same_lease_and_terminal_release_work(self):
        first = self.plan("first", "src/shared")
        overlapping = self.plan("overlap", "src/shared/nested")
        disjoint = self.plan("disjoint", "src/other")
        self.lease()
        first_claim = self.claim(first)
        self.claim(disjoint, now=self.now + 3)
        anchor = self.product.audit_anchor()
        with self.assertRaisesRegex(EngineeringError, "active_claim_path_conflict"):
            self.claim(overlapping, now=self.now + 4)
        self.assertEqual(self.product.audit_anchor(), anchor)
        self.assertEqual(self.product.worker_capacity("worker").reserved_units, 2)
        heartbeat = WorkerHeartbeatReceipt(
            "worker", "worker-key", first_claim.claim_id, first_claim.claim_fence,
            first_claim.revision, self.now + 5, self.now + 1000,
        )
        heartbeat = replace(heartbeat, signature=self.trust.sign(heartbeat, "worker", "worker-key"))
        running = self.product.heartbeat(heartbeat, heartbeat_ttl_ns=100, now_ns=self.now + 5)
        result = WorkerResultReceipt(
            "worker", "worker-key", running.claim_id, running.claim_fence,
            running.revision, "e" * 64, "semantic_failure", self.now + 6, self.now + 1000,
        )
        result = replace(result, signature=self.trust.sign(result, "worker", "worker-key"))
        failed = self.product.submit_result(result, now_ns=self.now + 6)
        self.assertEqual(failed.state, "failed")
        accepted = self.claim(overlapping, now=self.now + 7)
        self.assertEqual(accepted.state, "claimed")
        self.assertEqual(self.product.worker_capacity("worker").reserved_units, 2)

    def test_expired_heartbeat_cannot_keep_path_authority_or_revive_old_claim(self):
        first = self.plan("first", "src/shared")
        replacement = self.plan("replacement", "src/shared")
        self.lease()
        first_claim = self.claim(first, ttl=1)
        replacement_claim = self.claim(replacement, now=self.now + 4)
        self.assertEqual(replacement_claim.state, "claimed")
        with self.assertRaisesRegex(EngineeringError, "claim_heartbeat_expired"):
            self.claim(first, now=self.now + 4)
        report = self.product.startup_reconcile(now_ns=self.now + 5)
        self.assertEqual(report.heartbeat_expired_claims, (first_claim.claim_id,))
        self.assertEqual(report.active_claims, (replacement_claim.claim_id,))
        self.assertEqual(self.product.worker_capacity("worker").reserved_units, 1)

    def test_same_owner_cannot_create_distinct_live_leases_for_overlapping_paths(self):
        self.lease("src/shared")
        anchor = self.product.audit_anchor()
        with self.assertRaisesRegex(EngineeringError, "active_path_conflict"):
            self.product.acquire_lease(
                "other-lease", "env", "worker", ("src/shared/nested",), authority_epoch=1,
                expires_unix_ns=self.now + 500_000, now_ns=self.now + 2,
            )
        self.assertEqual(self.product.audit_anchor(), anchor)

    def test_two_product_connections_cannot_claim_overlapping_writes_concurrently(self):
        first = self.plan("first", "src/shared")
        second = self.plan("second", "src/shared")
        self.lease()

        def claim_from_connection(plan):
            with self.open_product(self.now + 2) as product:
                try:
                    return product.claim(
                        plan.generation_id, plan.assignments[0].package_id, "worker", "lease",
                        heartbeat_ttl_ns=100, now_ns=self.now + 2,
                    ).state
                except EngineeringError as error:
                    return error.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(claim_from_connection, (first, second)))
        self.assertEqual(sorted(outcomes), ["active_claim_path_conflict", "claimed"])
        self.assertEqual(self.product.worker_capacity("worker").reserved_units, 1)


if __name__ == "__main__":
    unittest.main()
