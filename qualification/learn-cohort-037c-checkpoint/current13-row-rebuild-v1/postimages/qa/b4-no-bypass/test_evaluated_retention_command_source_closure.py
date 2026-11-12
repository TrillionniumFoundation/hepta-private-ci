"""Close evaluated remote S/C receipts and their original command transports.

These are source-level adversarial gates. Real owner/native execution, original
Root/daemon delivery and ordinary qualification are separate requirements.
"""
from dataclasses import replace
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "evaluated_retention_command_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
# BEGIN GENERATED REVIEWED CONTRACTS
EXPECTED = {
    'learning_original_owner_command_channel': (AGENT + 'cell_q24_training_command.rs', AGENT + 'cell_q24_training_command_service.rs', AGENT + 'cell_q24_material_command.rs', AGENT + 'cell_q24_material_command_service.rs', AGENT + 'circuit_learning_read_capability.rs', AGENT + 'circuit_learning_read_service.rs', AGENT + 'circuit_selection_command.rs', AGENT + 'circuit_selection_command_service.rs', AGENT + 'cell_q24_training_bootstrap_service.rs', AGENT + 'cell_q24_training_command_connection.rs', AGENT + 'circuit_next_use_command.rs', AGENT + 'circuit_next_use_command_service.rs', AGENT + 'cell_q24_training_candidate_service.rs', AGENT + 'cell_q24_training_bootstrap_candidate.rs', AGENT + 'cell_q24_no_update_stage_inputs.rs', AGENT + 'circuit_learning_completion_readiness_service.rs', AGENT + 'authority_host_learning_resident_transport.rs', AGENT + 'neuron_cell_evaluation_host_command.rs', AGENT + 'neuron_cell_evaluation_host_service.rs', AGENT + 'circuit_retained_version_service.rs', AGENT + 'cell_q24_model_command_connection.rs', AGENT + 'cell_q24_model_command_service.rs', AGENT + 'neuron_cell_evaluation_model_material_connection.rs', AGENT + 'neuron_cell_evaluation_model_material_service.rs', AGENT + 'circuit_evaluated_next_use_command.rs', AGENT + 'circuit_evaluated_next_use_command_service.rs', AGENT + 'circuit_evaluated_selection_command.rs', AGENT + 'circuit_evaluated_selection_command_service.rs', AGENT + 'circuit_evaluated_selection_readback_owner.rs', AGENT + 'circuit_evaluated_selection_remote_readback.rs', AGENT + 'circuit_evaluated_version_readiness.rs', AGENT + 'circuit_evaluated_completion_readiness_service.rs',),
    'learning_original_owner_snapshot_encode': (AGENT + 'cell_q24_training_command_wire.rs', AGENT + 'cell_q24_material_command_wire.rs', AGENT + 'circuit_learning_read_wire.rs', AGENT + 'circuit_selection_command.rs', AGENT + 'circuit_selection_command_wire.rs', AGENT + 'circuit_next_use_command.rs', AGENT + 'circuit_next_use_command_wire.rs', AGENT + 'authority_host_learning_resident_profile.rs', AGENT + 'authority_host_learning_resident_store.rs', AGENT + 'authority_host_learning_resident_wire.rs', AGENT + 'neuron_cell_evaluation_host_contract.rs', AGENT + 'neuron_cell_evaluation_host_wire.rs', AGENT + 'circuit_retained_version_context.rs', AGENT + 'authority_host_learning_resident_model.rs', AGENT + 'cell_q24_model_command_context.rs', AGENT + 'neuron_cell_evaluation_model_material_export.rs', AGENT + 'circuit_evaluated_learning_read.rs', AGENT + 'circuit_evaluated_next_use_command_context.rs', AGENT + 'circuit_evaluated_next_use_command_wire.rs', AGENT + 'circuit_evaluated_selection_command_context.rs', AGENT + 'circuit_evaluated_selection_command_wire.rs', AGENT + 'circuit_evaluated_version_context.rs',),
    'learning_original_owner_snapshot_decode': (AGENT + 'cell_q24_training_command_wire.rs', AGENT + 'cell_q24_material_command_wire.rs', AGENT + 'circuit_selection_command_wire.rs', AGENT + 'circuit_next_use_command_wire.rs', AGENT + 'authority_host_learning_resident_store.rs', AGENT + 'authority_host_learning_resident_wire.rs', AGENT + 'neuron_cell_evaluation_host_wire.rs', AGENT + 'neuron_cell_evaluation_model_material_connection.rs', AGENT + 'neuron_cell_evaluation_model_material_verify.rs', AGENT + 'circuit_evaluated_next_use_command_wire.rs', AGENT + 'circuit_evaluated_selection_command_wire.rs'),
    'learning_evidence_original_owner_readback': (AGENT + 'learning_iteration_evaluation_evidence.rs', AGENT + 'learning_iteration_generation_evidence.rs', AGENT + 'neuron_cell_evaluation_receipt_owner.rs', AGENT + 'circuit_next_use_receipt_owner.rs', AGENT + 'circuit_selection_receipt_owner.rs', AGENT + 'cell_q24_training_source.rs', AGENT + 'circuit_model_selection_receipt_sources.rs', AGENT + 'neuron_cell_evaluation_qualification_sources.rs', AGENT + 'circuit_evaluated_version_commands.rs'),
    'learning_original_published_read_client_current': (AGENT + 'circuit_selection_receipt_owner.rs', AGENT + 'circuit_next_use_receipt_owner.rs', AGENT + 'circuit_evaluated_selection_remote.rs', AGENT + 'circuit_evaluated_next_use_remote.rs', AGENT + 'circuit_evaluated_version_commands.rs'),
    'learning_original_selector_command_owner_profile': (AGENT + 'circuit_selection_command_service.rs', AGENT + 'circuit_evaluated_selection_command_service.rs', AGENT + 'circuit_evaluated_selection_readback_owner.rs', AGENT + 'circuit_evaluated_selection_remote_readback.rs', AGENT + 'circuit_evaluated_version_commands.rs'),
    'learning_original_material_dataset_context_check': (AGENT + 'cell_q24_training_command_connection.rs', AGENT + 'cell_q24_training_candidate_readback.rs', AGENT + 'circuit_selection_command_stage_binding.rs', AGENT + 'circuit_next_use_command_stage_binding.rs', AGENT + 'circuit_learning_completion_readiness.rs', AGENT + 'cell_q24_no_update_stage_state.rs', AGENT + 'circuit_retained_version_context.rs', AGENT + 'cell_q24_model_command_context.rs', AGENT + 'circuit_evaluated_completion_readiness.rs', AGENT + 'circuit_evaluated_next_use_command_context.rs', AGENT + 'circuit_evaluated_selection_command_context.rs', AGENT + 'circuit_evaluated_version_context.rs', AGENT + 'circuit_evaluated_version_host.rs',),
    'learning_original_next_use_command_owner_profile': (AGENT + 'circuit_next_use_command_service.rs', AGENT + 'circuit_evaluated_next_use_command_service.rs', AGENT + 'circuit_evaluated_version_commands.rs'),
    'learning_evaluated_retention_context': (AGENT + 'circuit_evaluated_selection_command_context.rs', AGENT + 'circuit_evaluated_version_context.rs',),
    'learning_evaluated_retention_context_recover': (AGENT + 'circuit_evaluated_selection_command_context.rs', AGENT + 'circuit_evaluated_version_context.rs', AGENT + 'cell_q24_candidate_stage_retention_auth.rs',),
    'learning_original_evaluated_selection_readback_factory': (AGENT + 'circuit_evaluated_selection_receipt.rs',),
    'learning_original_evaluated_read_selection_context': (AGENT + 'circuit_retained_version_profile.rs',),
    'learning_original_evaluated_read_next_use_context': (AGENT + 'circuit_evaluated_completion_readiness.rs', AGENT + 'circuit_evaluated_version_readiness.rs'),
    'learning_original_evaluated_read_owner_create': (AGENT + 'circuit_evaluated_version_readiness.rs', AGENT + 'circuit_retained_version_state.rs'),
    'learning_original_evaluated_read_selection_binding': (AGENT + 'circuit_evaluated_selection_remote.rs', AGENT + 'circuit_evaluated_selection_command_service.rs', AGENT + 'circuit_evaluated_selection_remote_readback.rs', AGENT + 'circuit_evaluated_version_commands.rs'),
    'learning_original_evaluated_selection_remote_attest': (AGENT + 'circuit_evaluated_selection_command_service.rs',),
    'learning_original_evaluated_selection_remote_readback': (AGENT + 'circuit_evaluated_selection_command_evidence.rs', AGENT + 'circuit_evaluated_selection_command_service.rs', AGENT + 'circuit_evaluated_selection_remote_readback.rs'),
    'learning_original_evaluated_read_next_use_binding': (AGENT + 'circuit_evaluated_next_use_command_service.rs', AGENT + 'circuit_evaluated_next_use_remote.rs', AGENT + 'circuit_evaluated_version_commands.rs'),
    'learning_original_evaluated_selection_remote_readback_transfer': (),
    'learning_original_evaluated_selection_remote_readback_host_bind': (AGENT + 'circuit_evaluated_selection_remote.rs',),
    'learning_original_evaluated_selection_remote_readback_host_serve': (),
    'learning_original_evaluated_next_use_remote_attest': (AGENT + 'circuit_evaluated_next_use_command_service.rs',),
    'learning_original_evaluated_next_use_remote_readback': (AGENT + 'circuit_evaluated_next_use_command_evidence.rs', AGENT + 'circuit_evaluated_next_use_command_service.rs'),
    'learning_original_evaluated_selection_command_original_context': (AGENT + 'circuit_evaluated_selection_command_service.rs', AGENT + 'circuit_evaluated_version_commands.rs'),
    'learning_original_evaluated_selection_command_authenticate_response': (AGENT + 'circuit_evaluated_selection_command_wire.rs',),
    'learning_original_evaluated_selection_command_transfer': (AGENT + 'circuit_evaluated_version_commands.rs',),
    'learning_original_evaluated_selection_command_host_bind': (AGENT + 'circuit_evaluated_selection_receipt.rs',),
    'learning_original_evaluated_selection_command_host_serve': (),
    'learning_original_evaluated_selection_command_host_evidence_serve': (),
    'learning_original_evaluated_selection_command_create': (),
    'learning_original_evaluated_selection_command_recover': (),
    'learning_original_evaluated_selection_command_stage_bind': (AGENT + 'cell_q24_candidate_stage_retention_binding.rs',),
    'learning_original_evaluated_selection_command_stage_recover': (AGENT + 'cell_q24_candidate_stage_retention_binding.rs',),
    'learning_original_evaluated_selection_command_execute': (AGENT + 'cell_q24_candidate_stage_retention_selection.rs',),
    'learning_original_evaluated_selection_command_readback': (AGENT + 'cell_q24_candidate_stage_retention_next_use.rs', AGENT + 'cell_q24_candidate_stage_retention_selection.rs'),
    'learning_original_evaluated_selection_command_attestation': (),
    'learning_original_evaluated_next_use_command_original_context': (AGENT + 'circuit_evaluated_next_use_command_service.rs', AGENT + 'circuit_evaluated_version_commands.rs'),
    'learning_original_evaluated_next_use_command_authenticate_response': (AGENT + 'circuit_evaluated_next_use_command_wire.rs',),
    'learning_original_evaluated_next_use_command_transfer': (AGENT + 'circuit_evaluated_version_commands.rs',),
    'learning_original_evaluated_next_use_command_host_bind': (AGENT + 'circuit_evaluated_next_use_receipt.rs',),
    'learning_original_evaluated_next_use_command_host_serve': (),
    'learning_original_evaluated_next_use_command_host_evidence_serve': (),
    'learning_original_evaluated_next_use_command_create': (),
    'learning_original_evaluated_next_use_command_recover': (),
    'learning_original_evaluated_next_use_command_stage_bind': (AGENT + 'cell_q24_candidate_stage_retention_binding.rs',),
    'learning_original_evaluated_next_use_command_stage_recover': (AGENT + 'cell_q24_candidate_stage_retention_binding.rs',),
    'learning_original_evaluated_next_use_command_execute': (AGENT + 'cell_q24_candidate_stage_retention_next_use.rs',),
    'learning_original_evaluated_next_use_command_readback': (AGENT + 'cell_q24_candidate_stage_retention_next_use.rs',),
    'learning_original_evaluated_next_use_command_attestation': (),
}

