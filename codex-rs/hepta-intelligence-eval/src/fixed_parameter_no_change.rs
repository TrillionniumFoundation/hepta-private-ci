//! Complete original no-update E output. A raw decode is not Root custody.
use crate::*;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_plasticity::*;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

pub(crate) type HostResult<T> = Result<T, Box<dyn std::error::Error>>;
pub(crate) const MAX_NO_CHANGE_OUTPUT_BYTES: usize = 64 * 1024;
#[cfg(test)]
#[path = "fixed_parameter_no_change_tests.rs"]
mod tests;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Publication {
    pub(crate) schema: String,
    pub(crate) profile_digest: String,
    pub(crate) generator_digest: String,
    pub(crate) admission_digest: String,
    pub(crate) evaluator_evidence: ReviewEvidenceWireV1,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Output {
    pub(crate) schema: String,
    pub(crate) publication_hex: String,
    pub(crate) preparation_terminal_hex: String,
}

/// Verified original signatures and whole public bytes. Root custody and the
/// original live Round/material/source binding still require the caller's ports.
pub struct FixedParameterNoChangeOutputV1 {
    pub no_change_attestation: SignedLearningEvidenceV1,
    pub preparation_facts: SelfIterationPreparationFactsV1,
    pub preparation_attestation: SignedLearningEvidenceV1,
    pub publication_bytes: Vec<u8>,
    pub preparation_terminal_bytes: Vec<u8>,
}

pub(crate) fn evidence_digest(value: &SignedLearningEvidenceV1) -> Digest32 {
    Digest32::of_bytes(&[value.signing_bytes().as_slice(), value.signature.as_slice()].concat())
}
pub(crate) fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
pub(crate) fn unhex(value: &str, maximum: usize) -> HostResult<Vec<u8>> {
    if !value.len().is_multiple_of(2)
        || value.len() > maximum.checked_mul(2).ok_or("hex bound")?
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("complete parameter E hex".into());
    }
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let text = std::str::from_utf8(pair)?;
            Ok(u8::from_str_radix(text, 16)?)
        })
        .collect()
}
pub(crate) fn no_change(
    profile: &ParameterGeneratorProfileV3,
    admission: &PlasticityAdmissionEvidenceV1,
) -> HostResult<GeneratedParameterCandidateSetV3> {
    let generated = generate_parameter_candidates_v3(profile.clone())?;
    validate_parameter_admission_binding_v1(profile, &generated, admission)?;
    if generated
        .candidates
        .iter()
        .any(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
        || generated.candidates.len() != 1
        || generated.candidates[0].kind != ParameterCandidateKindV2::NoChange
    {
        return Err("fixed no-change E requires the actual complete no-update frontier".into());
    }
    Ok(generated)
}

/// Authenticate the exact original no-change and preparation signatures. This
/// never runs a model, records a proposal, signs, or changes current authority.
pub fn decode_fixed_parameter_no_change_output_v1(
    bytes: &[u8],
    profile: &ParameterGeneratorProfileV3,
    admission: &PlasticityAdmissionEvidenceV1,
    generator: &SignedLearningEvidenceV1,
    observer: &SignedLearningEvidenceV1,
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> HostResult<FixedParameterNoChangeOutputV1> {
    if bytes.len() > MAX_NO_CHANGE_OUTPUT_BYTES {
        return Err("parameter E output bound".into());
    }
    let output: Output = serde_json::from_slice(bytes)?;
    if output.schema != "hepta.parameter.no-change-output.v1" {
        return Err("parameter E schema".into());
    }
    let publication_bytes = unhex(&output.publication_hex, MAX_NO_CHANGE_OUTPUT_BYTES)?;
    let publication: Publication = serde_json::from_slice(&publication_bytes)?;
    if publication.schema != "hepta.parameter.no-admissible-update.v1"
        || serde_json::to_vec(&publication)? != publication_bytes
    {
        return Err("complete original no-change publication".into());
    }
    let generated = no_change(profile, admission)?;
    if publication.profile_digest.parse::<Digest32>()?
        != Digest32::of_bytes(&encode_untrusted_parameter_generator_profile_v3(profile)?)
        || publication.generator_digest.parse::<Digest32>()? != generated.generator_digest
        || publication.admission_digest.parse::<Digest32>()?
            != Digest32::of_bytes(&plasticity_admission_signing_payload_v1(admission))
    {
        return Err("original no-change material binding".into());
    }
    trust.revalidate_at(now)?;
    let g = trust.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        generator,
        &parameter_generator_signing_payload_v3(&generated),
        now,
    )?;
    let o = trust.verifier().verify(
        LearningEvidenceRoleV1::Observer,
        observer,
        &plasticity_admission_signing_payload_v1(admission),
        now,
    )?;
    let no_change_attestation = publication.evaluator_evidence.native()?;
    let e = trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &no_change_attestation,
        &no_change_disposition_signing_payload_v1(&generated, admission)?,
        now,
    )?;
    for actor in [&g, &o] {
        codex_hepta_learning_ledger::verify_signed_independent_roles_v1(actor, &e, now)?;
    }
    let preparation_terminal_bytes = unhex(
        &output.preparation_terminal_hex,
        MAX_SELF_ITERATION_PREPARATION_TERMINAL_BYTES_V1,
    )?;
    let (facts, preparation_attestation) =
        decode_self_iteration_preparation_terminal_v1(&preparation_terminal_bytes)?;
    if facts.disposition != SelfIterationPreparationDispositionV1::NoAdmissibleUpdate
        || facts.generated_digest != generated.generator_digest
        || facts.admission_digest
            != Digest32::of_bytes(&plasticity_admission_signing_payload_v1(admission))
        || facts.generator_evidence_digest != evidence_digest(generator)
        || facts.observer_evidence_digest != evidence_digest(observer)
        || facts.evaluation_publication_digest != Digest32::of_bytes(&publication_bytes)
        || facts.observed_at_ms != preparation_attestation.issued_at
        || preparation_attestation.principal_id != no_change_attestation.principal_id
        || no_change_attestation.issued_at > facts.observed_at_ms
        || preparation_attestation.expires_at > facts.deadline_ms
    {
        return Err("no-change original preparation facts".into());
    }
    let terminal_e = trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &preparation_attestation,
        &self_iteration_preparation_terminal_signing_payload_v1(&facts)?,
        now,
    )?;
    if terminal_e.controller_id() != e.controller_id() {
        return Err("same actual E purpose required".into());
    }
    Ok(FixedParameterNoChangeOutputV1 {
        no_change_attestation,
        preparation_facts: facts,
        preparation_attestation,
        publication_bytes,
        preparation_terminal_bytes,
    })
}
