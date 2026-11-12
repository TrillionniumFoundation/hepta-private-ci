"""Close explicit resident Root admission and the ordinary completed-A join.

These source mutations protect authority and ordering. They are not evidence
that any original deployment granted resident work or that an A/B/C run passed.
"""
import ast
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "resident_root_caller_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
EXPECTED = {
    "root_resident_original_register": [],
    "root_resident_original_recover": [],
    "root_resident_original_custody_open": [
        "codex-rs/hepta-agentd/src/authority_host_resident_registration.rs"
    ],
    "root_resident_original_custody_retain": [
        "codex-rs/hepta-agentd/src/authority_host_runtime.rs"
    ],
    "root_resident_registration_create": [
        "codex-rs/hepta-agentd/src/authority_host_resident_registration.rs"
    ],
    "root_resident_registration_recover": [
        "codex-rs/hepta-agentd/src/authority_host_resident_registration.rs"
    ],
    "root_resident_service_register": [],
    "root_resident_service_recover": [],
    "root_resident_runtime_consume": [],
    "root_resident_coordinator_run": [],
    "root_resident_original_stream_serve": [],
    "root_resident_original_client_create": [],
    "root_resident_original_client_recover": [],
    "root_resident_original_client_readback": [
        "codex-rs/hepta-agentd/src/resident_learning_delivery.rs"
    ],
    "root_resident_postclaim_admit": [
        "codex-rs/hepta-agentd/src/resident_learning_delivery.rs"
    ],
    "root_resident_preclaim_channel": [
        "codex-rs/hepta-agentd/src/resident_learning_delivery.rs"
    ],
    "root_resident_final_observation": [
        "codex-rs/hepta-agentd/src/resident_learning_delivery.rs"
    ],
    "root_resident_gate_effect_current": [
        "codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs",
        "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs"
    ],
    "root_resident_gate_training_cancel": [
        "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs"
    ],
    "root_resident_original_intent_fence": [
        "codex-rs/hepta-agentd/src/authority_host_learning_resident_authority.rs"
    ],
    "root_resident_original_intent_current": [
        "codex-rs/hepta-agentd/src/authority_host_learning_resident_authority.rs"
    ],
    "root_resident_late_enrollment_config": [],
    "root_resident_late_enrollment_submit": [],
    "root_resident_late_delivery_run": [
        "codex-rs/hepta-agentd/src/runtime.rs"
    ],
    "root_resident_late_source_candidate": [
        "codex-rs/hepta-agentd/src/resident_learning_delivery.rs"
    ],
    "root_resident_checkpoint_register": [
        "codex-rs/hepta-agentd/src/authority_host_learning_resident_authority.rs"
    ],
    "root_resident_checkpoint_recover": [
        "codex-rs/hepta-agentd/src/authority_host_learning_resident_authority.rs"
    ],
    "root_resident_checkpoint_fresh_cas": [
        "codex-rs/hepta-agentd/src/authority_host_learning_resident_authority.rs"
    ],
    "root_resident_registered_fresh_admit": [
        "codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs"
    ],
    "root_resident_gate_begin_dispatch": [
        "codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs"
    ],
    "root_resident_gate_commit_checkpoint": [
        "codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs"
    ]
}
ROOT_CASES = [
    "authority_host_service::resident::authority::tests::resident_root_formatter_and_original_registration_pin_both_scopes",
    "authority_host_service::resident::authority::tests::resident_root_reissued_intent_cannot_create_another_operation_namespace",
    "authority_host_service::resident::authority::tests::resident_root_only_actual_vacant_cas_creates_one_live_continuation",
    "authority_host_service::resident::authority::tests::resident_root_same_epoch_grant_revocation_fences_the_pending_effect",
    "authority_host_service::resident::authority::tests::resident_root_exact_lease_revocation_fences_without_restarting_dispatch",
    "authority_host_service::resident::authority::tests::resident_root_lost_fresh_ack_recovers_only_under_explicit_readback_intent",
    "authority_host_service::resident::authority::tests::resident_root_queued_admit_cancellation_sends_no_frame_and_consumes_channel",
    "authority_host_service::resident::authority::tests::resident_root_structured_uncertain_allows_only_same_operation_readback"
]

class ResidentRootSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def rejects(self, filename, function, marker, replacement=""):
        path = filename if filename.startswith("codex-rs/") else AGENT + filename
        source = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(source)
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + replacement + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_exact_new_callers_and_external_registration_stay_closed(self):
        paths = {path for name in EXPECTED for path in (
            self.boundaries[name].definition_path, *self.boundaries[name].product_callers
        )}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for name, expected in EXPECTED.items():
            with self.subTest(boundary=name):
                row = self.boundaries[name]
                self.assertIn(name, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, tuple(expected))
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                receiver = f"owner: &{row.receiver_type}" if row.receiver_type else ""
                call = f"owner.{method}()" if row.receiver_type else f"{method}()"
                extra = dict(sources)
                extra[AGENT + "unregistered_resident.rs"] = f"fn bypass({receiver}) {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_profile_is_only_canonical_data_and_stable_identity_rejects_rebinding(self):
        filename = "authority_host_learning_resident_profile.rs"
        for function, marker in (
            ("fn new(", "profile_identity(&initial, &scope, verifier)?"),
            ("fn new(", "require_artifacts("),
            ("fn new(", "&intent.signature"),
            ("fn new(", "lease.expires_at_unix_ms < deadline_ms"),
            ("fn profile_identity(", "expected.snapshot() != initial"),
            ("fn profile_identity(", "scope.validate_snapshot(initial)"),
            ("fn profile_identity(", "initial.request.operation_id.as_str()"),
            ("fn profile_identity(", "verifier.scope_digest().as_array()"),
            ("fn require_verifier(", "verifier.scope_digest() != self.evidence_scope"),
            ("fn require_artifacts(", "intent.grant.binding != *expected"),
            ("fn require_artifacts(", "lease.binding != lease_binding(expected)"),
            ("fn from_original_root(", "profile.expected(ResidentPurposeV3::Readback)?"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(filename, function, marker)
        self.rejects(filename, "fn owner_id(", "self.storage", "self.operation")

    def test_only_actual_strict_cas_can_mint_the_nonrecoverable_token(self):
        filename = "authority_host_learning_resident_store.rs"
        for function, marker in (
            ("fn register(", "HostAuthorityFrontierStore::initialize("),
            ("fn register(", "owner.read()?"),
            ("fn recover(", "HostAuthorityFrontierStore::open("),
            ("fn admit(", "self.admission_attempted.swap(true, Ordering::AcqRel)"),
            ("fn admit(", "snapshot.is_some() || current != Self::vacant(&self.profile)"),
            ("fn admit(", "self.store.compare_and_set(&self.owner_id, &current, &next)"),
            ("fn load(", "record.binding != self.profile.binding.to_string()"),
            ("fn load(", "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())"),
            ("fn load(", "self.profile.scope.validate_snapshot(&snapshot)"),
            ("fn begin_dispatch(", "coordinator.next_stage() != Some(stage)"),
            ("fn checkpoint(", "!next.receipts.starts_with(&predecessor.receipts)"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(filename, function, marker)
        self.rejects(filename, "fn recover(", "fresh_registration: false", "fresh_registration: true")
        self.rejects("codex-rs/hepta-contracts/src/authority_host_store.rs",
                     "fn initialize_bounded(", "store.root.exists(&store.name)?")
        self.rejects("codex-rs/hepta-contracts/src/authority_host_store.rs",
                     "fn compare_and_set(", "if &self.read()? != expected")

    def test_original_grant_registry_revocation_and_local_only_fence_are_mandatory(self):
        filename = "authority_host_learning_resident_authority.rs"
        for marker in (
            "self.root_pid != std::process::id()",
            "cancellation.is_cancelled()",
            "matches!(access, ResidentAccessV3::Work) && self.readonly()",
            "verifier.read_lease(&lease.lease_id)",
            "current.lease != *lease || intent.grant.binding != expected",
            "verifier.verify_use(&lease.lease_id, lease.revision, &binding)",
            "verifier.with_dispatch_boundary(token, &binding, ||",
            "self.issuer.hold_original_resident_intent_v3(",
            "let now_ms = issuer.require_current()?",
            "now_ms < started || cancellation.is_cancelled()",
        ):
            with self.subTest(marker=marker):
                self.rejects(filename, "fn perform(", marker)
        for marker in (
            "self.request_lock.try_lock()",
            "verify_strict(&bytes, &signature)",
            "state.head.revoked_grant_ids.contains(&grant.grant_id)",
            "sequence > state.sequence",
        ):
            with self.subTest(issuer=marker):
                self.rejects("deployment_learning_resident.rs",
                             "fn hold_original_resident_intent_v3", marker)
        self.rejects("deployment_learning_resident.rs", "fn require_current(",
                     "current.head != self.head")
        self.rejects("deployment_learning_resident.rs", "fn require_current(",
                     "now >= self.signed.grant.expires_at_unix_ms")

    def test_same_continuation_gate_is_cancelled_and_matches_the_durable_effect(self):
        filename = "authority_host_learning_resident_gate.rs"
        for function, marker in (
            ("fn admit(", "ResidentStoreActionV3::Admit(&owner.checkpoint)"),
            ("fn admit(", "cancellation.is_cancelled()"),
            ("fn drop(", "self.gate.fence()"),
            ("fn require_current(", "scope != &self.inner.owner.authority.profile.scope"),
            ("fn local(", "predecessor.request != profile.initial.request"),
            ("fn local(", "result.is_err() || self.inner.cancellation.is_cancelled()"),
            ("fn local_inner(", "inner.fresh.try_lock()"),
            ("fn local_inner(", "ResidentStoreActionV3::RequireDispatch"),
            ("fn local_inner(", "inner.owner.authority.perform(operation, &inner.cancellation)"),
            ("fn fence(", "self.inner.dispatch_cancel.store(true, Ordering::Release)"),
            ("fn training_cancellation(", "Arc::clone(&self.inner.dispatch_cancel)"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(filename, function, marker)

    def test_coordinator_installs_only_the_actual_fresh_token_and_never_replays_candidate(self):
        filename = "authority_host_learning_resident_runtime.rs"
        for function, marker in (
            ("fn compose(", "stages.require_initial(&profile.initial, &profile.scope, &verifier)"),
            ("fn run(", "self.admission_requested = true"),
            ("fn run(", "if result.is_err()"),
            ("fn admit(", "self.owner.admit(cancellation).await?"),
            ("fn admit(", "slot.take().ok_or(Error::CommitUncertain)?"),
            ("fn admit(", "stages.install_fresh_resident_gate(Arc::clone(&continuation.gate))?"),
            ("fn continue_original(", "LearningIterationStageV1::Evaluation | LearningIterationStageV1::Proposal"),
            ("fn continue_original(", "gate.begin(&predecessor, stage).await?"),
            ("fn continue_original(", "watchdog.tick()"),
            ("fn continue_original(", "authentication::original_attestations("),
            ("fn continue_original(", "gate.checkpoint(&predecessor, coordinator.snapshot().clone()).await?"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(filename, function, marker)
        self.rejects(filename, "fn readback(", "current.dispatch_pending != original.dispatch_pending")

    def test_queued_cancel_and_bound_refusal_never_restore_fresh_admission(self):
        filename = "authority_host_learning_resident_transport.rs"
        for marker in (
            ".take().ok_or(Error::Unavailable)?",
            "let cancelled = ResidentExchangeDropV3(",
            "Arc::clone(&cancelled.0)",
            "if send_cancelled.load(Ordering::Acquire)",
            "channel.peer.request(&bytes)",
            "response.authorization != authorization.to_string()",
            "response.action != action",
            "channel.peer.check_peer_lifetime()",
            "fresh < observed_at",
            "wire::require_original_prefix(",
            "authentication::verify_attestations(",
        ):
            with self.subTest(marker=marker):
                self.rejects(filename, "fn exchange(", marker)
        self.rejects(filename, "fn drop(", "self.0.store(true, Ordering::Release)")
        self.rejects(filename, "fn require_fresh_admission_channel(",
                     "channel.as_ref().is_none_or(|channel| channel.execution_requested)")
        self.rejects(filename, "fn recover_original_root_stream(",
                     "ClientOriginV3::Readback(authorization)", "ClientOriginV3::Fresh")

    def test_actual_completed_a_is_joined_before_claim_and_only_final_readback_retires(self):
        filename = "resident_learning_delivery.rs"
        for function, marker in (
            ("fn prepare_enrollment(", "AgentdRootResidentLearningClientV3::readback(&root).await?"),
            ("fn prepare_enrollment(", "root.require_fresh_admission_channel()?"),
            ("fn prepare_enrollment(", "state.require_resident_learning_source_candidate(request).await"),
            ("fn prepare_enrollment(", "host.reconcile_learning_outbox(store, Some(&request.source_run_id)).await"),
            ("fn deliver(", "self.admission = DeliveryAdmissionV3::Readback"),
            ("fn deliver(", "store.claim_circuit_learning(&row.intent, &digest).await"),
            ("fn deliver(", "coordinator.next_stage().is_some()"),
            ("fn deliver(", "self.root.revalidate_original_observation(&observed)?"),
            ("fn deliver(", "store.acknowledge_circuit_learning(&row.intent, &digest, &head).await"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(filename, function, marker)
        for marker in (
            "original.0.snapshot.generation != generation",
            "after.history_digest() != before.history_digest()",
            "host.learning_source_record(request)? != original",
            "self.current_generation()? != generation",
        ):
            self.rejects("objective_learning_source.rs",
                         "fn require_resident_learning_source_candidate(", marker)
        self.rejects("config_resident_learning.rs",
                     "fn with_root_resident_learning_enrollment(",
                     "self.learning_iteration_bootstrap.is_some()")

    def test_every_original_signature_is_revalidated_after_actual_role_and_root_reads(self):
        filename = "authority_host_learning_resident_auth.rs"
        for function, marker in (
            ("fn original_attestations(", "stages.validate_recovery(snapshot).await?"),
            ("fn original_attestations(", "stages.receipt_attestation(snapshot, receipt, now / 1_000).await?"),
            ("fn original_attestations(", "let (_, fresh) = owner.read(cancellation).await?"),
            ("fn verify_attestations(", "signatures.len() != snapshot.receipts.len()"),
            ("fn verify_attestations(", "verifier.verify(role, signature, &payload, now)"),
            ("fn verify_attestations(", "snapshot.training_no_update_v2().is_none()"),
            ("fn verify_attestations(", "verify_signed_actor_separation(&previous.1, current, now)"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(filename, function, marker)
        self.rejects("authority_host_learning_resident_wire.rs", "fn require_original_prefix(",
                     "!current.attestations.starts_with(evidence)")

    def test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof(self):
        workflow = (ROOT / ".github/workflows/hepta-daemon-learning-native.yml").read_text()
        match = re.search(r"parents = (\[[\s\S]*?\n          \])", workflow)
        self.assertIsNotNone(match)
        parents = ast.literal_eval(match.group(1))
        self.assertEqual(len(parents), len(set(parents)))
        self.assertTrue(set(ROOT_CASES).issubset(parents))
        self.assertEqual(len(parents), 7 + len(ROOT_CASES))
        roots = (ROOT / (AGENT + "authority_host_learning_resident_root_tests.rs")).read_text()
        for name in ROOT_CASES:
            self.assertIn("fn " + name.rsplit("::", 1)[-1] + "(", roots)
        self.assertEqual(roots.count('#[ignore = "explicit actual Root'), len(ROOT_CASES))
        for marker in (
            '"codex-rs/hepta-neuron/**"', '"-p", "codex-hepta-neuron"',
            '"codex-rs/hepta-neuron/"', "  caller-proof:",
            '("self-test", 300), ("verify", 4800)',
            'command = ["python3", "scripts/verify_hepta_callers.py", phase]',
            'result["returncode"] or result["timed_out"] or result["output_limit_exceeded"]',
            'if after != before:', "daemon-learning-caller-proof",
        ):
            self.assertIn(marker, workflow)

if __name__ == "__main__":
    unittest.main()
