from dataclasses import replace
from pathlib import Path
import subprocess
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
    admit_distributed_write_grant,
    distributed_write_frontier,
    evaluate_mutation_probes,
    export_audit_anchor,
    generate_candidate_bundle,
    generate_candidates,
    orchestration_generation,
    persist_orchestration_generation,
    plan_engineering_work,
    sandbox_candidate_bundle,
    verify_audit_anchor_receipt,
    verify_distributed_write_grant,
    verify_key_custody_receipt,
    verify_store_audit_anchor,
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

    def test_candidate_bundle_sandbox_supports_nested_atomic_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.name", "Lane G Test"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "lane-g@example.invalid"],
                cwd=root,
                check=True,
            )
            source = root / "src"
            source.mkdir()
            (source / "old.py").write_text("old = True\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            envelope = CandidateEnvelope(
                "bundle-env",
                base,
                ("src",),
                require_network_isolation=False,
            )
            bundle = generate_candidate_bundle(
                envelope,
                (
                    PatchOperation(
                        "add_file",
                        "src/new/a.py",
                        replacement_text="a = 1\n",
                    ),
                    PatchOperation(
                        "add_file",
                        "src/new/b.py",
                        replacement_text="b = 2\n",
                    ),
                    PatchOperation(
                        "rename_file",
                        "src/old.py",
                        "src/renamed.py",
                    ),
                ),
            )
            tested, receipt = sandbox_candidate_bundle(
                root,
                envelope,
                bundle,
                (
                    (
                        "python3",
                        "-c",
                        "from pathlib import Path; "
                        "assert Path('src/new/a.py').read_text() == 'a = 1\\n'; "
                        "assert Path('src/new/b.py').read_text() == 'b = 2\\n'; "
                        "assert Path('src/renamed.py').read_text() == 'old = True\\n'; "
                        "assert not Path('src/old.py').exists()",
                    ),
                ),
            )
            self.assertEqual(tested.state, "fixture_tested")
            self.assertTrue(receipt.passed)
            self.assertTrue((source / "old.py").is_file())
            self.assertFalse((source / "new").exists())
            self.assertFalse((source / "renamed.py").exists())

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

    def test_distributed_frontier_rejects_superseded_grants(self) -> None:
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
        with tempfile.TemporaryDirectory() as directory:
            with EngineeringStore(Path(directory) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                admitted = admit_distributed_write_grant(
                    store,
                    grant,
                    self.trust,
                    worker_id="worker",
                    source_commit=self.source_commit,
                    source_tree=self.source_tree,
                    requested_paths=("src/a.py",),
                    now_ns=self.now + 1,
                )
                self.assertEqual(admitted.fencing_token, 42)

                newer = replace(
                    grant,
                    fencing_token=43,
                    observed_unix_ns=self.now + 2,
                    signature="",
                )
                newer = replace(
                    newer,
                    signature=self.trust.sign(
                        newer,
                        newer.issuer,
                        newer.signing_identity,
                    ),
                )
                admit_distributed_write_grant(
                    store,
                    newer,
                    self.trust,
                    worker_id="worker",
                    source_commit=self.source_commit,
                    source_tree=self.source_tree,
                    requested_paths=("src/a.py",),
                    now_ns=self.now + 3,
                )
                frontier = distributed_write_frontier(store, "worker")
                self.assertEqual(frontier["leaderEpoch"], 7)
                self.assertEqual(frontier["fencingToken"], 43)

                with self.assertRaisesRegex(
                    EngineeringError,
                    "distributed_fence_stale",
                ):
                    admit_distributed_write_grant(
                        store,
                        grant,
                        self.trust,
                        worker_id="worker",
                        source_commit=self.source_commit,
                        source_tree=self.source_tree,
                        requested_paths=("src/a.py",),
                        now_ns=self.now + 4,
                    )

    def test_audit_anchor_binds_authoritative_store_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with EngineeringStore(Path(directory) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                unsigned = export_audit_anchor(
                    store,
                    database_id="engineering-db",
                )
                anchor = replace(
                    unsigned,
                    signing_identity="audit",
                    observed_unix_ns=self.now,
                    expires_unix_ns=self.now + 50_000,
                )
                anchor = replace(
                    anchor,
                    signature=self.trust.sign(
                        anchor,
                        anchor.issuer,
                        anchor.signing_identity,
                    ),
                )
                verified = verify_store_audit_anchor(
                    store,
                    anchor,
                    self.trust,
                    expected_database_id="engineering-db",
                    now_ns=self.now + 1,
                )
                self.assertEqual(verified.sequence, 1)

                store.connection.execute(
                    "UPDATE work_envelopes SET owner=? WHERE envelope_id=?",
                    ("tampered-owner", self.envelope.envelope_id),
                )
                with self.assertRaisesRegex(
                    EngineeringError,
                    "audit_anchor_store_mismatch",
                ):
                    verify_store_audit_anchor(
                        store,
                        anchor,
                        self.trust,
                        expected_database_id="engineering-db",
                        now_ns=self.now + 2,
                    )

    def test_key_custody_binds_subject_key_attestation(self) -> None:
        custody = KeyCustodyReceipt(
            provider="hsm-provider",
            key_id="engineering-verifier-key",
            purpose="engineering-evidence-verification",
            hardware_backed=True,
            exportable=False,
            issuer="external_key_custodian",
            signing_identity="hsm",
            observed_unix_ns=self.now,
            expires_unix_ns=self.now + 50_000,
            subject_signing_identity="engineering-evidence-binder-key",
            algorithm="ed25519",
            public_key_digest="7" * 64,
            attestation_digest="8" * 64,
        )
        custody = replace(
            custody,
            signature=self.trust.sign(
                custody,
                custody.issuer,
                custody.signing_identity,
            ),
        )
        verified = verify_key_custody_receipt(
            custody,
            self.trust,
            expected_subject_signing_identity="engineering-evidence-binder-key",
            now_ns=self.now + 1,
        )
        self.assertTrue(verified.hardware_backed)
        self.assertFalse(verified.exportable)
        with self.assertRaisesRegex(
            EngineeringError,
            "key_custody_identity_mismatch",
        ):
            verify_key_custody_receipt(
                custody,
                self.trust,
                expected_subject_signing_identity="different-key",
                now_ns=self.now + 1,
            )


if __name__ == "__main__":
    unittest.main()
