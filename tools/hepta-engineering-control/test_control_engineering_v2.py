from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from control_engineering_v2 import (
    CandidateEnvelope,
    CanonicalSourceReceipt,
    EngineeringError,
    EngineeringStore,
    EvaluatorIndependenceReceipt,
    ExecutionReceipt,
    HmacTrustStore,
    Mutation,
    OwnerConsentReceipt,
    SandboxParityReceipt,
    WorkEnvelope,
    WorkPackage,
    build_manifest_candidate,
    generate_candidates,
    propose_dormant_assimilation,
    sandbox_candidate,
    semantic_digest,
    synthesize_read_only_contracts,
    verify_integration_evidence,
)

DENIED = (
    "runtime_authority",
    "merge_authority",
    "activation_authority",
    "promotion_authority",
    "release_authority",
    "external_effect_authority",
)


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


class StoreTests(unittest.TestCase):
    def envelope(self, now: int = 1_000_000) -> WorkEnvelope:
        return WorkEnvelope(
            "env-1",
            "a" * 40,
            "b" * 40,
            "c" * 64,
            "d" * 64,
            "developer-productivity",
            ("tools/hepta-engineering-control",),
            DENIED,
            2,
            now + 1_000_000,
        )

    def test_fenced_lease_schedule_reopen_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "engineering.sqlite3"
            store = EngineeringStore(database)
            store.issue_work_envelope(self.envelope(), now_ns=1_000_000)
            lease = store.acquire_path_lease(
                "lease-1",
                "env-1",
                "worker-a",
                ("tools/hepta-engineering-control/a",),
                authority_epoch=7,
                expires_unix_ns=1_500_000,
                now_ns=1_000_001,
            )
            self.assertEqual(lease.fencing_token, 1)
            self.assertFalse(lease.runtime_authority)
            with self.assertRaisesRegex(EngineeringError, "active_path_conflict"):
                store.acquire_path_lease(
                    "lease-2",
                    "env-1",
                    "worker-b",
                    ("tools/hepta-engineering-control/a/sub",),
                    authority_epoch=7,
                    expires_unix_ns=1_500_000,
                    now_ns=1_000_002,
                )
            receipt = store.schedule_ready_packages(
                "env-1",
                (
                    WorkPackage(
                        0,
                        "A",
                        (),
                        ("tools/hepta-engineering-control/a",),
                    ),
                    WorkPackage(
                        1,
                        "B",
                        (),
                        ("tools/hepta-engineering-control/b",),
                    ),
                ),
                (),
                generation_id="generation-1",
                now_ns=1_000_003,
            )
            self.assertEqual(receipt.assigned, ("B",))
            self.assertEqual(receipt.blocked, (("A", "active_path_lease"),))
            renewed = store.transition_path_lease(
                "lease-1",
                expected_revision=1,
                authority_epoch=7,
                disposition="renew",
                new_expiry_unix_ns=1_700_000,
                now_ns=1_000_004,
            )
            self.assertEqual(renewed.revision, 2)
            with self.assertRaisesRegex(EngineeringError, "stale_lease_revision"):
                store.transition_path_lease(
                    "lease-1",
                    expected_revision=1,
                    authority_epoch=7,
                    disposition="release",
                    now_ns=1_000_005,
                )
            events = store.audit_projection()
            self.assertGreaterEqual(len(events), 4)
            store.close()
            reopened = EngineeringStore(database)
            reopened.verify_audit_chain()
            self.assertEqual(reopened.audit_projection(), events)
            reopened.close()

    def test_envelope_and_generation_semantic_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                value = self.envelope()
                store.issue_work_envelope(value, now_ns=1_000_000)
                store.issue_work_envelope(value, now_ns=1_000_000)
                with self.assertRaisesRegex(
                    EngineeringError,
                    "envelope_identity_conflict",
                ):
                    store.issue_work_envelope(
                        replace(value, maximum_assignments=1),
                        now_ns=1_000_000,
                    )
                package = WorkPackage(
                    0,
                    "A",
                    (),
                    ("tools/hepta-engineering-control/a",),
                )
                store.schedule_ready_packages(
                    "env-1",
                    (package,),
                    (),
                    generation_id="g",
                    now_ns=1_000_001,
                )
                with self.assertRaisesRegex(
                    EngineeringError,
                    "generation_identity_conflict",
                ):
                    store.schedule_ready_packages(
                        "env-1",
                        (
                            WorkPackage(
                                0,
                                "B",
                                (),
                                ("tools/hepta-engineering-control/b",),
                            ),
                        ),
                        (),
                        generation_id="g",
                        now_ns=1_000_002,
                    )

    def test_cycle_and_out_of_scope_paths_reject(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope(), now_ns=1_000_000)
                with self.assertRaisesRegex(EngineeringError, "dependency_cycle"):
                    store.schedule_ready_packages(
                        "env-1",
                        (
                            WorkPackage(
                                0,
                                "A",
                                ("B",),
                                ("tools/hepta-engineering-control/a",),
                            ),
                            WorkPackage(
                                0,
                                "B",
                                ("A",),
                                ("tools/hepta-engineering-control/b",),
                            ),
                        ),
                        (),
                        generation_id="cycle",
                        now_ns=1_000_001,
                    )
                with self.assertRaisesRegex(
                    EngineeringError,
                    "package_path_outside_envelope",
                ):
                    store.schedule_ready_packages(
                        "env-1",
                        (WorkPackage(0, "X", (), ("codex-rs/x",)),),
                        (),
                        generation_id="outside",
                        now_ns=1_000_001,
                    )

    def test_constructor_closes_connection_when_audit_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "store.db"
            store = EngineeringStore(database)
            store.issue_work_envelope(self.envelope(), now_ns=1_000_000)
            store.connection.execute(
                "UPDATE audit_events SET previous_digest=? WHERE sequence=1",
                ("f" * 64,),
            )
            store.close()
            with self.assertRaisesRegex(EngineeringError, "audit_chain_broken"):
                EngineeringStore(database)
            renamed = Path(temp) / "renamed.db"
            os.replace(database, renamed)
            self.assertTrue(renamed.exists())