GUARDED = {
    AGENT + 'circuit_evaluated_learning_read.rs': ('clone', 'for_original_selection', 'for_original_next_use', 'prefix', 'scope', 'mode', 'binding', 'decision', 'require_original_next_use', 'require_original_selection', 'from_original_evaluated_stream', 'require_original_evaluated_next_use', 'require_original_evaluated_selection', 'from_original_evaluated_owners'),
    AGENT + 'circuit_evaluated_next_use_command.rs': ('drop', 'original', 'execution_confirmed', 'from_original_stream', 'recover_from_original_stream', 'bind_original_stream', 'attest_completed_task', 'readback', 'receipt_attestation', 'exchange', 'require_clock', 'now'),
    AGENT + 'circuit_evaluated_next_use_command_context.rs': ('from_original', 'authenticate', 'initial', 'binding', 'bind_original_stage_channel', 'recover_original_stage_channel', 'bind_stage_context'),
    AGENT + 'circuit_evaluated_next_use_command_evidence.rs': ('serve_evidence_channel', 'evidence_response'),
    AGENT + 'circuit_evaluated_next_use_command_service.rs': ('from_original_receipt_owner', 'serve_commands', 'serve_evidence_readback', 'serve_command_channel', 'command_response', 'original_response', 'original_state'),
    AGENT + 'circuit_evaluated_next_use_command_wire.rs': ('new', 'require_context', 'from_request', 'require_request', 'encode_completed', 'decode_completed', 'authenticate_completed', 'same_original'),
    AGENT + 'circuit_evaluated_next_use_receipt.rs': ('clone', 'authenticate_original_command_response', 'attestation', 'original_selection', 'original_evaluated_command_selection', 'into_evaluated_command_owner', 'require_new', 'require_signed_separation', 'trainer', 'selector', 'evaluated_owners', 'location', 'observe', 'create_evaluated', 'recover_evaluated', 'from_evaluated_custody', 'attest_original_evaluated_completion', 'readback_evaluated_completion', 'completed_evaluated_next_use', 'authenticate_predecessors'),
    AGENT + 'circuit_evaluated_next_use_remote.rs': ('snapshot', 'trainer', 'selector', 'evaluated_owners', 'location', 'require_profile', 'observe', 'attest_original_evaluated_remote_completion', 'readback_evaluated_remote_completion'),
    AGENT + 'circuit_evaluated_selection_command.rs': ('drop', 'original', 'execution_confirmed', 'from_original_stream', 'recover_from_original_stream', 'bind_original_stream', 'execute_selection', 'readback', 'receipt_attestation', 'exchange', 'require_clock', 'now'),
    AGENT + 'circuit_evaluated_selection_command_context.rs': ('from_original', 'authenticate', 'initial', 'binding', 'bind_original_stage_channel', 'recover_original_stage_channel', 'bind_stage_context'),
    AGENT + 'circuit_evaluated_selection_command_evidence.rs': ('serve_evidence_channel', 'evidence_response'),
    AGENT + 'circuit_evaluated_selection_command_service.rs': ('from_original_receipt_owner', 'serve_commands', 'serve_evidence_readback', 'serve_command_channel', 'command_response', 'original_response', 'original_state'),
    AGENT + 'circuit_evaluated_selection_command_wire.rs': ('new', 'require_context', 'from_request', 'require_request', 'encode_completed', 'decode_completed', 'authenticate_completed', 'same_original'),
    AGENT + 'circuit_evaluated_selection_readback_binding.rs': ('original_context', 'from_original_pins', 'before_read', 'after_read'),
    AGENT + 'circuit_evaluated_selection_readback_owner.rs': ('from_original_receipt_owner', 'serve_readback', 'serve_channel', 'evidence_response', 'now'),
    AGENT + 'circuit_evaluated_selection_receipt.rs': ('clone', 'authenticate_original_command_response', 'receipt', 'attestation', 'original_context', 'into_original_receipt_readback', 'original_receipt_binding', 'original_receipt_predecessors', 'evidence_domain', 'require_new', 'require_signed_separation', 'trainer', 'evaluated_owners', 'location', 'observe', 'create_evaluated', 'recover_evaluated', 'from_evaluated_custody', 'attest_original_evaluated_selection', 'readback_evaluated_selection', 'completed_evaluated_selection', 'authenticate_evaluated_training', 'original_evaluated_command_context', 'into_evaluated_command_owner'),
    AGENT + 'circuit_evaluated_selection_remote.rs': ('snapshot', 'trainer', 'evaluated_owners', 'location', 'require_profile', 'observe', 'attest_original_evaluated_remote_selection', 'readback_evaluated_remote_selection', 'into_evaluated_remote_readback_owner'),
    AGENT + 'circuit_evaluated_selection_remote_readback.rs': ('from_original_receipt_owner', 'serve_readback', 'serve_channel', 'evidence_response'),
    AGENT + 'circuit_next_use_receipt_owner.rs': ('evaluated_owners', 'require_profile', 'read_local_next_use', 'read_remote_next_use', 'create', 'recover', 'into_command_owner', 'original_command_profile', 'attest_original_completion', 'attest_original_remote_completion', 'attest_source', 'readback', 'readback_remote', 'readback_source', 'prepare', 'predecessors', 'finish_original_readback', 'decode_completed', 'authenticate_completed'),
    AGENT + 'circuit_selection_receipt_owner.rs': ('evaluated_owners', 'require_profile', 'read_local_selection', 'read_remote_selection', 'original_command_profile', 'create', 'recover', 'attest_original_selection', 'attest_original_remote_selection', 'attest_source', 'readback', 'readback_remote', 'readback_source', 'prepare', 'training_evidence', 'finish_original_readback', 'decode_completed', 'authenticate_completed', 'into_command_owner', 'validate_config', 'training_receipt', 'authenticate_training', 'receipt', 'sign_original', 'signature_expiry', 'require_new_attestation', 'evidence_id', 'now'),
}

