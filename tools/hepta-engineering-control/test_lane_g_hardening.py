from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from control_engineering_v2 import (
    AssimilationProposal,
    AttestedSandboxParity,
    BoundEvidenceDecision,
    Candidate,
    CandidateEnvelope,
    CandidateEvidenceBindingReceipt,
    EngineeringError,
    EngineeringStore,
    EvidenceDecision,
    ExecutionReceipt,
    HmacTrustStore,
    Mutation,
    OwnerConsentAttestation,
    OwnerConsentReceipt,
    SandboxParityAttestation,
    SandboxParityReceipt,
    SandboxReceipt,
    WorkEnvelope,
    WorkPackage,
    generate_candidates,
    hardened_prepare_assimilation_candidate,
    hardened_request_independent_review,
    hardened_sandbox_candidate,
    semantic_digest,
)

DENIED = (
    "runtime_authority",
    "merge_authority",
    "activation_authority",
    "promotion_authority",
    "release_authority",
    "external_effect_authority",
)


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )


def initialize_repository(root: Path) -> tuple[str, str]:
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "lane-g-hardening@example.invalid")
    git(root, "config", "user.name", "Lane G Hardening")
    (root / "src").mkdir()
    (root / "src/base.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    commit = git(root, "rev-parse", "HEAD").stdout.strip()
    tree = git(root, "rev-parse", "HEAD^{tree}").stdout.strip()
    return commit, tree
from control_engineering_v2.closure import bind_candidate_evidence


class ErrorAndStoreHardeningTests(unittest.TestCase):
    def envelope(self, now: int) -> WorkEnvelope:
        return WorkEnvelope(
            "env-hardening",
            "a" * 40,
            "b" * 40,
            "c" * 64,
            "d" * 64,
            "developer-productivity",
            ("tools/hepta-engineering-control",),
            DENIED,
            4,
            now + 10_000_000,
        )

    def test_engineering_error_has_stable_code(self) -> None:
        error = EngineeringError("malformed_evidence")
        self.assertEqual(error.code, "malformed_evidence")
        self.assertEqual(str(error), "malformed_evidence")

    def test_generation_is_bound_to_envelope_and_lease_frontier(self) -> None:
        now = 1_000_000
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "store.sqlite3") as store:
                store.issue_work_envelope(self.envelope(now), now_ns=now)
                package = WorkPackage(
                    0,
                    "package-a",
                    (),
                    ("tools/hepta-engineering-control/a",),
                )
                first = store.schedule_ready_packages(
                    "env-hardening",
                    (package,),
                    (),
                    generation_id="generation-a",
                    now_ns=now + 1,
                )
                self.assertEqual(first.assigned, ("package-a",))
                frontier = store.assignment_frontier("generation-a")
                self.assertEqual(frontier["envelopeRevision"], 1)
                self.assertEqual(len(str(frontier["frontierDigest"])), 64)

                store.acquire_path_lease(
                    "lease-a",
                    "env-hardening",
                    "worker-a",
                    ("tools/hepta-engineering-control/unrelated",),
                    authority_epoch=3,
                    expires_unix_ns=now + 5_000_000,
                    now_ns=now + 2,
                )
                with self.assertRaisesRegex(
                    EngineeringError,
                    "generation_frontier_conflict",
                ):
                    store.schedule_ready_packages(
                        "env-hardening",
                        (package,),
                        (),
                        generation_id="generation-a",
                        now_ns=now + 3,
                    )

    def test_eligible_decision_requires_candidate_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "store.sqlite3") as store:
                with self.assertRaisesRegex(
                    EngineeringError,
                    "sealed_evidence_required",
                ):
                    from control_engineering_v2 import record_integration_decision

                    record_integration_decision(
                        store,
                        "decision-unbound",
                        EvidenceDecision(True, (), "e" * 64),
                        now_ns=1,
                    )


