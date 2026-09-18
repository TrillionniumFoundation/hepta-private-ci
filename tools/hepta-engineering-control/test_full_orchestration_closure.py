from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest

from control_engineering_v2 import (
    AuditAnchorReceipt,
    CandidateEnvelope,
    DistributedWriteGrant,
    EngineeringStore,
    EngineeringWorkPackage,
    HmacTrustStore,
    HostSandboxLimiter,
    KeyCustodyReceipt,
    Mutation,
    MutationProbeResult,
    PatchOperation,
    ReviewCapacity,
    WorkCompletionReceipt,
    WorkEnvelope,
    WorkerCapacity,
    evaluate_mutation_probes,
    export_audit_anchor,
    generate_candidate_bundle,
    generate_candidates,
    orchestration_generation,
    persist_orchestration_generation,
    plan_engineering_work,
    verify_audit_anchor_receipt,
    verify_distributed_write_grant,
    verify_key_custody_receipt,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES, EngineeringError


class FullOrchestrationClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_000_000
        self.source_commit = "a" * 40
        self.source_tree = "b" * 40
        self.trust = HmacTrustStore(
            {
                ("ci_executor", "ci"): b"ci",
                ("external_coordinator", "coord"): b"coord",
                ("external_audit_anchor", "audit"): b"audit",
                ("external_key_custodian", "hsm"): b"hsm",
            }
        )
        self.envelope = WorkEnvelope(
            "env",
            self.source_commit,
            self.source_tree,
            "1" * 64,
            "2" * 64,
            "developer-productivity",
            ("src",),
            tuple(sorted(DENIED_AUTHORITIES)),
            8,
            self.now + 100_000,
        )

    def _completion(self, package_id: str = "done") -> WorkCompletionReceipt:
        receipt = WorkCompletionReceipt(
            package_id,
            "prior-generation",
            self.source_commit,
            self.source_tree,
            "3" * 64,
            "completed",
            "ci_executor",
            "ci",
            self.now,
            self.now + 50_000,
        )
        return replace(
            receipt,
            signature=self.trust.sign(receipt, receipt.issuer, receipt.signing_identity),
        )

    def test_scheduler_consumes_signed_completion_and_multidimensional_capacity(self) -> None:
        packages = (
            EngineeringWorkPackage(
                0,
                "high-value",
                ("done",),
                ("src/high.py",),
                ("python",),
                1,
                1,
                ("architecture_reviewer",),
                10_000,
                4_000,
                1_000,
                "lane-g",
            ),
            EngineeringWorkPackage(
                0,
                "low-value",
                ("done",),
                ("src/low.py",),
                ("python",),
                1,
                1,
                ("architecture_reviewer",),
                1_000,
                0,
                10_000,
                "lane-g",
            ),
        )
        plan = plan_engineering_work(
            self.envelope,
            packages,
            (WorkerCapacity("worker", ("python",), 1, ("src",)),),
            (self._completion(),),
            self.trust,
            generation_id="generation",
            review_capacity=(ReviewCapacity("architecture_reviewer", 1),),
            ci_capacity_units=1,
            now_ns=self.now + 1,
        )
        self.assertEqual(tuple(item.package_id for item in plan.assignments), ("high-value",))
        self.assertIn(("low-value", "ci_capacity"), plan.blocked)
        self.assertEqual(plan.integration_order, ("high-value",))
        self.assertEqual(plan.merge_queue[0].package_id, "high-value")
        self.assertFalse(plan.merge_queue[0].merge_authority)
        self.assertFalse(plan.worker_write_authority)

        with tempfile.TemporaryDirectory() as directory:
            with EngineeringStore(Path(directory) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                persisted = persist_orchestration_generation(
                    store,
                    self.envelope,
                    plan,
                    packages,
                    (self._completion(),),
                    self.trust,
                    now_ns=self.now + 1,
                )
                durable = orchestration_generation(store, "generation")
                self.assertEqual(persisted.assigned, ("high-value",))
                self.assertEqual(
                    durable["plan"]["assignments"][0]["worker_id"], "worker"
                )
                self.assertEqual(
                    durable["plan"]["integrationOrder"], ["high-value"]
                )
                self.assertEqual(
                    durable["plan"]["mergeQueue"][0]["package_id"], "high-value"
                )

    def test_orchestration_respects_envelope_assignment_limit(self) -> None:
        envelope = replace(self.envelope, maximum_assignments=1)
        packages = (
            EngineeringWorkPackage(0, "first", (), ("src/first.py",), ("python",)),
            EngineeringWorkPackage(1, "second", (), ("src/second.py",), ("python",)),
        )
        plan = plan_engineering_work(
            envelope,
            packages,
            (WorkerCapacity("worker", ("python",), 2, ("src",)),),
            (),
            self.trust,
            generation_id="limited-generation",
            review_capacity=(),
            ci_capacity_units=2,
            now_ns=self.now + 1,
        )
        self.assertEqual(tuple(item.package_id for item in plan.assignments), ("first",))
        self.assertEqual(plan.blocked, (("second", "assignment_limit"),))

    def test_forged_completion_receipt_fails_closed(self) -> None:
        forged = replace(self._completion(), source_tree="c" * 40)
        with self.assertRaisesRegex(EngineeringError, "completion_source_mismatch"):
            plan_engineering_work(
                self.envelope,
                (
                    EngineeringWorkPackage(
                        0, "next", ("done",), ("src/next.py",), ("python",)
                    ),
                ),
                (WorkerCapacity("worker", ("python",), 1, ("src",)),),
                (forged,),
                self.trust,
                generation_id="generation",
                review_capacity=(),
                ci_capacity_units=1,
                now_ns=self.now + 1,
            )

    def test_test_and_evaluator_paths_are_unconditionally_protected(self) -> None:
        envelope = CandidateEnvelope(
            "candidate-env",
            self.source_commit,
            ("src",),
            require_network_isolation=False,
        )
        for path in (
            "src/lib_tests.rs",
            "src/fixtures/input.json",
            "src/golden/result.json",
            "src/evaluator/policy.py",
            "src/component.spec.ts",
            "src/component.test.js",
        ):
            with self.subTest(path=path):
                with self.assertRaisesRegex(EngineeringError, "protected_oracle_path"):
                    generate_candidates(
                        envelope,
                        (Mutation("replace_text", path, "old", "new"),),
                    )

    def test_multi_file_and_rename_candidate_bundle_are_content_addressed(self) -> None:
        envelope = CandidateEnvelope(
            "candidate-env",
            self.source_commit,
            ("src",),
            require_network_isolation=False,
        )
        bundle = generate_candidate_bundle(
            envelope,
            (
                PatchOperation("add_file", "src/a.py", replacement_text="a = 1\n"),
                PatchOperation("add_file", "src/b.py", replacement_text="b = 2\n"),
                PatchOperation("rename_file", "src/old.py", "src/new.py"),
            ),
        )
        self.assertEqual(
            bundle.changed_paths,
            ("src/a.py", "src/b.py", "src/new.py", "src/old.py"),
        )
        self.assertEqual(bundle.state, "drafted")
        self.assertFalse(bundle.merge_authority)

    def test_host_sandbox_limiter_caps_parallelism(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            limiter = HostSandboxLimiter(directory, maximum_slots=2)
            first = limiter.acquire()
            second = limiter.acquire()
            try:
                with self.assertRaisesRegex(EngineeringError, "sandbox_capacity_exhausted"):
                    limiter.acquire(deadline_monotonic=time.monotonic())
            finally:
                first.close()
                second.close()

    def test_mutation_testing_requires_every_probe_to_be_killed(self) -> None:
        failed = evaluate_mutation_probes(
            "4" * 64,
            (
                MutationProbeResult("p1", "t1", "5" * 64, True),
                MutationProbeResult("p2", "t2", "6" * 64, False),
            ),
        )
        self.assertFalse(failed.passed)
        self.assertEqual(failed.surviving_probe_ids, ("p2",))
        passed = evaluate_mutation_probes(
            "4" * 64,
            (MutationProbeResult("p1", "t1", "5" * 64, True),),
        )
        self.assertTrue(passed.passed)

    def test_external_fencing_audit_anchor_and_key_custody_are_verified(self) -> None:
        grant = DistributedWriteGrant(
            "coordinator",
            7,
            42,
            "worker",
            self.source_commit,
            self.source_tree,
            ("src",),
            "external_coordinator",
            "coord",
            self.now,
            self.now + 50_000,
        )
        grant = replace(
            grant,
            signature=self.trust.sign(grant, grant.issuer, grant.signing_identity),
        )
        verified = verify_distributed_write_grant(
            grant,
            self.trust,
            worker_id="worker",
            source_commit=self.source_commit,
            source_tree=self.source_tree,
            requested_paths=("src/a.py",),
            minimum_leader_epoch=7,
            minimum_fencing_token=42,
            now_ns=self.now + 1,
        )
        self.assertEqual(verified.fencing_token, 42)

        with tempfile.TemporaryDirectory() as directory:
            with EngineeringStore(Path(directory) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                unsigned = export_audit_anchor(store, database_id="engineering-db")
            anchor = replace(
                unsigned,
                signing_identity="audit",
                observed_unix_ns=self.now,
                expires_unix_ns=self.now + 50_000,
            )
            anchor = replace(
                anchor,
                signature=self.trust.sign(anchor, anchor.issuer, anchor.signing_identity),
            )
            self.assertEqual(
                verify_audit_anchor_receipt(
                    anchor,
                    self.trust,
                    expected_database_id="engineering-db",
                    now_ns=self.now + 1,
                ).sequence,
                1,
            )

        custody = KeyCustodyReceipt(
            "hsm-provider",
            "engineering-verifier-key",
            "engineering-evidence-verification",
            True,
            False,
            "external_key_custodian",
            "hsm",
            self.now,
            self.now + 50_000,
        )
        custody = replace(
            custody,
            signature=self.trust.sign(custody, custody.issuer, custody.signing_identity),
        )
        verified_custody = verify_key_custody_receipt(
            custody, self.trust, now_ns=self.now + 1
        )
        self.assertTrue(verified_custody.hardware_backed)
        self.assertFalse(verified_custody.exportable)


if __name__ == "__main__":
    unittest.main()
