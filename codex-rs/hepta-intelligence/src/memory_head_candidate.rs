//! Compose persisted research Head bytes with an anchored MemoryCell proposal.
//!
//! Every call reopens the owner's current evidence boundary. Signatures attest
//! the exact proposal and its provenance; they do not establish empirical
//! quality. The result cannot activate weights or modify the current snapshot.

use std::fmt;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::HnmfContractError;
use codex_hepta_cognitive_types::memory_cell::MemoryCellManifestV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellRoleV1;
use codex_hepta_cognitive_types::memory_meta_network::MemoryCellNextSnapshotCandidateV1;
use codex_hepta_learning_artifacts::ArtifactReadErrorV1;
use codex_hepta_learning_artifacts::ArtifactReadPinsV1;
use codex_hepta_learning_artifacts::CellHeadBundleErrorV1;
use codex_hepta_learning_artifacts::CellHeadBundleIdentityV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::VerifiedCellHeadBindingV1;
use codex_hepta_learning_artifacts::verify_cell_head_bundle;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryHeadCandidateContextV1 {
    pub candidate: MemoryCellNextSnapshotCandidateV1,
    pub artifact_pins: ArtifactReadPinsV1,
    pub head_identity: CellHeadBundleIdentityV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryHeadCandidateRequestV1 {
    pub context: MemoryHeadCandidateContextV1,
    pub replay_attestation: SignedLearningEvidenceV1,
    pub evaluator_attestation: SignedLearningEvidenceV1,
}

/// All fields are private. Construction requires live owner readback and two
/// independently controlled, host-trusted signers. This is still a proposal.
#[derive(Debug)]
pub struct PreparedMemoryHeadCandidateV1 {
    candidate: MemoryCellNextSnapshotCandidateV1,
    head: VerifiedCellHeadBindingV1,
    evidence_digest: Digest32,
}

impl PreparedMemoryHeadCandidateV1 {
    pub fn candidate(&self) -> &MemoryCellNextSnapshotCandidateV1 {
        &self.candidate
    }

    pub fn head(&self) -> &VerifiedCellHeadBindingV1 {
        &self.head
    }

    pub fn evidence_digest(&self) -> Digest32 {
        self.evidence_digest
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Debug)]
pub enum MemoryHeadCandidateErrorV1 {
    Contract(HnmfContractError),
    Owner(ArtifactReadErrorV1),
    Bundle(CellHeadBundleErrorV1),
    Evidence(SignedEvidenceError),
    Binding(&'static str),
}

impl fmt::Display for MemoryHeadCandidateErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for MemoryHeadCandidateErrorV1 {}

/// Canonical, bounded bytes signed by both the replay producer and evaluator.
/// The verifier's role parameter domain-separates their signatures. An evaluator
/// must resolve the referenced evaluation receipt independently before signing.
pub fn memory_head_candidate_signing_payload_v1(
    context: &MemoryHeadCandidateContextV1,
) -> Result<Vec<u8>, MemoryHeadCandidateErrorV1> {
    let candidate = &context.candidate;
    candidate
        .validate()
        .map_err(MemoryHeadCandidateErrorV1::Contract)?;
    let mut bytes = b"hepta.intelligence.memory-head-candidate.v1\0".to_vec();
    let id = candidate.cell_id.as_str().as_bytes();
    bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
    bytes.extend_from_slice(id);
    for digest in [
        candidate.shared_base_digest,
        candidate.encoder_digest,
        candidate.source_frontier_digest,
        candidate.forget_frontier_digest,
        candidate.replay_snapshot_digest,
        candidate.replay_receipt_digest,
        candidate.candidate_adapter_artifact_digest,
        candidate.candidate_head_artifact_digest,
        candidate.independent_evaluation_digest,
        candidate.rollback_plan_digest,
    ] {
        bytes.extend_from_slice(digest.digest().as_array());
    }
    for generation in [
        candidate.predecessor_graph_generation,
        candidate.next_graph_generation,
        candidate.predecessor_model_generation,
        candidate.next_model_generation,
    ] {
        bytes.extend_from_slice(&generation.get().to_be_bytes());
    }
    if candidate.topology_proposal_digest.is_some() {
        return Err(MemoryHeadCandidateErrorV1::Binding(
            "head-only proposal changes topology",
        ));
    }
    let identity = &context.head_identity;
    let pins = &context.artifact_pins;
    for digest in [
        identity.feature.compatibility_digest(),
        identity.manifest_digest,
        identity.weights_digest,
        identity.source_frontier_digest,
        identity.training_dataset_digest,
        identity.calibration_dataset_digest,
        identity.training_code_digest,
        identity.runtime_tuple_digest,
        identity.trained_tensor_digest,
        pins.admission.admission_digest,
        pins.publication.state_digest,
        pins.publication.witness_digest,
        pins.expected_registry_predecessor_head,
        pins.current_registry_head,
        pins.current_withdrawal_head,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(bytes)
}

/// Fresh, read-only composition. The owner retains its normal durability and
/// source-withdrawal fences. No model executor or learning writer is accepted.
pub fn prepare_memory_head_candidate_v1(
    owner: &LearningArtifactOwnerService,
    manifest: &MemoryCellManifestV1,
    request: &MemoryHeadCandidateRequestV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<PreparedMemoryHeadCandidateV1, MemoryHeadCandidateErrorV1> {
    let context = &request.context;
    let candidate = &context.candidate;
    candidate
        .validate_against(manifest)
        .map_err(MemoryHeadCandidateErrorV1::Contract)?;
    if !matches!(
        manifest.role,
        MemoryCellRoleV1::Semantic | MemoryCellRoleV1::Procedural
    ) {
        return Err(MemoryHeadCandidateErrorV1::Binding("untrained cell role"));
    }
    if candidate.candidate_adapter_artifact_digest != manifest.adapter_artifact_digest {
        return Err(MemoryHeadCandidateErrorV1::Binding(
            "external adapter changed",
        ));
    }
    let payload = memory_head_candidate_signing_payload_v1(context)?;
    let read = owner
        .read_current_artifact(&context.artifact_pins, now)
        .map_err(MemoryHeadCandidateErrorV1::Owner)?;
    let head = verify_cell_head_bundle(read, &context.head_identity)
        .map_err(MemoryHeadCandidateErrorV1::Bundle)?;
    check_binding(manifest, candidate, &head)?;
    let replay = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &request.replay_attestation,
            &payload,
            now,
        )
        .map_err(MemoryHeadCandidateErrorV1::Evidence)?;
    let evaluation = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &request.evaluator_attestation,
            &payload,
            now,
        )
        .map_err(MemoryHeadCandidateErrorV1::Evidence)?;
    verify_signed_independent_roles_v1(&replay, &evaluation, now)
        .map_err(MemoryHeadCandidateErrorV1::Evidence)?;
    if replay.objective_digest() != head.artifact().manifest().objective_class_digest
        || replay.principal().scope_digest != head.identity().feature.scope_digest
    {
        return Err(MemoryHeadCandidateErrorV1::Binding(
            "artifact objective differs",
        ));
    }
    let evidence_digest = Digest32::of_parts(&[
        b"hepta.intelligence.prepared-memory-head.v1\0",
        &payload,
        verifier.trust_digest().as_array(),
        head.artifact().trust_digest().as_array(),
        head.artifact().witness_digest().as_array(),
        &request.replay_attestation.signing_bytes(),
        &request.replay_attestation.signature,
        &request.evaluator_attestation.signing_bytes(),
        &request.evaluator_attestation.signature,
    ]);
    Ok(PreparedMemoryHeadCandidateV1 {
        candidate: candidate.clone(),
        head,
        evidence_digest,
    })
}

fn check_binding(
    manifest: &MemoryCellManifestV1,
    candidate: &MemoryCellNextSnapshotCandidateV1,
    head: &VerifiedCellHeadBindingV1,
) -> Result<(), MemoryHeadCandidateErrorV1> {
    let identity = head.identity();
    let artifact = head.artifact();
    let bound = |digest: ContractDigestV1, expected| digest.digest() == expected;
    if !bound(manifest.encoder_digest, identity.feature.encoder_digest)
        || !bound(
            manifest.source_frontier_digest,
            identity.source_frontier_digest,
        )
        || !bound(
            manifest.forget_frontier_digest,
            artifact.current_withdrawal_head(),
        )
        || !bound(
            candidate.replay_snapshot_digest,
            identity.training_dataset_digest,
        )
        || !bound(
            candidate.candidate_head_artifact_digest,
            artifact.manifest().bytes_digest,
        )
        || candidate.next_model_generation.get() != artifact.manifest().generation.get()
    {
        return Err(MemoryHeadCandidateErrorV1::Binding(
            "memory/head provenance differs",
        ));
    }
    Ok(())
}