class CandidateSandboxHardeningTests(unittest.TestCase):
    def test_zero_checks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            commit, _tree = initialize_repository(root)
            envelope = CandidateEnvelope(
                "env",
                commit,
                ("src",),
                protected_paths=("qualification",),
                require_network_isolation=False,
            )
            candidate = generate_candidates(
                envelope,
                (Mutation("add_file", "src/new.txt", replacement_text="new\n"),),
            )[1]
            with self.assertRaisesRegex(
                EngineeringError,
                "invalid_check",
            ):
                hardened_sandbox_candidate(root, envelope, candidate, ())

    def test_dirty_source_is_rejected_before_candidate_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            commit, _tree = initialize_repository(root)
            (root / "untracked.txt").write_text("dirty\n", encoding="utf-8")
            envelope = CandidateEnvelope(
                "env",
                commit,
                ("src",),
                protected_paths=("qualification",),
                require_network_isolation=False,
            )
            candidate = generate_candidates(envelope, ())[0]
            with self.assertRaisesRegex(
                EngineeringError,
                "source_tree_mutated",
            ):
                hardened_sandbox_candidate(
                    root,
                    envelope,
                    candidate,
                    ((sys.executable, "-c", "print('ok')"),),
                )

    def test_candidate_has_no_git_metadata_and_cannot_change_caller_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            commit, tree = initialize_repository(root)
            envelope = CandidateEnvelope(
                "env",
                commit,
                ("src",),
                protected_paths=("qualification",),
                require_network_isolation=False,
            )
            candidate = generate_candidates(
                envelope,
                (Mutation("add_file", "src/new.txt", replacement_text="new\n"),),
            )[1]
            script = (
                "import subprocess; "
                "subprocess.run(['git','update-ref','refs/heads/candidate-only','HEAD'],check=True)"
            )
            tested, receipt = hardened_sandbox_candidate(
                root,
                envelope,
                candidate,
                ((sys.executable, "-c", script),),
            )
            self.assertEqual(tested.state, "rejected")
            self.assertFalse(receipt.passed)
            self.assertEqual(git(root, "rev-parse", "HEAD^{tree}").stdout.strip(), tree)
            missing = git(
                root,
                "show-ref",
                "--verify",
                "refs/heads/candidate-only",
                check=False,
            )
            self.assertNotEqual(missing.returncode, 0)

    def test_check_cannot_rewrite_candidate_after_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            commit, _tree = initialize_repository(root)
            envelope = CandidateEnvelope(
                "env",
                commit,
                ("src",),
                protected_paths=("qualification",),
                require_network_isolation=False,
            )
            candidate = generate_candidates(
                envelope,
                (Mutation("add_file", "src/new.txt", replacement_text="new\n"),),
            )[1]
            script = "from pathlib import Path; Path('src/new.txt').write_text('rewritten\\n')"
            with self.assertRaisesRegex(
                EngineeringError,
                "source_tree_mutated",
            ):
                hardened_sandbox_candidate(
                    root,
                    envelope,
                    candidate,
                    ((sys.executable, "-c", script),),
                )


class CandidateEvidenceBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = time.time_ns()
        self.base_commit = "a" * 40
        self.candidate = Candidate(
            "candidate-a",
            "envelope-a",
            self.base_commit,
            Mutation("no_change"),
            "c" * 64,
            "sandbox_tested",
            (),
            None,
        )
        self.sandbox = SandboxReceipt(
            self.candidate.candidate_id,
            self.base_commit,
            "b" * 40,
            "b" * 40,
            (("check-a", 0),),
            0,
            True,
            10,
            True,
            filesystem_isolated=True,
            isolation_adapter="bubblewrap-unshare-all-ro-workspace-v2",
            check_set_digest="1" * 64,
            candidate_state_digest_before="2" * 64,
            candidate_state_digest_after="2" * 64,
            source_worktree_digest_before="3" * 64,
            source_worktree_digest_after="3" * 64,
        )
        self.sandbox_digest = semantic_digest(asdict(self.sandbox))
        self.candidate = replace(
            self.candidate,
            sandbox_receipt_digest=self.sandbox_digest,
        )
        self.evidence = EvidenceDecision(True, (), "e" * 64)
        self.source_execution = ExecutionReceipt(
            "source-run",
            "exact_source",
            self.base_commit,
            "b" * 40,
            (),
            "1" * 64,
            True,
            "ci_executor",
            "ci-key",
            self.now - 10,
            self.now + 1_000_000_000,
        )
        self.merge_execution = ExecutionReceipt(
            "merge-run",
            "synthetic_merge",
            "d" * 40,
            "b" * 40,
            ("f" * 40, self.base_commit),
            "2" * 64,
            True,
            "ci_executor",
            "ci-key",
            self.now - 10,
            self.now + 1_000_000_000,
        )
        self.trust = HmacTrustStore({("ci_executor", "ci-key"): b"ci-secret"})
        for field in ("source_execution", "merge_execution"):
            receipt = getattr(self, field)
            setattr(self, field, replace(receipt, signature=self.trust.sign(
                receipt, receipt.issuer, receipt.signing_identity)))


    def binding(self) -> CandidateEvidenceBindingReceipt:
        value = CandidateEvidenceBindingReceipt(
            self.candidate.candidate_id,
            self.candidate.semantic_digest,
            self.sandbox_digest,
            self.base_commit,
            self.evidence.evidence_digest,
            semantic_digest(asdict(self.source_execution)),
            semantic_digest(asdict(self.merge_execution)),
            "ci_executor",
            "ci-key",
            self.now - 10,
            self.now + 1_000_000_000,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_unbound_evidence_cannot_request_review(self) -> None:
        with self.assertRaisesRegex(EngineeringError, "candidate_binding_required"):
            hardened_request_independent_review(
                self.candidate,
                self.evidence,
                "independent_evaluator",
                now_ns=self.now,
            )

    def test_signed_binding_allows_review_request_but_no_acceptance(self) -> None:
        bound = bind_candidate_evidence(
            self.candidate,
            self.sandbox,
            self.evidence,
            self.source_execution,
            self.merge_execution,
            self.binding(),
            self.trust,
            now_ns=self.now,
        )
        self.assertIsInstance(bound, BoundEvidenceDecision)
        request = hardened_request_independent_review(
            self.candidate,
            bound,
            "independent_evaluator",
            now_ns=self.now,
        )
        self.assertEqual(request.status, "review_requested")
        self.assertFalse(request.independent_acceptance)
        self.assertFalse(request.merge_authority)
        self.assertFalse(request.release_authority)

    def test_binding_cannot_be_replayed_for_another_candidate(self) -> None:
        other = replace(self.candidate, candidate_id="candidate-b")
        with self.assertRaisesRegex(
            EngineeringError,
            "sandbox_candidate_binding_mismatch",
        ):
            bind_candidate_evidence(
                other,
                self.sandbox,
                self.evidence,
                self.source_execution,
                self.merge_execution,
                self.binding(),
                self.trust,
                now_ns=self.now,
            )


class AssimilationAttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = time.time_ns()
        self.owner = "external-owner"
        self.target = "1" * 64
        self.trust = HmacTrustStore(
            {
                (self.owner, "owner-key"): b"owner-secret",
                ("independent-evaluator", "eval-key"): b"eval-secret",
            }
        )
        template = OwnerConsentReceipt(
            self.owner,
            self.target,
            ("query_version", "query_health"),
            ("isolated-rootfs",),
            self.now - 100,
            self.now + 1_000_000_000,
            "0" * 64,
        )
        payload = semantic_digest(
            {
                "ownerPrincipal": template.owner_principal,
                "targetIdentityDigest": template.target_identity_digest,
                "allowedOperations": tuple(sorted(template.allowed_operations)),
                "allowedRoots": tuple(sorted(template.allowed_roots)),
                "observedUnixNs": template.observed_unix_ns,
                "expiresUnixNs": template.expires_unix_ns,
            }
        )
        self.consent = replace(template, receipt_digest=payload)
        attestation = OwnerConsentAttestation(
            self.owner,
            self.target,
            payload,
            self.owner,
            "owner-key",
            self.now - 50,
            self.now + 1_000_000_000,
        )
        self.consent_attestation = replace(
            attestation,
            signature=self.trust.sign(
                attestation,
                attestation.issuer,
                attestation.signing_identity,
            ),
        )
        self.observations = {
            "os_id": "debian",
            "os_version": "13",
            "package_inventory_digest": "3" * 64,
            "service_graph_digest": "4" * 64,
            "mutable_state_digest": "5" * 64,
            "provenance_digest": "6" * 64,
        }

    def factory(self, manifest, operations) -> AttestedSandboxParity:
        manifest_digest = semantic_digest(asdict(manifest))
        operations_digest = semantic_digest([asdict(item) for item in operations])
        receipt = SandboxParityReceipt(
            self.target,
            manifest_digest,
            operations_digest,
            "7" * 64,
            "8" * 64,
            "9" * 64,
            "independent-evaluator",
            "generator",
            True,
        )
        attestation = SandboxParityAttestation(
            semantic_digest(asdict(receipt)),
            manifest_digest,
            operations_digest,
            "independent-evaluator",
            "eval-key",
            self.now - 10,
            self.now + 1_000_000_000,
        )
        return AttestedSandboxParity(
            receipt,
            replace(
                attestation,
                signature=self.trust.sign(
                    attestation,
                    attestation.issuer,
                    attestation.signing_identity,
                ),
            ),
        )

    def test_authenticated_pipeline_still_stops_at_dormant_candidate(self) -> None:
        proposal = hardened_prepare_assimilation_candidate(
            self.consent,
            self.observations,
            ("runtime_processes_not_observed",),
            self.factory,
            trust_store=self.trust,
            consent_attestation=self.consent_attestation,
            now_ns=self.now,
        )
        self.assertIsInstance(proposal, AssimilationProposal)
        self.assertEqual(proposal.state, "dormant_candidate")
        self.assertFalse(proposal.activation)
        self.assertFalse(proposal.federation)
        self.assertFalse(proposal.propagation)
        self.assertFalse(proposal.authority_granted)

    def test_unsigned_or_unattested_parity_is_rejected(self) -> None:
        def unsigned_factory(manifest, operations):
            return self.factory(manifest, operations).receipt

        with self.assertRaisesRegex(
            EngineeringError,
            "sandbox_attestation_missing",
        ):
            hardened_prepare_assimilation_candidate(
                self.consent,
                self.observations,
                (),
                unsigned_factory,
                trust_store=self.trust,
                consent_attestation=self.consent_attestation,
                now_ns=self.now,
            )


if __name__ == "__main__":
    unittest.main()
