"""Run only source mutations, never the incomplete-view membership tests."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent
VIEW = ROOT / "validation-source"
SPECS = (
    (
        "selection_readback_final_v3_mutations",
        "test_original_selection_readback_source_closure.py",
        "OriginalSelectionReadbackClosureTests",
        (
            "test_original_peer_and_initial_context_are_verified_before_and_after_binding",
            "test_opaque_dataset_training_and_selection_cannot_be_detached_or_renewed",
            "test_wire_purpose_action_sequence_and_original_context_cannot_change",
            "test_service_checks_read_only_request_before_the_same_original_owner",
            "test_client_requires_fresh_complete_original_evidence_before_restoring_peer",
            "test_missing_pending_and_unknown_are_not_reusable_completed_selection",
            "test_service_keeps_bounded_original_transport_and_final_authentication",
            "test_read_only_adapters_cannot_gain_signing_execution_reconnection_or_new_owner",
        ),
        "test_exact_readback_edges_use_complete_rust_collection_and_reject_another_caller",
    ),
    (
        "artifact_channel_final_v3_mutations",
        "test_original_artifact_channel_source_closure.py",
        "OriginalArtifactChannelClosureTests",
        (
            "test_head_client_cannot_promote_readback_or_retain_a_signing_continuation",
            "test_head_peer_currentness_and_complete_signature_are_checked_after_io",
            "test_head_service_authenticates_and_dispatches_the_original_action_without_upgrade",
            "test_registry_read_uses_the_same_writer_then_fresh_authentication",
            "test_registry_channel_is_restored_only_after_current_subject_and_time_checks",
            "test_native_recovery_cannot_create_a_fresh_signing_owner",
            "test_sign_claim_is_owner_wide_before_key_take_and_durable_commit",
            "test_head_readback_cannot_sign_recover_or_merge_changed_observations",
            "test_wire_keeps_registry_read_only_and_exact_nonce_binding_and_failure_states",
            "test_head_config_keeps_registered_current_lease_key_and_fixed_expiry",
            "test_complete_head_signature_and_fixed_context_are_reverified",
            "test_durable_read_preserves_actual_files_complete_equality_and_fresh_validation",
            "test_keyless_adapters_cannot_gain_reconnect_signing_or_reconstruction_entrypoints",
        ),
        "test_exact_original_channel_membership_uses_all_rust_and_rejects_another_caller",
    ),
)
suite = unittest.TestSuite()
selected = []
not_run = []
for module_name, filename, class_name, methods, membership in SPECS:
    spec = importlib.util.spec_from_file_location(module_name, VIEW / "qa/b4-no-bypass" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    test_class = getattr(module, class_name)
    discovered = set(unittest.defaultTestLoader.getTestCaseNames(test_class))
    assert discovered == set(methods) | {membership}
    for name in methods:
        case = test_class(name)
        selected.append(case.id())
        suite.addTest(case)
    not_run.append(module_name + "." + class_name + "." + membership)
assert len(selected) == 21
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({
    "scope": "source mutations on nine exact Rust files; not full repository membership",
    "test_methods_run": result.testsRun,
    "selected_methods": selected,
    "membership_methods_not_run": not_run,
    "failures": [case.id() for case, _ in result.failures],
    "errors": [case.id() for case, _ in result.errors],
    "skipped": [case.id() for case, _ in result.skipped],
    "was_successful": result.wasSuccessful(),
    "full_source_gate": "not_run",
    "full_caller_gate": "not_run",
    "runtime_tests": "not_run",
    "authority_granted": False,
}, sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
