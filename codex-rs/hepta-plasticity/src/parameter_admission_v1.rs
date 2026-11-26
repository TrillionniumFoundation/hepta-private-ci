//! Original parameter admission facts and signing bytes, without evidence authority.
use crate::GeneratedParameterCandidateSetV3;
use crate::ParameterCandidateKindV2;
use crate::ProposalWindowV2;
use crate::parameter_material_wire::ParameterMaterialCodecErrorV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityAdmissionEvidenceV1 {
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub artifact_registry_binding: Digest32,
    pub artifact_registry_head_digest: Digest32,
    pub qualification_evidence_head_digest: Digest32,
    /// Canonical digest of host-resolved, context-bound owner evidence receipts.
    pub owner_evidence_set_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub dataset_digest: Digest32,
    pub update_rule_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub eligibility_digest: Digest32,
    pub generator_digest: Digest32,
}

/// Canonical bytes attested by the trusted Observer evidence role. The verifier's
/// own validity/revocation window provides freshness; the payload binds the exact
/// artifact/evidence frontiers and all proposal lineage digests.
pub fn plasticity_admission_signing_payload_v1(
    evidence: &PlasticityAdmissionEvidenceV1,
) -> Vec<u8> {
    let mut bytes = b"hepta.intelligence.plasticity-admission.v1\0".to_vec();
    push_id(&mut bytes, &evidence.baseline_id);
    for digest in [
        evidence.objective_digest,
        evidence.selected_artifact_digest,
        evidence.artifact_registry_binding,
        evidence.artifact_registry_head_digest,
        evidence.qualification_evidence_head_digest,
        evidence.owner_evidence_set_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &evidence.window.window_id);
    bytes.extend_from_slice(evidence.window.window_digest.as_array());
    bytes.extend_from_slice(&evidence.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&evidence.candidate_generation.get().to_be_bytes());
    for digest in [
        evidence.dataset_digest,
        evidence.update_rule_digest,
        evidence.modulator_digest,
        evidence.modulator_broadcast_digest,
        evidence.eligibility_digest,
        evidence.generator_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes
}

/// Canonical terminal payload used only when the deterministic V3 generator
/// produces the explicit no-change candidate and no admissible update candidate.
/// Signing this payload is an independent evaluation of the terminal disposition;
/// it is not selection, activation or authority to mutate the current artifact.
pub fn no_change_disposition_signing_payload_v1(
    generated: &GeneratedParameterCandidateSetV3,
    admission: &PlasticityAdmissionEvidenceV1,
) -> Result<Vec<u8>, ParameterMaterialCodecErrorV1> {
    let no_change = generated
        .candidates
        .iter()
        .find(|candidate| candidate.kind == ParameterCandidateKindV2::NoChange)
        .ok_or(ParameterMaterialCodecErrorV1::MissingNoChange)?;
    let mut bytes = b"hepta.intelligence.plasticity-no-admissible-update.v1\0".to_vec();
    bytes.extend_from_slice(generated.generator_digest.as_array());
    bytes.extend_from_slice(admission.owner_evidence_set_digest.as_array());
    bytes.extend_from_slice(admission.selected_artifact_digest.as_array());
    push_id(&mut bytes, &admission.window.window_id);
    bytes.extend_from_slice(admission.window.window_digest.as_array());
    bytes.extend_from_slice(&admission.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&admission.candidate_generation.get().to_be_bytes());
    push_id(&mut bytes, &no_change.candidate_id);
    Ok(bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct ParameterAdmissionBindingErrorV1(pub &'static str);
impl std::fmt::Display for ParameterAdmissionBindingErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.0)
    }
}
impl std::error::Error for ParameterAdmissionBindingErrorV1 {}
/// Exact original product binding checks, without authentication or mutation.
pub fn validate_parameter_admission_binding_v1(
    profile: &crate::ParameterGeneratorProfileV3,
    generated: &GeneratedParameterCandidateSetV3,
    evidence: &PlasticityAdmissionEvidenceV1,
) -> Result<(), ParameterAdmissionBindingErrorV1> {
    for (label, digest) in [
        ("objective", evidence.objective_digest),
        ("selected artifact", evidence.selected_artifact_digest),
        (
            "artifact registry binding",
            evidence.artifact_registry_binding,
        ),
        (
            "artifact registry head",
            evidence.artifact_registry_head_digest,
        ),
        (
            "qualification evidence head",
            evidence.qualification_evidence_head_digest,
        ),
        ("owner evidence set", evidence.owner_evidence_set_digest),
        ("dataset", evidence.dataset_digest),
        ("update rule", evidence.update_rule_digest),
        ("modulator", evidence.modulator_digest),
        ("modulator broadcast", evidence.modulator_broadcast_digest),
        ("eligibility", evidence.eligibility_digest),
        ("generator", evidence.generator_digest),
    ] {
        if digest.is_zero() {
            return Err(ParameterAdmissionBindingErrorV1(label));
        }
    }
    if evidence.baseline_generation.next() != Ok(evidence.candidate_generation) {
        return Err(ParameterAdmissionBindingErrorV1("generation successor"));
    }
    if evidence.selected_artifact_digest != generated.selected_artifact_digest
        || evidence.window != generated.window
        || evidence.generator_digest != generated.generator_digest
        || profile.selected_artifact_digest != generated.selected_artifact_digest
        || profile.window != generated.window
    {
        return Err(ParameterAdmissionBindingErrorV1("generator/admission"));
    }
    Ok(())
}
