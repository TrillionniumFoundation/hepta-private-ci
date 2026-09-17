//! Deterministic three-factor parameter candidate generation.
//!
//! V2 remains the stable supplied-candidate compatibility surface. This module
//! adds a generator-relative completeness boundary: every admitted trainable
//! parameter signal is deterministically projected exactly once, and the full
//! non-zero result is emitted as one update candidate beside the mandatory
//! no-change candidate. No candidate is silently truncated or selected.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::ParameterCandidateKindV2;
use crate::ParameterCandidateRequestV2;
use crate::ParameterDeltaV2;
use crate::types::MAX_PARAMETER_DELTAS;

const GENERATOR_DOMAIN: &[u8] = b"hepta.plasticity.parameter-generator.v3";
const CANDIDATE_SET_DOMAIN: &[u8] = b"hepta.plasticity.generated-candidate-set.v3";

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct ParameterGeneratorSignalV3 {
    pub layer_id: StableId,
    pub parameter_id: StableId,
    /// Bounded local eligibility value for this trainable parameter.
    pub eligibility: FixedQ32,
    /// Artifact-bound low-dimensional modulator broadcast after B_m mapping.
    pub modulator_broadcast: FixedQ32,
    pub lower_bound: FixedQ32,
    pub upper_bound: FixedQ32,
    /// Evidence for the exact eligibility/modulator pair used by this row.
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterGeneratorRequestV3 {
    pub proposal_id: StableId,
    /// Registered step size. It must be strictly positive.
    pub learning_rate: FixedQ32,
    /// Complete admitted trainable surface for this generator invocation.
    pub signals: Vec<ParameterGeneratorSignalV3>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratedParameterCandidateSetV3 {
    pub candidates: Vec<ParameterCandidateRequestV2>,
    pub generator_input_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub input_parameter_count: u32,
    pub generated_delta_count: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ParameterGeneratorErrorV3 {
    InvalidLearningRate,
    SignalLimitExceeded,
    DuplicateParameter(String),
    InvertedBounds(String),
    EmptyEvidence(String),
    Arithmetic,
    InvalidGeneratedIdentifier,
}

impl fmt::Display for ParameterGeneratorErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ParameterGeneratorErrorV3 {}

/// Generate the complete bounded candidate set for one admitted signal surface.
///
/// Generation is deterministic and fail-closed. The caller cannot supply the
/// candidates. Every signal is included in the generator input digest. A signal
/// whose projected/clamped update is zero remains represented by that digest but
/// contributes no parameter delta. If every projected update is zero the result
/// is the explicit no-change candidate only.
pub fn generate_parameter_candidates_v3(
    mut request: ParameterGeneratorRequestV3,
) -> Result<GeneratedParameterCandidateSetV3, ParameterGeneratorErrorV3> {
    if request.learning_rate <= FixedQ32::ZERO {
        return Err(ParameterGeneratorErrorV3::InvalidLearningRate);
    }
    if request.signals.len() > MAX_PARAMETER_DELTAS {
        return Err(ParameterGeneratorErrorV3::SignalLimitExceeded);
    }

    request.signals.sort_by(|left, right| {
        left.layer_id
            .cmp(&right.layer_id)
            .then_with(|| left.parameter_id.cmp(&right.parameter_id))
    });
    let mut seen = BTreeSet::new();
    for signal in &request.signals {
        if !seen.insert(signal.parameter_id.clone()) {
            return Err(ParameterGeneratorErrorV3::DuplicateParameter(
                signal.parameter_id.to_string(),
            ));
        }
        if signal.lower_bound > signal.upper_bound {
            return Err(ParameterGeneratorErrorV3::InvertedBounds(
                signal.parameter_id.to_string(),
            ));
        }
        if signal.evidence_digest.is_zero() {
            return Err(ParameterGeneratorErrorV3::EmptyEvidence(
                signal.parameter_id.to_string(),
            ));
        }
    }

    let generator_input_digest = digest_generator_request(&request)?;
    let no_change_id = generated_id("no-change", generator_input_digest)?;
    let update_id = generated_id("update", generator_input_digest)?;

    let mut deltas = Vec::with_capacity(request.signals.len());
    for signal in &request.signals {
        let update = signal
            .eligibility
            .checked_mul(signal.modulator_broadcast)
            .and_then(|value| value.checked_mul(request.learning_rate))
            .map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?
            .clamp(signal.lower_bound, signal.upper_bound)
            .map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?;
        if update == FixedQ32::ZERO {
            continue;
        }
        deltas.push(ParameterDeltaV2 {
            layer_id: signal.layer_id.clone(),
            parameter_id: signal.parameter_id.clone(),
            delta: update,
            lower_bound: signal.lower_bound,
            upper_bound: signal.upper_bound,
            evidence_digest: signal.evidence_digest,
        });
    }

    let mut candidates = vec![ParameterCandidateRequestV2 {
        candidate_id: no_change_id,
        kind: ParameterCandidateKindV2::NoChange,
        parameter_deltas: Vec::new(),
    }];
    if !deltas.is_empty() {
        candidates.push(ParameterCandidateRequestV2 {
            candidate_id: update_id,
            kind: ParameterCandidateKindV2::Update,
            parameter_deltas: deltas,
        });
    }
    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));

    let input_parameter_count = u32::try_from(request.signals.len())
        .map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?;
    let generated_delta_count = u32::try_from(
        candidates
            .iter()
            .map(|candidate| candidate.parameter_deltas.len())
            .sum::<usize>(),
    )
    .map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?;
    let candidate_set_digest = digest_candidate_set(generator_input_digest, &candidates)?;
    Ok(GeneratedParameterCandidateSetV3 {
        candidates,
        generator_input_digest,
        candidate_set_digest,
        input_parameter_count,
        generated_delta_count,
    })
}

/// Recompute a generated set from its request and require byte-semantic parity.
pub fn verify_generated_parameter_candidates_v3(
    request: ParameterGeneratorRequestV3,
    generated: &GeneratedParameterCandidateSetV3,
) -> Result<(), ParameterGeneratorErrorV3> {
    if &generate_parameter_candidates_v3(request)? == generated {
        Ok(())
    } else {
        Err(ParameterGeneratorErrorV3::Arithmetic)
    }
}

/// Canonical bytes that a trusted generator signs before a governed proposal is
/// admitted. The payload binds both the complete input surface and its output.
pub fn generator_attestation_payload_v3(
    generated: &GeneratedParameterCandidateSetV3,
) -> Vec<u8> {
    let mut bytes = b"hepta.plasticity.generator-attestation.v3".to_vec();
    bytes.extend_from_slice(generated.generator_input_digest.as_array());
    bytes.extend_from_slice(generated.candidate_set_digest.as_array());
    bytes.extend_from_slice(&generated.input_parameter_count.to_be_bytes());
    bytes.extend_from_slice(&generated.generated_delta_count.to_be_bytes());
    bytes
}

fn digest_generator_request(
    request: &ParameterGeneratorRequestV3,
) -> Result<Digest32, ParameterGeneratorErrorV3> {
    let mut bytes = GENERATOR_DOMAIN.to_vec();
    push_id(&mut bytes, &request.proposal_id)?;
    bytes.extend_from_slice(&request.learning_rate.raw().to_be_bytes());
    push_len(&mut bytes, request.signals.len())?;
    for signal in &request.signals {
        push_id(&mut bytes, &signal.layer_id)?;
        push_id(&mut bytes, &signal.parameter_id)?;
        bytes.extend_from_slice(&signal.eligibility.raw().to_be_bytes());
        bytes.extend_from_slice(&signal.modulator_broadcast.raw().to_be_bytes());
        bytes.extend_from_slice(&signal.lower_bound.raw().to_be_bytes());
        bytes.extend_from_slice(&signal.upper_bound.raw().to_be_bytes());
        bytes.extend_from_slice(signal.evidence_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_candidate_set(
    input_digest: Digest32,
    candidates: &[ParameterCandidateRequestV2],
) -> Result<Digest32, ParameterGeneratorErrorV3> {
    let mut bytes = CANDIDATE_SET_DOMAIN.to_vec();
    bytes.extend_from_slice(input_digest.as_array());
    push_len(&mut bytes, candidates.len())?;
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.push(match candidate.kind {
            ParameterCandidateKindV2::NoChange => 0,
            ParameterCandidateKindV2::Update => 1,
        });
        push_len(&mut bytes, candidate.parameter_deltas.len())?;
        for delta in &candidate.parameter_deltas {
            push_id(&mut bytes, &delta.layer_id)?;
            push_id(&mut bytes, &delta.parameter_id)?;
            bytes.extend_from_slice(&delta.delta.raw().to_be_bytes());
            bytes.extend_from_slice(&delta.lower_bound.raw().to_be_bytes());
            bytes.extend_from_slice(&delta.upper_bound.raw().to_be_bytes());
            bytes.extend_from_slice(delta.evidence_digest.as_array());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn generated_id(
    kind: &str,
    input_digest: Digest32,
) -> Result<StableId, ParameterGeneratorErrorV3> {
    StableId::new(format!("plasticity:{kind}:{input_digest}"))
        .map_err(|_| ParameterGeneratorErrorV3::InvalidGeneratedIdentifier)
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), ParameterGeneratorErrorV3> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), ParameterGeneratorErrorV3> {
    let length = u32::try_from(value).map_err(|_| ParameterGeneratorErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    Ok(())
}