NEW_PRIVATE_FILES = (AGENT + 'circuit_evaluated_next_use_command.rs', AGENT + 'circuit_evaluated_next_use_command_context.rs', AGENT + 'circuit_evaluated_next_use_command_evidence.rs', AGENT + 'circuit_evaluated_next_use_command_service.rs', AGENT + 'circuit_evaluated_next_use_command_wire.rs', AGENT + 'circuit_evaluated_next_use_remote.rs', AGENT + 'circuit_evaluated_selection_command.rs', AGENT + 'circuit_evaluated_selection_command_context.rs', AGENT + 'circuit_evaluated_selection_command_evidence.rs', AGENT + 'circuit_evaluated_selection_command_service.rs', AGENT + 'circuit_evaluated_selection_command_wire.rs', AGENT + 'circuit_evaluated_selection_readback_binding.rs', AGENT + 'circuit_evaluated_selection_remote_readback.rs')

LEGACY_FORBIDDEN = {
    AGENT + 'circuit_evaluated_learning_read.rs': ('SigningKey', 'LearningEvidenceTrustV1', 'LearningEvidenceVerifierV1::new', 'File::open', 'File::create', 'UnixStream::connect', 'Deserialize', 'Deref', 'into_inner', 'with_root_learning_stage_owners(', 'LearningIterationStageOwnerPortsV1 for', 'fit_or_readback(', 'evaluate_or_readback(', 'qualify_and_persist(', '.compare_and_swap(', '.publish(', '.commit_once(', '.claim(', 'permit_all', 'if false', 'pub enum OriginalCut', 'pub(crate) enum OriginalCut', 'pub(super) enum OriginalCut', 'pub fn from_snapshot', 'pub fn from_bytes', 'pub fn from_observation'),
    AGENT + 'circuit_evaluated_next_use_receipt.rs': ('pub selection: LearningIterationSnapshotV1', 'pub attestation: SignedLearningEvidenceV1', 'pub fn from_snapshot', 'pub fn original_selection', 'pub(crate) fn create_evaluated', 'SigningKey::generate', 'SigningKey::from_bytes', 'LearningEvidenceVerifierV1::new', 'LearningEvidenceTrustV1', 'UnixStream::connect', 'File::open', 'Profile::TrainingNoUpdate', 'TrainingNoUpdateV2', 'unwrap_or', 'permit_all', 'if false', 'LearningIterationStageOwnerPortsV1 for', 'RootResidentLearningEffectGateV3', 'with_root_learning_stage_owners(', "pub selector: &'a mut", "pub selector: &'a OriginalCircuitSelectionReceiptOwnerV1", 'pub selector: OriginalCircuitSelectionReceiptOwnerV1'),
    AGENT + 'circuit_evaluated_selection_readback_owner.rs': ('SigningKey', 'File::open', 'UnixStream::connect', 'LearningEvidenceVerifierV1::new', 'LearningEvidenceTrustV1', 'attest_original_evaluated_selection', 'attest_source(', 'commit_once(', 'sign_original(', 'execute(', 'serve_execute(', 'create_evaluated(', 'recover_evaluated(', 'RootResidentLearningEffectGateV3', 'with_root_learning_stage_owners(', 'LearningIterationStageOwnerPortsV1 for', 'unwrap_or', 'permit_all', 'if false', 'pub owner:', 'pub cell:', 'pub trainer:', 'pub evaluator:', 'pub selection:', 'pub initial_head:', 'pub binding:', 'pub connections:', 'pub fn from_original_receipt_owner(', 'pub fn evidence_response(', 'pub(crate) fn evidence_response('),
    AGENT + 'circuit_evaluated_selection_receipt.rs': ('pub enum Profile', 'pub(crate) enum Profile', 'SigningKey::generate', 'SigningKey::from_bytes', 'LearningEvidenceVerifierV1::new', 'LearningEvidenceTrustV1', 'File::open', 'File::create', 'UnixStream::connect', 'with_root_learning_stage_owners(', 'LearningIterationStageOwnerPortsV1 for', 'RootResidentLearningEffectGateV3', 'Deserialize', 'impl Default', 'unwrap_or', 'permit_all', 'if false', 'pub fn from_snapshot(', 'pub fn from_checkpoint(', 'pub fn original_context(', 'pub fn into_original_context(', 'pub fn selector(', 'pub fn selector_mut(', 'pub fn owner(', 'OriginalCircuitNextUseReceiptOwnerV1', 'OriginalCircuitNextUseCommandOwnerV1', '.execute_training(', '.execute_evaluation(', '.publish(', '.compare_and_swap(', 'pub fn original_receipt_predecessors(', 'pub fn original_receipt_binding(', 'pub fn into_original_receipt_readback('),
    AGENT + 'circuit_evaluated_selection_remote.rs': ('SigningKey', 'LearningEvidenceTrustV1', 'LearningEvidenceVerifierV1::new', 'File::open', 'File::create', 'UnixStream::connect', 'Deserialize', 'Deref', 'into_inner', 'with_root_learning_stage_owners(', 'LearningIterationStageOwnerPortsV1 for', 'fit_or_readback(', 'evaluate_or_readback(', 'qualify_and_persist(', '.compare_and_swap(', '.publish(', '.commit_once(', '.claim(', 'permit_all', 'if false', "&'a mut", 'LearningIterationEvidenceClientV1::readback(', 'ObservationLocation::RemoteOwner', 'ObservationLocation::LocalOwner', 'CommandOrigin::FreshCreate => self.readback_source', 'CommandOrigin::Recovered => self.attest_source', 'pub trait SelectionSources'),
    AGENT + 'circuit_next_use_receipt_owner.rs': ('pub trait NextUseSources', 'pub(crate) trait NextUseSources', 'dyn NextUseSources', 'SigningKey::generate', 'SigningKey::from_bytes', 'LearningEvidenceVerifierV1::new', 'LearningEvidenceTrustV1', 'File::open', 'UnixStream::connect', 'with_root_learning_stage_owners(', 'LearningIterationStageOwnerPortsV1 for', 'fit_or_readback(', 'evaluate_or_readback(', 'qualify_and_persist(', 'unwrap_or', 'permit_all', 'if false', 'pub fn sign_original', 'pub(crate) fn sign_original', 'pub fn receipt(', 'pub(crate) fn receipt(', 'pub journal:', 'pub key:', 'pub command_origin:', 'pub enum CommandOrigin', 'pub enum ObservationLocation', 'pub(crate) enum ObservationLocation', 'pub completion_fenced:', 'pub(crate) completion_fenced:', 'self.completion_fenced = false', 'pub profile:', 'pub(crate) profile:', 'Profile::Evaluated(())'),
    AGENT + 'circuit_selection_receipt_owner.rs': ('pub command_origin:', 'pub fn original_command_profile(', 'pub trait SelectionSources', 'pub(crate) trait SelectionSources', 'dyn SelectionSources', 'SigningKey::generate', 'SigningKey::from_bytes', 'LearningEvidenceVerifierV1::new', 'LearningEvidenceTrustV1', 'File::open', 'UnixStream::connect', 'with_root_learning_stage_owners(', 'LearningIterationStageOwnerPortsV1 for', 'fit_or_readback(', 'evaluate_or_readback(', 'qualify_and_persist(', 'unwrap_or', 'permit_all', 'if false', 'pub fn sign_original', 'pub(crate) fn sign_original', 'pub fn receipt(', 'pub(crate) fn receipt(', 'pub journal:', 'pub key:', 'pub enum ObservationLocation', 'pub(crate) enum ObservationLocation', 'pub completion_fenced:', 'pub(crate) completion_fenced:', 'self.completion_fenced = false', 'pub profile:', 'pub(crate) profile:'),
    AGENT + 'learning_iteration_evidence_client.rs': ('SigningKey', 'UnixStream::connect', 'File::open', 'initialize_host_authority', 'create_protected', 'AllowVerifier', 'permit_all'),
}

