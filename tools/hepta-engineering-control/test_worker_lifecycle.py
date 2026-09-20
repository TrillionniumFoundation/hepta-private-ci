from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    CompletionReceipt,
    EngineeringCapacity,
    EngineeringStore,
    EngineeringWorkPackage,
    HmacTrustStore,
    ReviewCapacity,
    WorkerHeartbeatReceipt,
    WorkerProfile,
    WorkerRegistrationReceipt,
    WorkerResultReceipt,
    WorkEnvelope,
    claim_assignment,
    expire_stale_claims,
    heartbeat_claim,
    observe_claim_completion,
    plan_engineering_work,
    register_worker,
    semantic_digest,
    submit_worker_result,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES


class WorkerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000_000
        self.envelope = WorkEnvelope(
            "env",
            "a" * 40,
            "b" * 40,
            "c" * 64,
            "d" * 64,
            "developer-productivity",
            ("src",),
            tuple(sorted(DENIED_AUTHORITIES)),
            4,
            self.now + 10_000_000_000,
        )
        self.trust = HmacTrustStore(
            {
                ("engineering_worker_identity", "identity-key"): b"identity",
                ("worker-a", "worker-key"): b"worker",
                ("ci_executor", "ci-key"): b"ci",
            }
        )

    def register(self, store):
        value = WorkerRegistrationReceipt(
            "worker-a",
            "worker-key",
            ("python",),
            4,
            ("src",),
            "engineering_worker_identity",
            "identity-key",
            self.now - 1,
            self.now + 9_000_000_000,
        )
        value = replace(
            value,
            signature=self.trust.sign(
                value, value.issuer, value.signing_identity
            ),
        )
        register_worker(store, value, self.trust, now_ns=self.now)

    def plan_and_lease(self, store):
        store.issue_work_envelope(self.envelope, now_ns=self.now)
        plan = plan_engineering_work(
            store,
            self.envelope,
            (
                EngineeringWorkPackage(
                    0,
                    "package-a",
                    (),
                    ("src/package-a",),
                    required_skills=("python",),
                    capacity_units=1,
                    ci_units=1,
                    review_roles=("architecture",),
                    expected_value_q32=100,
                ),
            ),
            (WorkerProfile("worker-a", ("python",), 4, ("src",)),),
            (),
            self.trust,
            EngineeringCapacity(1, (ReviewCapacity("architecture", 1),)),
            generation_id="generation-a",
            now_ns=self.now,
        )
        self.assertEqual(plan.assignments[0].worker_id, "worker-a")
        lease = store.acquire_path_lease(
            "lease-a",
            "env",
            "worker-a",
            ("src/package-a",),
            authority_epoch=1,
            expires_unix_ns=self.now + 8_000_000_000,
            now_ns=self.now + 1,
        )
        return plan, lease

    def heartbeat(self, claim, observed):
        value = WorkerHeartbeatReceipt(
            "worker-a",
            "worker-key",
            claim.claim_id,
            claim.claim_fence,
            claim.revision,
            observed,
            observed + 1_000_000_000,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.worker_id, value.worker_signing_identity),
        )

    def result(self, claim, observed, outcome):
        value = WorkerResultReceipt(
            "worker-a",
            "worker-key",
            claim.claim_id,
            claim.claim_fence,
            claim.revision,
            "e" * 64,
            outcome,
            observed,
            observed + 1_000_000_000,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.worker_id, value.worker_signing_identity),
        )

    def completion(self, store, claim, observed):
        generation = store.connection.execute(
            "SELECT semantic_digest FROM assignment_generations WHERE generation_id=?",
            (claim.generation_id,),
        ).fetchone()
        value = CompletionReceipt(
            claim.package_id,
            self.envelope.source_commit,
            self.envelope.source_tree,
            claim.generation_id,
            str(generation[0]),
            "e" * 64,
            "ci_executor",
            "ci-key",
            observed,
            observed + 1_000_000_000,
            True,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_claim_heartbeat_worker_result_and_independent_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.register(store)
                _plan, _lease = self.plan_and_lease(store)
                claim = claim_assignment(
                    store,
                    "generation-a",
                    "package-a",
                    "worker-a",
                    "lease-a",
                    heartbeat_ttl_ns=1_000_000_000,
                    now_ns=self.now + 2,
                )
                running = heartbeat_claim(
                    store,
                    self.heartbeat(claim, self.now + 3),
                    self.trust,
                    heartbeat_ttl_ns=1_000_000_000,
                    now_ns=self.now + 3,
                )
                submitted = submit_worker_result(
                    store,
                    self.result(running, self.now + 4, "success"),
                    self.trust,
                    now_ns=self.now + 4,
                )
                self.assertEqual(submitted.state, "result_submitted")
                self.assertNotEqual(submitted.state, "completed_observed")
                completed = observe_claim_completion(
                    store,
                    submitted.claim_id,
                    self.envelope,
                    self.completion(store, submitted, self.now + 5),
                    self.trust,
                    now_ns=self.now + 5,
                )
                self.assertEqual(completed.state, "completed_observed")

    def test_timeout_requeues_but_semantic_failure_never_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.register(store)
                self.plan_and_lease(store)
                first = claim_assignment(
                    store,
                    "generation-a",
                    "package-a",
                    "worker-a",
                    "lease-a",
                    heartbeat_ttl_ns=10,
                    now_ns=self.now + 2,
                )
                self.assertEqual(
                    expire_stale_claims(store, now_ns=self.now + 12),
                    (first.claim_id,),
                )
                second = claim_assignment(
                    store,
                    "generation-a",
                    "package-a",
                    "worker-a",
                    "lease-a",
                    heartbeat_ttl_ns=1_000_000_000,
                    now_ns=self.now + 13,
                )
                self.assertEqual(second.attempt, 2)
                running = heartbeat_claim(
                    store,
                    self.heartbeat(second, self.now + 14),
                    self.trust,
                    heartbeat_ttl_ns=1_000_000_000,
                    now_ns=self.now + 14,
                )
                failed = submit_worker_result(
                    store,
                    self.result(running, self.now + 15, "semantic_failure"),
                    self.trust,
                    now_ns=self.now + 15,
                )
                self.assertEqual(failed.state, "failed")
                with self.assertRaisesRegex(ValueError, "assignment_already_claimed"):
                    claim_assignment(
                        store,
                        "generation-a",
                        "package-a",
                        "worker-a",
                        "lease-a",
                        heartbeat_ttl_ns=1_000_000_000,
                        now_ns=self.now + 16,
                    )

    def test_claim_requires_registered_assigned_worker_and_fenced_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.plan_and_lease(store)
                with self.assertRaisesRegex(ValueError, "worker_not_active"):
                    claim_assignment(
                        store,
                        "generation-a",
                        "package-a",
                        "worker-a",
                        "lease-a",
                        heartbeat_ttl_ns=1_000_000_000,
                        now_ns=self.now + 2,
                    )


if __name__ == "__main__":
    unittest.main()
