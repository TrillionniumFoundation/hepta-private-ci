//! Fixed preparation outcomes bind real independent E output to an original
//! admitted round. Decoding these public facts supplies no custody or authority.
use crate::ProductEvaluationError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelfIterationPreparationDispositionV1 {
    NoAdmissibleUpdate,
    Ineligible,
    InsufficientEvidence,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationPreparationFactsV1 {
    pub disposition: SelfIterationPreparationDispositionV1,
    pub round_identity_digest: Digest32,
    pub round_payload_digest: Digest32,
    pub canonical_policy_digest: Digest32,
    pub execution_envelope_digest: Digest32,
    pub enrolled_inputs_digest: Digest32,
    pub generated_digest: Digest32,
    pub admission_digest: Digest32,
    pub generator_evidence_digest: Digest32,
    pub observer_evidence_digest: Digest32,
    /// The complete original E output, including its original evaluation or
    /// no-change signature; it excludes this terminal-purpose attestation.
    pub evaluation_publication_digest: Digest32,
    pub admitted_at_ms: u64,
    pub deadline_ms: u64,
    pub observed_at_ms: u64,
}

const DOMAIN: &[u8] = b"hepta.self-iteration.preparation-terminal.v1\0";
pub const MAX_SELF_ITERATION_PREPARATION_FACTS_BYTES_V1: usize = 512;
pub const MAX_SELF_ITERATION_PREPARATION_TERMINAL_BYTES_V1: usize = 64 * 1024;

/// One codec is also the fixed E signing preimage. A verifier must additionally
/// authenticate the original E and match the actual reserved round and sources.
pub fn self_iteration_preparation_terminal_signing_payload_v1(
    facts: &SelfIterationPreparationFactsV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    let digests = [
        facts.round_identity_digest,
        facts.round_payload_digest,
        facts.canonical_policy_digest,
        facts.execution_envelope_digest,
        facts.enrolled_inputs_digest,
        facts.generated_digest,
        facts.admission_digest,
        facts.generator_evidence_digest,
        facts.observer_evidence_digest,
        facts.evaluation_publication_digest,
    ];
    if digests.iter().any(|digest| digest.is_zero())
        || facts.admitted_at_ms == 0
        || facts.deadline_ms <= facts.admitted_at_ms
        || facts.observed_at_ms < facts.admitted_at_ms
        || facts.observed_at_ms >= facts.deadline_ms
    {
        return Err(invalid());
    }
    let mut bytes = DOMAIN.to_vec();
    bytes.push(match facts.disposition {
        SelfIterationPreparationDispositionV1::NoAdmissibleUpdate => 0,
        SelfIterationPreparationDispositionV1::Ineligible => 1,
        SelfIterationPreparationDispositionV1::InsufficientEvidence => 2,
    });
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    for time in [
        facts.admitted_at_ms,
        facts.deadline_ms,
        facts.observed_at_ms,
    ] {
        bytes.extend_from_slice(&time.to_be_bytes());
    }
    Ok(bytes)
}

pub fn decode_self_iteration_preparation_facts_v1(
    bytes: &[u8],
) -> Result<SelfIterationPreparationFactsV1, ProductEvaluationError> {
    if bytes.len() != DOMAIN.len() + 1 + 10 * 32 + 3 * 8 || !bytes.starts_with(DOMAIN) {
        return Err(invalid());
    }
    let disposition = match bytes[DOMAIN.len()] {
        0 => SelfIterationPreparationDispositionV1::NoAdmissibleUpdate,
        1 => SelfIterationPreparationDispositionV1::Ineligible,
        2 => SelfIterationPreparationDispositionV1::InsufficientEvidence,
        _ => return Err(invalid()),
    };
    let mut cursor = DOMAIN.len() + 1;
    let mut digest = || {
        let value = Digest32::from_array(
            bytes[cursor..cursor + 32]
                .try_into()
                .map_err(|_| invalid())?,
        );
        cursor += 32;
        Ok::<_, ProductEvaluationError>(value)
    };
    let digests = [
        digest()?,
        digest()?,
        digest()?,
        digest()?,
        digest()?,
        digest()?,
        digest()?,
        digest()?,
        digest()?,
        digest()?,
    ];
    let mut time = || {
        let value = u64::from_be_bytes(
            bytes[cursor..cursor + 8]
                .try_into()
                .map_err(|_| invalid())?,
        );
        cursor += 8;
        Ok::<_, ProductEvaluationError>(value)
    };
    let facts = SelfIterationPreparationFactsV1 {
        disposition,
        round_identity_digest: digests[0],
        round_payload_digest: digests[1],
        canonical_policy_digest: digests[2],
        execution_envelope_digest: digests[3],
        enrolled_inputs_digest: digests[4],
        generated_digest: digests[5],
        admission_digest: digests[6],
        generator_evidence_digest: digests[7],
        observer_evidence_digest: digests[8],
        evaluation_publication_digest: digests[9],
        admitted_at_ms: time()?,
        deadline_ms: time()?,
        observed_at_ms: time()?,
    };
    if self_iteration_preparation_terminal_signing_payload_v1(&facts)? != bytes {
        return Err(invalid());
    }
    Ok(facts)
}

/// Complete original E terminal output, using the existing raw evidence codec.
/// Encoding or decoding does not authenticate its role or its Root custody.
pub fn encode_self_iteration_preparation_terminal_v1(
    facts: &SelfIterationPreparationFactsV1,
    evaluator: &SignedLearningEvidenceV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    let facts = self_iteration_preparation_terminal_signing_payload_v1(facts)?;
    let evidence = crate::encode_untrusted_plasticity_learning_evidence_v1(evaluator)?;
    let mut bytes = b"HPTSPT01".to_vec();
    bytes.extend_from_slice(&(facts.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&(evidence.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&facts);
    bytes.extend_from_slice(&evidence);
    if bytes.len() + 32 > MAX_SELF_ITERATION_PREPARATION_TERMINAL_BYTES_V1 {
        return Err(invalid());
    }
    bytes.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
    Ok(bytes)
}

pub fn decode_self_iteration_preparation_terminal_v1(
    bytes: &[u8],
) -> Result<(SelfIterationPreparationFactsV1, SignedLearningEvidenceV1), ProductEvaluationError> {
    if bytes.len() < 48
        || bytes.len() > MAX_SELF_ITERATION_PREPARATION_TERMINAL_BYTES_V1
        || !bytes.starts_with(b"HPTSPT01")
    {
        return Err(invalid());
    }
    let facts_len = u32::from_be_bytes(bytes[8..12].try_into().map_err(|_| invalid())?) as usize;
    let evidence_len =
        u32::from_be_bytes(bytes[12..16].try_into().map_err(|_| invalid())?) as usize;
    let end = 16usize
        .checked_add(facts_len)
        .and_then(|n| n.checked_add(evidence_len))
        .ok_or_else(invalid)?;
    if facts_len > MAX_SELF_ITERATION_PREPARATION_FACTS_BYTES_V1
        || end.checked_add(32) != Some(bytes.len())
        || Digest32::of_bytes(&bytes[..end]).as_array() != &bytes[end..]
    {
        return Err(invalid());
    }
    let facts = decode_self_iteration_preparation_facts_v1(&bytes[16..16 + facts_len])?;
    let evidence =
        crate::decode_untrusted_plasticity_learning_evidence_v1(&bytes[16 + facts_len..end])?;
    if encode_self_iteration_preparation_terminal_v1(&facts, &evidence)? != bytes {
        return Err(invalid());
    }
    Ok((facts, evidence))
}

fn invalid() -> ProductEvaluationError {
    ProductEvaluationError::Integrity("whole original preparation terminal facts")
}

#[cfg(test)]
#[path = "self_iteration_preparation_tests.rs"]
mod tests;
