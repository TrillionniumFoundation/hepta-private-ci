from dataclasses import replace
import unittest

from control_engineering_v2 import (
    WorkerHeartbeatReceipt,
    WorkerRegistrationRenewalReceipt,
    WorkerResultReceipt,
)
from control_engineering_v2.control_plane import EngineeringError
import test_product_claim_admission as claim_fixtures


class ProductCapacityRenewalReplayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = claim_fixtures.ProductClaimAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def renew(self, capacity, *, observed=None, expires=None, skills=None, paths=None):
        fixture = self.fixture
        row = fixture.product.store.connection.execute(
            "SELECT revision,profile_digest FROM worker_registrations WHERE worker_id='worker'"
        ).fetchone()
        receipt = WorkerRegistrationRenewalReceipt(
            "worker", int(row["revision"]), str(row["profile_digest"]), "worker-key",
            fixture.profile.skills if skills is None else skills, capacity,
            fixture.profile.allowed_paths if paths is None else paths,
            "engineering_worker_identity", "identity-key",
            fixture.now + 3 if observed is None else observed,
            fixture.envelope.expires_unix_ns if expires is None else expires,
        )
        receipt = replace(
            receipt,
            signature=fixture.trust.sign(receipt, receipt.issuer, receipt.signing_identity),
        )
        return fixture.product.renew_worker_registration(receipt, now_ns=receipt.observed_unix_ns)

    def test_live_claim_ack_survives_capacity_increase_decrease_and_reopen(self):
        fixture = self.fixture
        plan = fixture.plan("committed", "src/committed")
        fixture.lease()
        claim = fixture.claim(plan)
        for capacity, observed in ((5, fixture.now + 3), (1, fixture.now + 5)):
            self.renew(capacity, observed=observed)
            anchor = fixture.product.audit_anchor()
            self.assertEqual(fixture.claim(plan, now=observed + 1), claim)
            self.assertEqual(fixture.product.audit_anchor(), anchor)
            usage = fixture.product.worker_capacity("worker")
            self.assertEqual((usage.capacity_units, usage.reserved_units, usage.active_claims), (capacity, 1, 1))
        fixture.product.close()
        fixture.product = fixture.open_product(fixture.now + 7)
        anchor = fixture.product.audit_anchor()
        self.assertEqual(fixture.claim(plan, now=fixture.now + 8), claim)
        self.assertEqual(fixture.product.audit_anchor(), anchor)
        self.assertEqual(fixture.product.worker_capacity("worker").reserved_units, 1)

    def test_capacity_change_does_not_admit_unclaimed_stale_plan(self):
        fixture = self.fixture
        committed = fixture.plan("committed", "src/committed")
        pending = fixture.plan("pending", "src/pending")
        fixture.lease()
        claim = fixture.claim(committed)
        self.renew(5)
        anchor = fixture.product.audit_anchor()
        with self.assertRaisesRegex(EngineeringError, "worker_profile_drift"):
            fixture.claim(pending, now=fixture.now + 4)
        self.assertEqual(fixture.product.audit_anchor(), anchor)
        self.assertEqual(fixture.product.worker_capacity("worker").reserved_units, 1)
        self.assertEqual(fixture.claim(committed, now=fixture.now + 4), claim)

    def test_capacity_cannot_drop_below_existing_reservations(self):
        fixture = self.fixture
        first = fixture.plan("first", "src/first")
        second = fixture.plan("second", "src/second")
        fixture.lease()
        first_claim = fixture.claim(first)
        fixture.claim(second)
        anchor = fixture.product.audit_anchor()
        with self.assertRaisesRegex(EngineeringError, "worker_registration_capacity_below_reserved"):
            self.renew(1)
        self.assertEqual(fixture.product.audit_anchor(), anchor)
        usage = fixture.product.worker_capacity("worker")
        self.assertEqual((usage.capacity_units, usage.reserved_units, usage.active_claims), (4, 2, 2))
        self.assertEqual(fixture.claim(first, now=fixture.now + 4), first_claim)

    def test_running_and_submitted_claim_ack_retains_current_committed_result(self):
        fixture = self.fixture
        plan = fixture.plan("job", "src/job")
        fixture.lease()
        claim = fixture.claim(plan)
        heartbeat = WorkerHeartbeatReceipt(
            "worker", "worker-key", claim.claim_id, claim.claim_fence, claim.revision,
            fixture.now + 3, fixture.now + 1000,
        )
        heartbeat = replace(heartbeat, signature=fixture.trust.sign(heartbeat, "worker", "worker-key"))
        running = fixture.product.heartbeat(heartbeat, heartbeat_ttl_ns=100, now_ns=fixture.now + 3)
        self.renew(5, observed=fixture.now + 4)
        anchor = fixture.product.audit_anchor()
        self.assertEqual(fixture.claim(plan, now=fixture.now + 5), running)
        self.assertEqual(fixture.product.audit_anchor(), anchor)
        result = WorkerResultReceipt(
            "worker", "worker-key", running.claim_id, running.claim_fence, running.revision,
            "e" * 64, "success", fixture.now + 6, fixture.now + 1000,
        )
        result = replace(result, signature=fixture.trust.sign(result, "worker", "worker-key"))
        submitted = fixture.product.submit_result(result, now_ns=fixture.now + 6)
        self.assertEqual(submitted.state, "result_submitted")
        anchor = fixture.product.audit_anchor()
        self.assertEqual(fixture.claim(plan, now=fixture.now + 7), submitted)
        self.assertEqual(fixture.product.audit_anchor(), anchor)
        self.assertEqual(fixture.product.worker_capacity("worker").reserved_units, 0)

    def test_capacity_renewal_does_not_revive_expired_claim_or_owner_frontiers(self):
        cases = (
            ("heartbeat", 103, 1_000_000, "claim_heartbeat_expired"),
            ("lease", 500_001, 1_000_000, "claim_lease_invalid"),
            ("registration", 1_000_000, 1_000_000, "worker_not_active"),
            ("envelope", 1_000_000, 2_000_000, "expired_envelope"),
        )
        for name, replay_delta, registration_delta, expected in cases:
            with self.subTest(frontier=name):
                fixture = claim_fixtures.ProductClaimAdmissionTests()
                fixture.setUp()
                previous_fixture = self.fixture
                self.fixture = fixture
                try:
                    plan = fixture.plan("job", "src/job")
                    fixture.lease()
                    claim = fixture.claim(plan)
                    self.renew(5, expires=fixture.now + registration_delta)
                    anchor = fixture.product.audit_anchor()
                    with self.assertRaisesRegex(EngineeringError, expected):
                        fixture.claim(plan, now=fixture.now + replay_delta)
                    self.assertEqual(fixture.product.audit_anchor(), anchor)
                    self.assertEqual(fixture.product.claim_state(claim.claim_id), claim)
                    self.assertEqual(fixture.product.worker_capacity("worker").reserved_units, 1)
                finally:
                    self.fixture = previous_fixture
                    fixture.doCleanups()

    def test_retryable_attempt_still_requires_a_current_plan_profile(self):
        fixture = self.fixture
        plan = fixture.plan("job", "src/job")
        fixture.lease()
        claim = fixture.claim(plan)
        heartbeat = WorkerHeartbeatReceipt(
            "worker", "worker-key", claim.claim_id, claim.claim_fence, claim.revision,
            fixture.now + 3, fixture.now + 1000,
        )
        heartbeat = replace(heartbeat, signature=fixture.trust.sign(heartbeat, "worker", "worker-key"))
        running = fixture.product.heartbeat(heartbeat, heartbeat_ttl_ns=100, now_ns=fixture.now + 3)
        result = WorkerResultReceipt(
            "worker", "worker-key", running.claim_id, running.claim_fence, running.revision,
            "e" * 64, "infra_failure", fixture.now + 4, fixture.now + 1000,
        )
        result = replace(result, signature=fixture.trust.sign(result, "worker", "worker-key"))
        retryable = fixture.product.submit_result(result, now_ns=fixture.now + 4)
        self.assertEqual(retryable.state, "retryable")
        self.renew(5, observed=fixture.now + 5)
        anchor = fixture.product.audit_anchor()
        with self.assertRaisesRegex(EngineeringError, "worker_profile_drift"):
            fixture.claim(plan, now=fixture.now + 6)
        self.assertEqual(fixture.product.audit_anchor(), anchor)
        self.assertEqual(fixture.product.claim_state(claim.claim_id), retryable)
        self.assertEqual(fixture.product.worker_capacity("worker").reserved_units, 0)

    def test_committed_ack_cannot_bypass_changed_skill_or_scope_profile(self):
        cases = (({"skills": ("rust",)}, "skill"), ({"paths": ("src/new",)}, "scope"))
        for changes, name in cases:
            with self.subTest(binding=name):
                fixture = claim_fixtures.ProductClaimAdmissionTests()
                fixture.setUp()
                previous_fixture = self.fixture
                self.fixture = fixture
                try:
                    plan = fixture.plan("job", "src/job")
                    fixture.lease()
                    claim = fixture.claim(plan)
                    heartbeat = WorkerHeartbeatReceipt(
                        "worker", "worker-key", claim.claim_id, claim.claim_fence, claim.revision,
                        fixture.now + 3, fixture.now + 1000,
                    )
                    heartbeat = replace(heartbeat, signature=fixture.trust.sign(heartbeat, "worker", "worker-key"))
                    running = fixture.product.heartbeat(heartbeat, heartbeat_ttl_ns=100, now_ns=fixture.now + 3)
                    result = WorkerResultReceipt(
                        "worker", "worker-key", running.claim_id, running.claim_fence, running.revision,
                        "e" * 64, "success", fixture.now + 4, fixture.now + 1000,
                    )
                    result = replace(result, signature=fixture.trust.sign(result, "worker", "worker-key"))
                    fixture.product.submit_result(result, now_ns=fixture.now + 4)
                    self.renew(5, observed=fixture.now + 5, **changes)
                    anchor = fixture.product.audit_anchor()
                    with self.assertRaisesRegex(EngineeringError, "worker_profile_drift"):
                        fixture.claim(plan, now=fixture.now + 6)
                    self.assertEqual(fixture.product.audit_anchor(), anchor)
                    self.assertEqual(fixture.product.worker_capacity("worker").reserved_units, 0)
                finally:
                    self.fixture = previous_fixture
                    fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