MOUNTS = ((AGENT + 'circuit_evaluated_next_use_receipt.rs', 'remote', 'circuit_evaluated_next_use_remote.rs'), (AGENT + 'circuit_evaluated_selection_readback_owner.rs', 'binding', 'circuit_evaluated_selection_readback_binding.rs'), (AGENT + 'circuit_evaluated_selection_readback_owner.rs', 'remote', 'circuit_evaluated_selection_remote_readback.rs'), (AGENT + 'circuit_evaluated_selection_readback_owner.rs', 'command', 'circuit_evaluated_selection_command.rs'), (AGENT + 'learning_iteration_evidence_client.rs', 'evaluated_next_use_command', 'circuit_evaluated_next_use_command.rs'), (AGENT + 'circuit_evaluated_selection_command.rs', 'context', 'circuit_evaluated_selection_command_context.rs'), (AGENT + 'circuit_evaluated_selection_command.rs', 'wire', 'circuit_evaluated_selection_command_wire.rs'), (AGENT + 'circuit_evaluated_selection_command.rs', 'serving', 'circuit_evaluated_selection_command_service.rs'), (AGENT + 'circuit_evaluated_next_use_command.rs', 'context', 'circuit_evaluated_next_use_command_context.rs'), (AGENT + 'circuit_evaluated_next_use_command.rs', 'wire', 'circuit_evaluated_next_use_command_wire.rs'), (AGENT + 'circuit_evaluated_next_use_command.rs', 'serving', 'circuit_evaluated_next_use_command_service.rs'), (AGENT + 'circuit_evaluated_selection_command_service.rs', 'evidence', 'circuit_evaluated_selection_command_evidence.rs'), (AGENT + 'circuit_evaluated_next_use_command_service.rs', 'evidence', 'circuit_evaluated_next_use_command_evidence.rs'))

