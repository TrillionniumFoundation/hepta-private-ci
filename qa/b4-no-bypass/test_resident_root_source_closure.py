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
    "root_resident_coordinator_run": ['codex-rs/hepta-agentd/src/authority_host_learning_candidate_service.rs'],
    "root_resident_original_stream_serve": ['codex-rs/hepta-agentd/src/authority_host_learning_candidate_service.rs'],
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
    "root_resident_gate_effect_current": ['codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs', 'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs', 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_readback.rs', 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_evaluation.rs', 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs', 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained_execute.rs'],
    "root_resident_gate_training_cancel": ['codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs', 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs', 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained_execute.rs'],
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
    "authority_host_service::resident::authority::tests::resident_root_structured_uncertain_allows_only_same_operation_readback",
    "authority_host_service::resident::authority::tests::evaluation::resident_root_original_evaluation_requires_actual_checkpoint_and_independent_signature",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_four_cut_preserves_original_wire_and_all_signatures",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_five_cut_uses_original_record_without_fifth_signature",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_refuses_missing_extra_wrong_stage_or_reordered_evidence",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_refuses_changed_record_context_and_signature_window",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_cold_checkpoint_is_readonly_and_pins_complete_original_bytes",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_unknown_dispatch_never_recommits_or_mints_fresh_gate",
    "authority_host_service::resident::authority::tests::retention_auth::resident_root_retention_auth_roundtrip_keeps_exact_six_stage_prefix",
    "authority_host_service::resident::authority::tests::retention_auth::resident_root_retention_auth_refuses_changed_order_bundle_role_and_window",
    "authority_host_service::resident::authority::tests::retention_auth::resident_root_retention_auth_refuses_all_cocontrolled_role_pairs",
    "authority_host_service::resident::authority::tests::retention_auth::resident_root_retention_auth_keeps_training_no_update_at_five_stages",
    "authority_host_service::resident::authority::tests::provider_transport::resident_role_handoff_elapsed_real_time_cannot_renew_any_original_deadline",
    "authority_host_service::resident::authority::tests::provider_transport::resident_role_admission_rejects_actual_uid_pidfd_and_process_start_mismatch",
    "authority_host_service::resident::authority::tests::provider_transport::resident_role_receiver_refuses_another_real_recipient_or_registered_profile",
    "authority_host_service::resident::authority::tests::provider_transport::lifecycle::resident_idle_original_a_eof_does_not_cancel_fresh_or_readonly_root",
    "authority_host_service::resident::authority::tests::provider_transport::lifecycle::resident_idle_root_cancel_closes_live_a_and_joins_original_work",
    "authority_host_service::resident::authority::tests::provider_transport::lifecycle::resident_idle_delivery_delay_keeps_original_service_expiry_and_joins",
]
ROOT_ISSUER_CASES = [
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_uses_actual_prepared_binding_and_installs_distinct_c",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_denied_once_keeps_actual_prepared_operation_read_only",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_lost_ack_never_reissues_original_intent",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_wrong_grant_cannot_replace_prepared_purpose",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_withdrawal_before_root_request_sends_no_frame",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_queued_cancellation_sends_no_frame_and_never_reopens_once",
    "runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::evaluated_publication::publication_fixture::version_recovery_tests::final_use_tests::evaluated_version_late_b_loss_keeps_published_material_but_cannot_serve_s_or_start_c",
]
ROOT_CUSTODY_CASES = ['runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::tests::root_initial_custody_refuses_another_operation_without_rewriting_current',
 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::tests::root_initial_custody_failed_publish_keeps_only_same_operation_readback',
 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::tests::root_initial_custody_installs_the_original_task_and_drains_its_same_cell',
 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::tests::root_initial_custody_installation_error_retains_original_publication_readback',
 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::tests::root_initial_custody_original_artifact_withdrawal_fences_task_installation',
 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::cold_tests::root_initial_cold_entry_reopens_existing_current_and_runs_the_original_task',
 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::cold_tests::root_initial_cold_entry_refuses_pending_without_reprepare_or_grant',
 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::cold_tests::root_initial_cold_entry_rechecks_original_artifact_after_published_readback',
 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::cold_tests::root_initial_cold_entry_retains_same_operation_after_installation_error']

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
            ("fn admit(", "self.store\n            .compare_and_set(&self.owner_id, &current, &next)"),
            ("fn load(", "record.binding != self.profile.binding.to_string()"),
            ("fn load(", "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())"),
            ("fn load(", "self.profile\n            .scope\n            .validate_snapshot(&snapshot)"),
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
        self.rejects(filename, "fn new(", "unsafe { libc::geteuid() } != 0")
        for marker in (
            "self.root_pid != std::process::id()",
            "unsafe { libc::geteuid() } != 0",
            "cancellation.is_cancelled()",
            "matches!(access, ResidentAccessV3::Work) && self.readonly()",
            "verifier\n            .read_lease(&lease.lease_id)",
            "current.lease != *lease || intent.grant.binding != expected",
            "verifier\n            .verify_use(&lease.lease_id, lease.revision, &binding)",
            "verifier\n            .with_dispatch_boundary(token, &binding, ||",
            "self\n                    .issuer\n                    .hold_original_resident_intent_v3(",
            "let now_ms = issuer.require_current()?",
            "now_ms < started || cancellation.is_cancelled()",
        ):
            with self.subTest(marker=marker):
                self.rejects(filename, "fn perform(", marker)
        for marker in (
            "self\n            .request_lock\n            .try_lock()",
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
            ("fn local_inner(", "inner\n                .owner\n                .authority\n                .perform(operation, &inner.cancellation)"),
            ("fn fence(", "self.inner.dispatch_cancel.store(true, Ordering::Release)"),
            ("fn training_cancellation(", "Arc::clone(&self.inner.dispatch_cancel)"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(filename, function, marker)

    def test_coordinator_installs_only_the_actual_fresh_token_and_never_replays_candidate(self):
        filename = "authority_host_learning_resident_runtime.rs"
        for function, marker in (
            ("fn compose(", "ResidentOriginalStageOwnersV3::require_initial(\n        &stages,\n        &profile.initial,\n        &profile.scope,\n        &verifier,\n    )"),
            ("fn run(", "self.admission_requested = true"),
            ("fn run(", "if result.is_err()"),
            ("fn admit(", "ResidentRegisteredStateV3::admit(&self.owner, cancellation).await?"),
            ("fn admit(", "slot.take().ok_or(Error::CommitUncertain)?"),
            ("fn admit(", "ResidentOriginalStageOwnersV3::install_fresh_resident_gate("),
            ("fn continue_original(", "ResidentOriginalStageOwnersV3::require_stage(\n            stages.as_ref(),\n            coordinator.snapshot(),\n            stage,\n        )?"),
            ("fn continue_original(", "gate.begin(&predecessor, stage).await?"),
            ("fn continue_original(", "watchdog.tick()"),
            ("fn continue_original(", "authentication::original_attestations("),
            ("fn continue_original(", "gate.checkpoint(&predecessor, coordinator.snapshot().clone())\n            .await?"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(filename, function, marker)
        self.rejects(filename, "fn readback(", "current.dispatch_pending != original.dispatch_pending")

    def test_queued_cancel_and_bound_refusal_never_restore_fresh_admission(self):
        filename = "authority_host_learning_resident_transport.rs"
        for marker in (
            ".take()\n            .ok_or(Error::Unavailable)?",
            "let cancelled = ResidentExchangeDropV3(",
            "Arc::clone(&cancelled.0)",
            "if send_cancelled.load(Ordering::Acquire)",
            "channel\n                .peer\n                .request(&bytes)",
            "response.authorization != authorization.to_string()",
            "response.action != action",
            "channel\n                .peer\n                .check_peer_lifetime()",
            "fresh < observed_at",
            "wire::require_original_prefix(",
            "authentication::verify_original_evidence(",
        ):
            with self.subTest(marker=marker):
                self.rejects(filename, "fn exchange(", marker)
        self.rejects(filename, "fn drop(", "self.0.store(true, Ordering::Release)")
        self.rejects(filename, "fn require_fresh_admission_channel(",
                     "channel\n            .as_ref()\n            .is_none_or(|channel| channel.execution_requested)")
        self.rejects(filename, "fn recover_original_root_stream(",
                     "ClientOriginV3::Readback(authorization)", "ClientOriginV3::Fresh")

    def test_actual_completed_a_is_joined_before_claim_and_only_final_readback_retires(self):
        filename = "resident_learning_delivery.rs"
        for function, marker in (
            ("fn prepare_enrollment(", "AgentdRootResidentLearningClientV3::readback(&root).await?"),
            ("fn prepare_enrollment(", "root.require_fresh_admission_channel()?"),
            ("fn prepare_enrollment(", "state\n            .require_resident_learning_source_candidate(request)\n            .await"),
            ("fn prepare_enrollment(", "host.reconcile_learning_outbox(store, Some(&request.source_run_id))\n            .await"),
            ("fn deliver(", "self.admission = DeliveryAdmissionV3::Readback"),
            ("fn deliver(", "store\n                .claim_circuit_learning(&row.intent, &digest)\n                .await"),
            ("fn deliver(", "coordinator.next_stage().is_some()"),
            ("fn deliver(", "self.root.revalidate_original_observation(&observed)?"),
            ("fn deliver(", "store\n            .acknowledge_circuit_learning(&row.intent, &digest, &head)\n            .await"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(filename, function, marker)
        boundary = self.boundaries["root_learning_completed_circuit_source"]
        self.assertEqual(boundary.receiver_type, "AgentdState")
        self.assertEqual(boundary.symbol, "AgentdState::require_circuit_learning_source")
        self.assertEqual(boundary.product_callers, (
            AGENT + "learning_iteration_delivery_runtime.rs",
            AGENT + "resident_learning_delivery.rs",
        ))
        self.assertEqual(boundary.caller_markers,
                         (".require_circuit_learning_source(request)",))
        paths = (boundary.definition_path, *boundary.product_callers)
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        PROOF._verify_boundary(ROOT, boundary, sources, ())
        extra = dict(sources)
        extra[AGENT + "unregistered_completed_source.rs"] = (
            "fn bypass(state: &AgentdState) { state.require_circuit_learning_source(request); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, boundary, extra, ())
        # The shared caller marker is only the method. These per-file guards
        # retain the complete actual receiver-call span despite rustfmt layout.
        for source_file, function, original_call in (
            ("learning_iteration_delivery_runtime.rs", "fn run(",
             "state.require_circuit_learning_source(request)"),
            ("resident_learning_delivery.rs", "fn prepare_enrollment(",
             "state\n            .require_circuit_learning_source(request)"),
            ("resident_learning_delivery.rs", "fn deliver(",
             "state\n                .require_circuit_learning_source(request)"),
        ):
            for changed_call in (
                original_call.replace("state", "different_owner", 1),
                original_call.replace("state", "state; different_owner", 1),
            ):
                with self.subTest(source=source_file, replacement=changed_call):
                    self.rejects(source_file, function, original_call, changed_call)
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
            ("fn original_attestations(", "stages\n                .receipt_attestation(snapshot, receipt, now / 1_000)\n                .await?"),
            ("fn original_attestations(", "let (_, fresh) = owner.read(cancellation).await?"),
            ("fn verify_non_model_attestations(", "signatures.len() + proposal_count != snapshot.receipts.len()"),
            ("fn verify_non_model_attestations(", "verifier\n            .verify(role, signature, &payload, now)"),
            ("fn verify_non_model_attestations(", "snapshot.training_no_update_v2().is_none()"),
            ("fn verify_non_model_attestations(", "verify_signed_actor_separation(&previous.1, current, now)"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(filename, function, marker)
        self.rejects("authority_host_learning_resident_wire.rs", "fn require_original_prefix(",
                     "!current.attestations.starts_with(&previous.attestations)")

    def test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof(self):
        workflow = (ROOT / ".github/workflows/hepta-daemon-learning-native.yml").read_text()
        match = re.search(r"parents = (\[[\s\S]*?\n          \])", workflow)
        self.assertIsNotNone(match)
        parents = ast.literal_eval(match.group(1))
        self.assertEqual(len(parents), len(set(parents)))
        self.assertTrue(set(ROOT_CASES).issubset(parents))
        self.assertTrue(set(ROOT_ISSUER_CASES).issubset(parents))
        self.assertTrue(set(ROOT_CUSTODY_CASES).issubset(parents))
        self.assertEqual(len(parents), 7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES) + len(ROOT_CUSTODY_CASES))
        roots = (ROOT / (AGENT + "authority_host_learning_resident_root_tests.rs")).read_text()
        evaluation = (ROOT / (AGENT + "authority_host_learning_resident_evaluation_tests.rs")).read_text()
        self.assertIn(
            '#[path = "authority_host_learning_resident_evaluation_tests.rs"]\nmod evaluation;',
            roots,
        )
        model = (ROOT / (AGENT + "authority_host_learning_resident_model_tests.rs")).read_text()
        self.assertIn(
            '#[path = "authority_host_learning_resident_model_tests.rs"]\nmod original_model;',
            roots,
        )
        retention = (ROOT / (AGENT + "authority_host_learning_resident_retention_auth_tests.rs")).read_text()
        self.assertIn(
            '#[path = "authority_host_learning_resident_retention_auth_tests.rs"]\nmod retention_auth;',
            roots,
        )
        provider = (ROOT / (AGENT + "authority_host_learning_resident_provider_transport_tests.rs")).read_text()
        lifecycle = (ROOT / (AGENT + "authority_host_learning_resident_provider_lifecycle_tests.rs")).read_text()
        self.assertIn(
            '#[path = "authority_host_learning_resident_provider_transport_tests.rs"]\nmod provider_transport;',
            roots,
        )
        self.assertIn(
            '#[path = "authority_host_learning_resident_provider_lifecycle_tests.rs"]\nmod lifecycle;',
            provider,
        )
        for name in ROOT_CASES:
            source = (
                lifecycle if "::provider_transport::lifecycle::" in name
                else provider if "::provider_transport::" in name
                else retention if "::retention_auth::" in name
                else model if "::original_model::" in name
                else evaluation if "::evaluation::" in name
                else roots
            )
            self.assertIn("fn " + name.rsplit("::", 1)[-1] + "(", source)
        self.assertEqual(
            roots.count('#[ignore = "explicit actual Root')
            + evaluation.count('#[ignore = "explicit actual Root')
            + model.count('#[ignore = "explicit actual Root')
            + retention.count('#[ignore = "explicit actual Root')
            + provider.count('#[ignore = "explicit actual Root')
            + lifecycle.count('#[ignore = "explicit actual Root'),
            len(ROOT_CASES),
        )
        task_support = (ROOT / (AGENT + "circuit_q24_task_test_support.rs")).read_text()
        custody_support = (ROOT / (AGENT + "neuron_generation_initial_root_custody_support_tests.rs")).read_text()
        custody = (ROOT / (AGENT + "neuron_generation_initial_root_custody_tests.rs")).read_text()
        cold = (ROOT / (AGENT + "neuron_generation_initial_root_cold_tests.rs")).read_text()
        self.assertIn(
            '#[path = "neuron_generation_initial_root_custody_support_tests.rs"]\nmod root_initial_custody;',
            task_support,
        )
        self.assertIn(
            '#[path = "neuron_generation_initial_root_custody_tests.rs"]\nmod tests;',
            custody_support,
        )
        self.assertIn(
            '#[path = "neuron_generation_initial_root_cold_tests.rs"]\nmod cold_tests;',
            custody_support,
        )
        self.assertEqual(len(ROOT_CUSTODY_CASES), len(set(ROOT_CUSTODY_CASES)))
        self.assertTrue(set(ROOT_CUSTODY_CASES).isdisjoint(ROOT_CASES + ROOT_ISSUER_CASES))
        for name in ROOT_CUSTODY_CASES:
            source = cold if "::cold_tests::" in name else custody
            self.assertIn("async fn " + name.rsplit("::", 1)[-1] + "(", source)
        self.assertEqual(
            custody.count('#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]')
            + cold.count('#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]'),
            len(ROOT_CUSTODY_CASES),
        )
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
