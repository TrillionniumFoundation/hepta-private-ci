//! Two-phase preparation for governed plasticity.
//!
//! Generator completeness and independent evaluation necessarily happen after
//! candidate generation. This API prepares the exact content-addressed candidate
//! set and generator signing payload before final proposal admission. Finalize
//! still recomputes the same inputs and fails closed on any drift.

use codex_hepta_learning_artifacts::{ArtifactKind, ArtifactRegistry};
use codex_hepta_learning_ledger::{
    DatasetSnapshotReceiptV3, LearningEvidenceRoleV1, LearningEvidenceVerifierV1,
    SignedLearningEvidenceV1, verify_dataset_snapshot_receipt_v3,
};
use codex_hepta_types::{Digest32, StableId};

use crate::{
    GeneratedParameterCandidateSetV3, GovernedProposalError, ParameterEvidenceBindingV3,
    ParameterGenerationPolicyV3, PlasticityEvidenceKindV3, PlasticityEvidencePortV3,
    PlasticityEvidenceQueryV3, candidate_completeness_signing_payload_v3,
    evidence_binding_signing_payload_v3, generate_parameter_candidates_v3,
    verify_plasticity_evidence_v3,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GovernedParameterPreparationV3 {
    pub generated: GeneratedParameterCandidateSetV3,
    pub generator_signing_payload: Vec<u8>,
    pub artifact_registry_head_digest: Digest32,
    pub evidence_verification_digest: Digest32,
    pub source_payload_digest: Digest32,
}

/// Prepare exactly the candidate set that the final governed admission will
/// recompute. The caller can use `generator_signing_payload` for the authenticated
/// Generator attestation and `generated.completeness.set_id` as the independent
/// evaluator's candidate identity.
pub fn prepare_governed_parameter_candidates_v3(
    binding: &ParameterEvidenceBindingV3,
    policy: &ParameterGenerationPolicyV3,
    source_evidence: &SignedLearningEvidenceV1,
    dataset: &DatasetSnapshotReceiptV3,
    verifier: &LearningEvidenceVerifierV1,
    artifacts: &ArtifactRegistry,
    evidence_port: &dyn PlasticityEvidencePortV3,
    now: u64,
) -> Result<GovernedParameterPreparationV3, GovernedProposalError> {
    if source_evidence.objective_digest != binding.objective_digest {
        return Err(GovernedProposalError::Binding(
            "signed learning evidence objective",
        ));
    }
    let manifest = artifacts
        .manifest(&binding.selected_artifact_id)
        .ok_or(GovernedProposalError::Artifact("selected artifact missing"))?;
    if !artifacts.is_eligible(&binding.selected_artifact_id) {
        return Err(GovernedProposalError::Artifact(
            "selected artifact lineage unavailable",
        ));
    }
    if !matches!(manifest.kind, ArtifactKind::Parameters | ArtifactKind::Model) {
        return Err(GovernedProposalError::Artifact("selected artifact kind"));
    }
    if manifest.content_digest != binding.selected_artifact_digest
        || manifest.objective_digest != binding.objective_digest
        || manifest.generation != binding.baseline_generation
    {
        return Err(GovernedProposalError::Artifact("selected artifact binding"));
    }
    if binding.baseline_generation.next() != Ok(binding.candidate_generation) {
        return Err(GovernedProposalError::Binding(
            "candidate generation is not exact successor",
        ));
    }

    verify_dataset_snapshot_receipt_v3(dataset, now)?;
    if dataset.snapshot.dataset_digest != binding.dataset_digest
        || dataset.snapshot.objective_digest != binding.objective_digest
    {
        return Err(GovernedProposalError::Binding("dataset binding"));
    }

    let artifact_registry_head_digest = artifacts
        .records()
        .last()
        .map_or(Digest32::ZERO, |record| record.chain_digest);
    let evidence_verification_digest = verify_evidence_set(binding, evidence_port, now)?;
    let source_payload = evidence_binding_signing_payload_v3(
        binding,
        artifact_registry_head_digest,
        &dataset.snapshot.snapshot_id,
    )?;
    verifier.verify(
        LearningEvidenceRoleV1::Observer,
        source_evidence,
        &source_payload,
        now,
    )?;
    let source_payload_digest = Digest32::of_bytes(&source_payload);

    let mut generator_state = b"hepta.plasticity.generator-state.v3\0".to_vec();
    generator_state.extend_from_slice(source_payload_digest.as_array());
    generator_state.extend_from_slice(evidence_verification_digest.as_array());
    let generated = generate_parameter_candidates_v3(
        binding,
        policy,
        Digest32::of_bytes(&generator_state),
    )?;
    let generator_signing_payload =
        candidate_completeness_signing_payload_v3(&generated.completeness)?;

    Ok(GovernedParameterPreparationV3 {
        generated,
        generator_signing_payload,
        artifact_registry_head_digest,
        evidence_verification_digest,
        source_payload_digest,
    })
}

fn verify_evidence_set(
    binding: &ParameterEvidenceBindingV3,
    evidence_port: &dyn PlasticityEvidencePortV3,
    now: u64,
) -> Result<Digest32, GovernedProposalError> {
    let mut verification_digests = Vec::with_capacity(4 + binding.opportunities.len());
    for (kind, evidence_digest) in [
        (PlasticityEvidenceKindV3::UpdateRule, binding.update_rule_digest),
        (PlasticityEvidenceKindV3::Modulator, binding.modulator_digest),
        (
            PlasticityEvidenceKindV3::ModulatorBroadcast,
            binding.modulator_broadcast_digest,
        ),
        (PlasticityEvidenceKindV3::Eligibility, binding.eligibility_digest),
    ] {
        verification_digests.push(verify_plasticity_evidence_v3(
            evidence_port,
            &query(binding, kind, evidence_digest, None, None, now),
        )?);
    }

    let mut opportunities = binding.opportunities.iter().collect::<Vec<_>>();
    opportunities.sort_by(|left, right| {
        left.layer_id
            .cmp(&right.layer_id)
            .then_with(|| left.parameter_id.cmp(&right.parameter_id))
    });
    for opportunity in opportunities {
        verification_digests.push(verify_plasticity_evidence_v3(
            evidence_port,
            &query(
                binding,
                PlasticityEvidenceKindV3::ParameterOpportunity,
                opportunity.evidence_digest,
                Some(opportunity.layer_id.clone()),
                Some(opportunity.parameter_id.clone()),
                now,
            ),
        )?);
    }

    let mut bytes = b"hepta.plasticity.evidence-verification-set.v3\0".to_vec();
    push_len(&mut bytes, verification_digests.len())?;
    for digest in verification_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn query(
    binding: &ParameterEvidenceBindingV3,
    kind: PlasticityEvidenceKindV3,
    evidence_digest: Digest32,
    layer_id: Option<StableId>,
    parameter_id: Option<StableId>,
    now: u64,
) -> PlasticityEvidenceQueryV3 {
    PlasticityEvidenceQueryV3 {
        kind,
        evidence_digest,
        objective_digest: binding.objective_digest,
        selected_artifact_digest: binding.selected_artifact_digest,
        window_id: binding.window.window_id.clone(),
        window_digest: binding.window.window_digest,
        dataset_digest: binding.dataset_digest,
        baseline_generation: binding.baseline_generation,
        layer_id,
        parameter_id,
        now,
    }
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), GovernedProposalError> {
    let value = u32::try_from(value).map_err(|_| GovernedProposalError::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}