NATIVE_CASES = {
    AGENT + 'circuit_evaluated_selection_command_tests.rs': ('evaluated_selection_command_once_reads_originals_and_readonly_evidence', 'evaluated_selection_command_lost_ack_recovers_only_exact_readback', 'evaluated_selection_command_recovered_missing_cannot_claim', 'evaluated_selection_command_never_reuses_s_after_training_withdrawal', 'evaluated_selection_command_never_reuses_s_after_evaluation_withdrawal'),
    AGENT + 'circuit_evaluated_next_use_command_tests.rs': ('evaluated_next_use_command_once_reads_originals_and_readonly_evidence', 'evaluated_next_use_command_lost_ack_recovers_only_exact_readback', 'evaluated_next_use_command_recovered_missing_cannot_claim'),
    AGENT + 'circuit_evaluated_next_use_remote_tests.rs': ('evaluated_remote_c_reads_original_s_and_recovers_exact_six_cut', 'evaluated_remote_c_cold_missing_reads_originals_without_claiming', 'evaluated_remote_c_fences_after_last_s_reply_withdraws_actual_source'),
}
# END GENERATED REVIEWED CONTRACTS

S_MAIN = AGENT + "circuit_evaluated_selection_command.rs"
S_CTX = AGENT + "circuit_evaluated_selection_command_context.rs"
S_WIRE = AGENT + "circuit_evaluated_selection_command_wire.rs"
S_HOST = AGENT + "circuit_evaluated_selection_command_service.rs"
S_EVIDENCE = AGENT + "circuit_evaluated_selection_command_evidence.rs"
C_MAIN = AGENT + "circuit_evaluated_next_use_command.rs"
C_CTX = AGENT + "circuit_evaluated_next_use_command_context.rs"
C_WIRE = AGENT + "circuit_evaluated_next_use_command_wire.rs"
C_HOST = AGENT + "circuit_evaluated_next_use_command_service.rs"
C_EVIDENCE = AGENT + "circuit_evaluated_next_use_command_evidence.rs"
S_OPAQUE = AGENT + "circuit_evaluated_selection_receipt.rs"
C_OPAQUE = AGENT + "circuit_evaluated_next_use_receipt.rs"
S_ENGINE = AGENT + "circuit_selection_receipt_owner.rs"
C_ENGINE = AGENT + "circuit_next_use_receipt_owner.rs"
S_REMOTE = AGENT + "circuit_evaluated_selection_remote.rs"
C_REMOTE = AGENT + "circuit_evaluated_next_use_remote.rs"
S_READBACK = AGENT + "circuit_evaluated_selection_readback_owner.rs"
S_REMOTE_HOST = AGENT + "circuit_evaluated_selection_remote_readback.rs"
S_BINDING = AGENT + "circuit_evaluated_selection_readback_binding.rs"
READ_CUT = AGENT + "circuit_evaluated_learning_read.rs"

DOMAINS = {
    S_CTX: [("binding", r"Ok\(Digest32::of_parts\(&\[", 'b"hepta.agentd.original-circuit-evaluated-selection-command.v1\\0"')],
    C_CTX: [("binding", r"Ok\(Digest32::of_parts\(&\[", 'b"hepta.agentd.original-circuit-evaluated-next-use-command.v1\\0"')],
    S_WIRE: [(None, r"pub\(super\) const OPERATION: &str =", '"runtime.learning.original-circuit.evaluated-selection.command.v1"')],
    C_WIRE: [(None, r"pub\(super\) const OPERATION: &str =", '"runtime.learning.original-circuit.evaluated-next-use.command.v1"')],
}


def code_of(source):
    return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))


def span(source, name):
    code = code_of(source)
    marker = "fn " + name + "("
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("unique actual guarded function: " + marker)
    start = code.index(marker)
    end = PROOF._rust_item_end(code, start)
    if end is None or code[end] != "}":
        raise PROOF.VerificationFailure("complete actual function: " + marker)
    return code, start, end + 1


def require_domains(path, source):
    code = code_of(source)
    for function, pattern, literal in DOMAINS.get(path, ()):
        start, end = 0, len(code)
        if function:
            _, start, end = span(source, function)
        matches = list(re.finditer(pattern, code[start:end]))
        if len(matches) != 1:
            raise PROOF.VerificationFailure("one actual command domain expression")
        offset = start + matches[0].end()
        found = re.match(r'\s*(b?"(?:[^"\\]|\\.)*")', source[offset:end])
        if found is None or found[1] != literal:
            raise PROOF.VerificationFailure("different actual command purpose/domain")
        if function is None:
            prefix = code[:start + matches[0].start()]
            if prefix.count("{") != prefix.count("}"):
                raise PROOF.VerificationFailure("operation must be a module constant")