class CandidateTests(unittest.TestCase):
    def test_no_change_dedupe_and_protected_paths(self) -> None:
        envelope = CandidateEnvelope(
            "env",
            "a" * 40,
            ("tools/hepta-engineering-control",),
            require_network_isolation=False,
        )
        values = generate_candidates(
            envelope,
            (
                Mutation(
                    "add_file",
                    "tools/hepta-engineering-control/new.txt",
                    replacement_text="hello\n",
                ),
                Mutation(
                    "add_file",
                    "tools/hepta-engineering-control/new.txt",
                    replacement_text="hello\n",
                ),
            ),
        )
        self.assertEqual(len(values), 2)
        self.assertEqual(values[0].mutation.operation, "no_change")
        with self.assertRaisesRegex(EngineeringError, "protected_path"):
            generate_candidates(
                CandidateEnvelope(
                    "env",
                    "a" * 40,
                    (".github",),
                    require_network_isolation=False,
                ),
                (
                    Mutation(
                        "add_file",
                        ".github/workflows/evil.yml",
                        replacement_text="x",
                    ),
                ),
            )

    def test_detached_sandbox_does_not_mutate_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            run_git(root, "init")
            run_git(root, "config", "user.email", "lane-g@example.invalid")
            run_git(root, "config", "user.name", "Lane G Test")
            (root / "tools/hepta-engineering-control").mkdir(parents=True)
            (root / "tools/hepta-engineering-control/base.txt").write_text(
                "base\n",
                encoding="utf-8",
            )
            run_git(root, "add", ".")
            run_git(root, "commit", "-m", "base")
            base = run_git(root, "rev-parse", "HEAD")
            tree = run_git(root, "rev-parse", "HEAD^{tree}")
            envelope = CandidateEnvelope(
                "env",
                base,
                ("tools/hepta-engineering-control",),
                protected_paths=("qualification",),
                require_network_isolation=False,
            )
            candidate = generate_candidates(
                envelope,
                (
                    Mutation(
                        "add_file",
                        "tools/hepta-engineering-control/candidate.txt",
                        replacement_text="candidate\n",
                    ),
                ),
            )[1]
            tested, receipt = sandbox_candidate(
                root,
                envelope,
                candidate,
                ((sys.executable, "-c", "print('ok')"),),
            )
            self.assertEqual(tested.state, "fixture_tested")
            self.assertTrue(receipt.passed)
            self.assertFalse(receipt.filesystem_isolated)
            self.assertFalse(receipt.network_isolated)
            self.assertFalse(receipt.authority_delta)
            self.assertEqual(run_git(root, "rev-parse", "HEAD^{tree}"), tree)
            self.assertFalse(
                (root / "tools/hepta-engineering-control/candidate.txt").exists()
            )


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        run_git(self.root, "init")
        run_git(self.root, "config", "user.email", "lane-g@example.invalid")
        run_git(self.root, "config", "user.name", "Lane G Test")
        run_git(
            self.root,
            "remote",
            "add",
            "origin",
            "https://github.com/TrillionniumFoundation/hepta-private-ci.git",
        )
        (self.root / "file.txt").write_text("base\n", encoding="utf-8")
        run_git(self.root, "add", ".")
        run_git(self.root, "commit", "-m", "base")
        self.base = run_git(self.root, "rev-parse", "HEAD")
        (self.root / "file.txt").write_text("source\n", encoding="utf-8")
        run_git(self.root, "commit", "-am", "source")
        self.source = run_git(self.root, "rev-parse", "HEAD")
        self.source_tree = run_git(self.root, "rev-parse", "HEAD^{tree}")
        self.merge = run_git(
            self.root,
            "commit-tree",
            self.source_tree,
            "-p",
            self.base,
            "-p",
            self.source,
            "-m",
            "synthetic merge",
        )
        self.now = 5_000_000
        self.document_digest = "d" * 64
        self.trust = HmacTrustStore(
            {
                ("source_authority", "source-key"): b"source-secret",
                ("ci_executor", "ci-key"): b"ci-secret",
                ("independent_evaluator", "eval-key"): b"eval-secret",
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def signed_receipts(self):
        source = CanonicalSourceReceipt(
            "TrillionniumFoundation/hepta-private-ci",
            self.source,
            self.source_tree,
            self.document_digest,
            "source_authority",
            "source-key",
            self.now - 100,
            self.now + 100,
        )
        source = replace(
            source,
            signature=self.trust.sign(
                source,
                source.issuer,
                source.signing_identity,
            ),
        )
        source_execution = ExecutionReceipt(
            "source-run",
            "exact_source",
            self.source,
            self.source_tree,
            (self.base,),
            "a" * 64,
            True,
            "ci_executor",
            "ci-key",
            self.now - 100,
            self.now + 100,
        )
        source_execution = replace(
            source_execution,
            signature=self.trust.sign(
                source_execution,
                source_execution.issuer,
                source_execution.signing_identity,
            ),
        )
        merge_execution = ExecutionReceipt(
            "merge-run",
            "synthetic_merge",
            self.merge,
            self.source_tree,
            (self.base, self.source),
            "b" * 64,
            True,
            "ci_executor",
            "ci-key",
            self.now - 100,
            self.now + 100,
        )
        merge_execution = replace(
            merge_execution,
            signature=self.trust.sign(
                merge_execution,
                merge_execution.issuer,
                merge_execution.signing_identity,
            ),
        )
        independence = EvaluatorIndependenceReceipt(
            "generator",
            "generator-key",
            "independent_evaluator",
            "eval-key",
            self.now - 100,
            self.now + 100,
        )
        independence = replace(
            independence,
            signature=self.trust.sign(
                independence,
                independence.evaluator_principal,
                independence.evaluator_signing_identity,
            ),
        )
        return source, source_execution, merge_execution, independence

    def test_exact_objects_and_independent_roles_pass_for_review_only(self) -> None:
        values = self.signed_receipts()
        decision = verify_integration_evidence(
            self.root,
            "TrillionniumFoundation/hepta-private-ci",
            *values,
            self.trust,
            expected_document_set_digest=self.document_digest,
            now_ns=self.now,
        )
        self.assertTrue(decision.eligible_for_independent_review)
        self.assertEqual(decision.reasons, ())
        self.assertFalse(decision.merge_authority)
        self.assertFalse(decision.release_authority)

    def test_tamper_and_role_collision_fail_closed(self) -> None:
        source, source_execution, merge_execution, independence = self.signed_receipts()
        collision = replace(
            independence,
            generator_principal=independence.evaluator_principal,
        )
        collision = replace(
            collision,
            signature=self.trust.sign(
                collision,
                collision.evaluator_principal,
                collision.evaluator_signing_identity,
            ),
        )
        decision = verify_integration_evidence(
            self.root,
            "TrillionniumFoundation/hepta-private-ci",
            source,
            replace(source_execution, passed=False),
            merge_execution,
            collision,
            self.trust,
            expected_document_set_digest=self.document_digest,
            now_ns=self.now,
        )
        self.assertFalse(decision.eligible_for_independent_review)
        self.assertIn("source_execution_signature", decision.reasons)
        self.assertIn("source_execution_failed", decision.reasons)
        self.assertIn("evaluator_identity_collision", decision.reasons)


class AssimilationTests(unittest.TestCase):
    def receipt(self, now: int) -> OwnerConsentReceipt:
        return OwnerConsentReceipt(
            "external-owner",
            "1" * 64,
            ("query_version", "query_health"),
            ("isolated-rootfs",),
            now - 10,
            now + 10,
            "2" * 64,
        )

    def test_read_only_pipeline_stops_at_dormant_candidate(self) -> None:
        now = 9_000_000
        consent = self.receipt(now)
        manifest = build_manifest_candidate(
            consent,
            {
                "os_id": "debian",
                "os_version": "13",
                "package_inventory_digest": "3" * 64,
                "service_graph_digest": "4" * 64,
                "mutable_state_digest": "5" * 64,
                "provenance_digest": "6" * 64,
            },
            ("runtime_processes_not_observed",),
            now_ns=now,
        )
        operations = synthesize_read_only_contracts(
            consent,
            manifest,
            now_ns=now,
        )
        sandbox = SandboxParityReceipt(
            consent.target_identity_digest,
            semantic_digest(manifest.__dict__),
            semantic_digest([value.__dict__ for value in operations]),
            "7" * 64,
            "8" * 64,
            "9" * 64,
            "independent-evaluator",
            "generator",
            True,
        )
        proposal = propose_dormant_assimilation(
            consent,
            manifest,
            operations,
            sandbox,
            now_ns=now,
        )
        self.assertEqual(proposal.state, "dormant_candidate")
        self.assertFalse(proposal.activation)
        self.assertFalse(proposal.propagation)
        self.assertFalse(proposal.authority_granted)

    def test_expired_or_effect_scope_rejects(self) -> None:
        now = 9_000_000
        with self.assertRaisesRegex(EngineeringError, "consent_expired"):
            build_manifest_candidate(
                replace(self.receipt(now), expires_unix_ns=now),
                {},
                (),
                now_ns=now,
            )
        with self.assertRaisesRegex(
            EngineeringError,
            "consent_scope_widens_authority",
        ):
            synthesize_read_only_contracts(
                replace(
                    self.receipt(now),
                    allowed_operations=("install_package",),
                ),
                None,
                now_ns=now,
            )


if __name__ == "__main__":
    unittest.main()