class EvaluatedRetentionCommandSourceClosureTests(unittest.TestCase):
    attacks = 0

    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        cls.protected = {row["path"]: row for row in cls.manifest["protected_file"]}
        cls.sources = {path: (ROOT / path).read_text() for path in GUARDED}

    @classmethod
    def tearDownClass(cls):
        print("evaluated command source mutations rejected:", cls.attacks)

    def verifies(self, path, source, domains=True):
        self.assertIn(path, self.protected)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": [self.protected[path]]})
        if domains:
            require_domains(path, source)

    def rejects_source(self, path, original, changed):
        self.assertNotEqual(original, changed)
        self.verifies(path, original)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)
        type(self).attacks += 1

    def rejects(self, path, function, marker, replacement=""):
        original = self.sources[path]
        code, start, end = span(original, function)
        pattern = r"\s*".join(re.escape(token) for token in re.findall(r"\w+|[^\w\s]", marker))
        found = re.search(pattern, code[start:end])
        self.assertIsNotNone(found, (path, function, marker))
        offset = start + found.start()
        actual = original[offset:start + found.end()]
        self.rejects_source(path, original, original[:offset] + replacement + original[offset + len(actual):])

    def test_inventory_and_exact_real_callers_reject_additional_typed_callers(self):
        PROOF._verify_privileged_inventory(self.manifest, tuple(self.boundaries.values()))
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))
        paths = {path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: code_of((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                changed = dict(sources)
                changed[AGENT + "unregistered_evaluated_command.rs"] = (
                    "fn bypass(owner: &" + row.receiver_type + ") { owner." + method + "(); }"
                    if row.receiver_type else "fn bypass() { " + row.symbol + "(); }"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())
                type(self).attacks += 1
                if expected:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), sources, ())
                    type(self).attacks += 1

    def test_legacy_forbidden_markers_and_all_actual_functions_stay_guarded(self):
        for path, expected in LEGACY_FORBIDDEN.items():
            self.assertTrue(set(expected).issubset(self.protected[path]["forbidden"]), path)
        for path, functions in GUARDED.items():
            self.verifies(path, self.sources[path])
            guarded = {row["function"][3:-1] for row in self.protected[path].get("required_function_order", ())}
            self.assertTrue(set(functions).issubset(guarded), path)
            if path in NEW_PRIVATE_FILES:
                actual = set(re.findall(r"\bfn ([A-Za-z_]\w*)\(", code_of(self.sources[path])))
                self.assertEqual(actual, guarded, path)

    def test_every_guarded_function_rejects_an_uninvoked_closure_copy(self):
        for path, functions in GUARDED.items():
            if path.endswith("learning_iteration_evidence_client.rs"):
                continue
            for function in functions:
                with self.subTest(path=path, function=function):
                    original = self.sources[path]
                    code, start, end = span(original, function)
                    opening = code.index("{", start, end)
                    changed = (
                        original[:opening + 1] + "\nlet _never_called = || async {"
                        + original[opening + 1:end - 1] + "\n}; panic!();\n"
                        + original[end - 1:]
                    )
                    self.rejects_source(path, original, changed)

    def test_live_checks_cannot_be_hidden_after_an_early_cached_result(self):
        for path in (S_MAIN, C_MAIN):
            original = self.sources[path]
            code, start, end = span(original, "exchange")
            opening = code.index("{", start, end)
            early = (
                "\nif let Some(cached) = self.retained.lock().unwrap().as_ref() {"
                "\nreturn Ok(cached.original().clone());\n}\n"
            )
            self.rejects_source(path, original, original[:opening + 1] + early + original[opening + 1:])
        for path, function in ((S_BINDING, "before_read"), (S_BINDING, "after_read"), (S_HOST, "command_response"), (C_HOST, "command_response")):
            original = self.sources[path]
            code, start, end = span(original, function)
            opening = code.index("{", start, end)
            changed = original[:opening + 1] + "\nreturn Err(Error::Unavailable);\n" + original[opening + 1:]
            self.rejects_source(path, original, changed)

    def test_opaque_custody_fields_and_private_bool_helpers_cannot_be_exposed(self):
        for path in (S_MAIN, C_MAIN, S_CTX, C_CTX, S_HOST, C_HOST, S_BINDING, S_REMOTE_HOST, S_READBACK, S_OPAQUE, C_OPAQUE):
            original = self.sources[path]
            code = code_of(original)
            for match in list(re.finditer(r"(?m)^(\s{4})([a-z_]\w*): ([^\n]+),$", code)):
                # Private named fields only. Public config/source inputs stay
                # immutable under the separate exact type/body guards.
                name = match[2]
                if not any(word in name for word in ("owner", "context", "selection", "original", "channel", "retained", "trainer", "evaluator", "binding", "head", "live", "selector", "connection", "execution", "attestation", "snapshot", "receipt")):
                    continue
                for visibility in ("pub ", "pub(crate) ", "pub(super) "):
                    changed = original[:match.start(2)] + visibility + original[match.start(2):]
                    self.rejects_source(path, original, changed)
        for path, function in ((S_MAIN, "bind_original_stream"), (C_MAIN, "bind_original_stream"), (S_CTX, "bind_stage_context"), (C_CTX, "bind_stage_context"), (S_HOST, "original_response"), (C_HOST, "original_response")):
            original = self.sources[path]
            code, start, _ = span(original, function)
            for visibility in ("pub ", "pub(crate) ", "pub(super) "):
                self.rejects_source(path, original, original[:start] + visibility + original[start:])

    def test_domains_are_checked_at_actual_expressions_and_comments_cannot_replace_them(self):
        for path, definitions in DOMAINS.items():
            original = self.sources[path]
            self.verifies(path, original)
            for _, _, literal in definitions:
                # Same length preserves every masked literal position. Only
                # the actual domain check can detect this mutation.
                point = literal.index('"') + 1
                wrong = literal[:point] + "x" + literal[point + 1:]
                changed = original.replace(literal, wrong, 1) + "\n// " + literal + "\n"
                self.assertNotEqual(original, changed)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, changed)
                type(self).attacks += 1

    def test_fresh_and_cold_constructors_bind_actual_predecessors_and_never_rebrand(self):
        for path in (S_MAIN, C_MAIN):
            self.rejects(path, "recover_from_original_stream", ".into_original_receipt_readback()", "")
            self.rejects(path, "from_original_stream", ".require_new_original_receipt(now()?)?", ".require_new_original_receipt(0)?")
            for function in ("bind_original_stream", "exchange"):
                self.rejects(path, function, "require_clock(started_at, current)?;")
            self.rejects(path, "bind_original_stream", "retained.map(Retained::Readback)", "retained.map(Retained::Executed)")
        for path in (S_CTX, C_CTX):
            if path == S_CTX:
                self.rejects(path, "recover_original_stage_channel", "OriginalCircuitEvaluatedRetentionContextV1::recover_original_evaluation", "OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation")
            else:
                self.rejects(path, "recover_original_stage_channel", ".into_original_receipt_readback()", "")
            for marker in (
                "peer.check_peer_lifetime()?",
                "OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context",
                "require_clock(started_at, fresh)?",
                "if !execution_requested",
            ):
                self.rejects(path, "bind_stage_context", marker, "false" if marker == "if !execution_requested" else "")
        for path in (S_HOST, C_HOST):
            self.rejects(path, "from_original_receipt_owner", "AtomicBool::new(readback_only)", "AtomicBool::new(false)")
            self.rejects(path, "command_response", "self.execution_requested.swap(true, Ordering::AcqRel)", "self.execution_requested.swap(false, Ordering::AcqRel)")

    def test_only_this_clients_complete_execute_ack_retains_fresh_origin(self):
        for path in (S_MAIN, C_MAIN):
            for marker, replacement in (
                ("action == wire::Action::Execute || retained.as_ref().is_some_and(Retained::execution_confirmed)", "true"),
                ("Retained::Readback(original.clone())", "Retained::Executed(original.clone())"),
                ("context.into_original_receipt_readback()", "context"),
                ("wire::same_original(saved.original(), &original)", "true"),
                ("channel.peer.check_peer_lifetime()?", ""),
            ):
                self.rejects(path, "exchange", marker, replacement)
            self.rejects(path, "execution_confirmed", "matches!(self, Self::Executed(_))", "true")

    def test_complete_five_and_six_cut_signatures_are_mandatory(self):
        for path, count in ((S_OPAQUE, "5"), (C_OPAQUE, "6")):
            self.rejects(path, "authenticate_original_command_response", "snapshot.receipts.len() != " + count, "false")
            for marker in (
                "snapshot.request != prefix.request",
                "snapshot.owners != prefix.owners",
                "snapshot.receipts.starts_with(&prefix.receipts)",
            ):
                self.rejects(path, "authenticate_original_command_response", marker, "true" if "!=" in marker else "")
        self.rejects(S_OPAQUE, "authenticate_original_command_response", "original.original_receipt_predecessors(current)?;")
        for path, function, scope in ((S_OPAQUE, "original_receipt_predecessors", "&self.snapshot"), (C_OPAQUE, "authenticate_original_command_response", "&snapshot")):
            self.rejects(path, function, "scope.validate_snapshot(" + scope + ")?;")
            self.rejects(path, function, "verify_signed_actor_separation(")
        for path, marker, replacement in (
            (S_CTX, "self.original.receipt_context_binding().as_array()", "self.original.snapshot().head_digest.as_array()"),
            (C_CTX, "self.selection.original_receipt_binding().as_array()", "self.selection.snapshot().head_digest.as_array()"),
        ):
            self.rejects(path, "binding", marker, replacement)
        for marker in ("state_partition.run_id != prefix.request.source_run_id", "!checkpoint_digest.is_zero()", "!committed_step_receipt.is_zero()", "!task_owner_publication.is_zero()", "original.next_stage().is_some()", "original.next_task_bundle() != Some(&prefix.request.selected_bundle)"):
            self.rejects(C_OPAQUE, "authenticate_original_command_response", marker, "false")

    def test_fixed_wire_requests_echo_every_context_field_and_reject_extra_fields(self):
        for path, head in ((S_WIRE, "evaluation_head"), (C_WIRE, "selection_head")):
            for field in ("schema", "operation", "request_id", "binding", "operation_id", head, "scope_binding", "actor_id"):
                self.rejects(path, "require_context", "self." + field + " != " + ("request_id" if field == "request_id" else "actual." + field), "false")
                self.rejects(path, "require_request", "self." + field + " != request." + field, "false")
            self.rejects(path, "require_request", "self.action != request.action", "false")
            self.rejects(path, "decode_completed", "snapshot.len() > 10_924", "snapshot.len() > 100_000")
            self.rejects(path, "decode_completed", "STANDARD_NO_PAD.encode(&bytes) != snapshot", "false")
            self.rejects(path, "authenticate_completed", "context.authenticate(current)?;")
            original = self.sources[path]
            for marker in ("#[serde(deny_unknown_fields)]", '#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]'):
                changed = original.replace(marker, "", 1) + "\n// " + marker + "\n"
                self.rejects_source(path, original, changed)

    def test_unknown_outcomes_and_queued_cancellation_permanently_consume_the_channel(self):
        for path in (S_MAIN, C_MAIN):
            for marker, replacement in (
                ("slot.take().ok_or(Error::Unavailable)?", "slot.take().ok_or(Error::Busy)?"),
                ("channel.execution_requested = true;", "channel.execution_requested = false;"),
                ("wire::CommandResult::Uncertain => return Err(Error::CommitUncertain)", "wire::CommandResult::Uncertain => Err(Error::Missing)"),
                ("wire::CommandResult::Unavailable => return Err(Error::Unavailable)", "wire::CommandResult::Unavailable => Err(Error::Unavailable)"),
                ("abandoned.load(Ordering::Acquire)", "false"),
                ("drop(queued_execute_fence);", ""),
                ("response.require_request(&request)?;", ""),
            ):
                self.rejects(path, "exchange", marker, replacement)
            self.rejects(path, "drop", "self.abandoned.store(true, Ordering::Release)", "self.abandoned.store(false, Ordering::Release)")
            original = self.sources[path]
            code, start, end = span(original, "exchange")
            point = original.index("self.context.authenticate(started_at)?;", start, end)
            # Merely preserving the guarded suffix after returning a cache is
            # already tested; suppressing channel consumption is separately pinned.
            self.assertGreater(point, original.index("slot.take()", start, end))

    def test_original_request_session_and_deadline_limits_are_not_extended(self):
        for path in (S_MAIN, C_MAIN):
            self.rejects(path, "exchange", "(1..=128).contains(&request_id)", "(1..=129).contains(&request_id)")
            self.rejects(path, "exchange", "request_id.checked_add(1)", "request_id.checked_add(0)")
        for path in (S_HOST, C_HOST):
            self.rejects(path, "from_original_receipt_owner", "Semaphore::new(4)", "Semaphore::new(5)")
            self.rejects(path, "serve_command_channel", "1..=128_u64", "1..=129_u64")
            self.rejects(path, "serve_evidence_readback", "Duration::from_millis(500)", "Duration::from_millis(501)")
            self.rejects(path, "serve_commands", "Arc::clone(&self.connections)", "Arc::new(Semaphore::new(4))")
        for path in (S_EVIDENCE, C_EVIDENCE):
            self.rejects(path, "serve_evidence_channel", "1..=128_u64", "1..=129_u64")

    def test_readonly_s_binding_keeps_full_signatures_and_real_pre_post_reads(self):
        for marker in ("config.decision != *selection.original_context().snapshot()", "config.training_evidence != training", "config.signer.principal.principal_id != selection.receipt().actor_id"):
            self.rejects(S_BINDING, "original_context", marker, "false")
        for marker in ("request.binding != self.initial_head.to_string()", "request.predecessor != self.selection.receipt().predecessor.to_string()", "request.receipt_digest != self.selection.attestation().payload_digest.to_string()", "snapshot_head.is_zero()"):
            self.rejects(S_BINDING, "before_read", marker, "false")
        for marker in ("original.snapshot() != self.selection.snapshot()", "original.receipt() != self.selection.receipt()", "original.attestation() != self.selection.attestation()", "original.original_receipt_binding() != self.binding", "current < started_at"):
            self.rejects(S_BINDING, "after_read", marker, "false")
        for path in (S_READBACK, S_REMOTE_HOST, S_EVIDENCE):
            for marker in ("before_read(bytes, request_id)?", "after_read(request, started_at, original)"):
                self.rejects(path, "evidence_response", marker)
        self.rejects(S_REMOTE_HOST, "evidence_response", "readback_evaluated_remote_selection", "attest_original_evaluated_remote_selection")
        self.rejects(S_EVIDENCE, "evidence_response", "readback_evaluated_remote_selection", "attest_original_evaluated_remote_selection")
        self.rejects(C_EVIDENCE, "evidence_response", "readback_evaluated_remote_completion", "attest_original_evaluated_remote_completion")

    def test_actual_t_b_s_source_cell_and_journal_reads_cannot_be_replaced_by_pins(self):
        for path, method in ((S_REMOTE, "require_original_evaluated_selection"), (C_REMOTE, "require_original_evaluated_next_use")):
            self.rejects(path, "require_profile", method + "(")
            self.rejects(path, "observe", "OriginalCircuitLearningReadClientV1::read_current(self.live).await?")
            self.rejects(path, "location", "ObservationLocation::EvaluatedOwner", "ObservationLocation::RemoteOwner")
            self.rejects(path, "evaluated_owners", "Some((self.trainer, self.evaluator))", "None")
        for path in (S_ENGINE, C_ENGINE):
            self.rejects(path, "finish_original_readback", "self.prepare(source).await?", "*observed")
            self.rejects(path, "finish_original_readback", "self.journal.read(&self.saved)?", "bytes.to_vec()")
            self.rejects(path, "readback_source", "self.journal.read(&self.saved)?", "Vec::new()")
        self.rejects(C_ENGINE, "finish_original_readback", "self.predecessors(source).await?", "[self.config.training_evidence.clone(), self.config.selection_evidence.clone()]")
        self.rejects(C_ENGINE, "prepare", "source.require_profile(&self.profile)?;")
        for path in (S_HOST, C_HOST):
            self.rejects(path, "original_response", "let mut owner = match self.owner.try_lock()")
            self.rejects(path, "original_response", "wire::same_original(saved, &original)", "true")
        for path in (S_EVIDENCE, C_EVIDENCE):
            self.rejects(path, "evidence_response", ".ok_or(Error::Missing)?")

    def test_recovery_in_both_engines_remains_readback_without_any_new_claim(self):
        for path, function in (
            (S_REMOTE, "attest_original_evaluated_remote_selection"),
            (C_REMOTE, "attest_original_evaluated_remote_completion"),
        ):
            self.rejects(path, function, "CommandOrigin::Recovered => self.readback_source(source).await?", "CommandOrigin::Recovered => self.attest_source(source).await?")
        for path in (S_OPAQUE, C_OPAQUE):
            self.rejects(path, "recover_evaluated", "CommandOrigin::Recovered", "CommandOrigin::FreshCreate")
            self.rejects(path, "from_evaluated_custody", ".into_original_receipt_readback()", "")
        for path in (S_MAIN, C_MAIN):
            self.rejects(path, "recover_from_original_stream", "retained", "None")

    def test_real_product_mounts_and_native_mechanism_cases_remain_connected(self):
        for path, module, name in MOUNTS:
            source = (ROOT / path).read_text()
            code = code_of(source)
            pattern = re.compile(r'#\[path\s*=\s*[^\]]+\]\s*(?:pub\([^)]*\)\s+)?mod\s+' + re.escape(module) + r'\s*;')
            matches = list(pattern.finditer(code))
            self.assertEqual(len(matches), 1, (path, module))
            actual = source[matches[0].start():matches[0].end()]
            self.assertIn('"' + name + '"', actual)
        for name in (
            "OriginalCircuitEvaluatedSelectionCommandClientV1",
            "OriginalCircuitEvaluatedSelectionCommandErrorV1",
            "OriginalCircuitEvaluatedSelectionCommandOwnerV1",
            "OriginalCircuitEvaluatedNextUseCommandClientV1",
            "OriginalCircuitEvaluatedNextUseCommandErrorV1",
            "OriginalCircuitEvaluatedNextUseCommandOwnerV1",
        ):
            source = (ROOT / AGENT / "lib.rs").read_text()
            code = code_of(source)
            found = list(re.finditer(r'#\[cfg\(target_os\s*=\s*[^)]+\)\]\s*pub use learning_iteration_evidence_client::' + name + r';', code))
            self.assertEqual(len(found), 1, name)
            self.assertIn('"linux"', source[found[0].start():found[0].end()])
        for path, cases in NATIVE_CASES.items():
            source = (ROOT / path).read_text()
            for case in cases:
                self.assertRegex(source, r"#\[tokio::test\([^\]]+\)\]\s*async fn " + case + r"\(")
        for path, child in (
            (AGENT + "circuit_evaluated_retention_receipt_tests.rs", "circuit_evaluated_selection_command_tests.rs"),
            (AGENT + "circuit_evaluated_selection_command_tests.rs", "circuit_evaluated_next_use_command_tests.rs"),
            (AGENT + "circuit_evaluated_next_use_receipt_tests.rs", "circuit_evaluated_next_use_remote_tests.rs"),
        ):
            self.assertIn('#[path = "' + child + '"]', (ROOT / path).read_text())


if __name__ == "__main__":
    unittest.main()

