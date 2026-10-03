//! A distinct E fact for an authenticated training contract incompatible with CURRENT.
//! Pure decoding grants no custody. No absent Generator/Observer facts are filled.
use crate::ProductEvaluationError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationServingScopeIncompatibleFactsV1 {
    pub round_identity_digest: Digest32,
    pub round_payload_digest: Digest32,
    pub canonical_policy_digest: Digest32,
    pub execution_envelope_digest: Digest32,
    pub enrolled_inputs_digest: Digest32,
    pub serving_observation_digest: Digest32,
    pub training_material_digest: Digest32,
    pub training_registration_digest: Digest32,
    pub registry_binding_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub registry_acknowledgement_digest: Digest32,
    pub serving_scope_digest: Digest32,
    pub serving_objective_digest: Digest32,
    pub training_scope_digest: Digest32,
    pub training_objective_digest: Digest32,
    pub expected_training_scope_digest: Digest32,
    pub expected_training_objective_digest: Digest32,
    pub configuration_digest: Digest32,
    pub body_bundle_digest: Digest32,
    pub neuron_generation: u64,
    /// The actual owner value; None preserves an actual fixed-scope owner.
    pub goal_ordinal: Option<u64>,
    pub admitted_at_ms: u64,
    pub deadline_ms: u64,
    pub observed_at_ms: u64,
}
const DOMAIN: &[u8] = b"hepta.self-iteration.serving-scope-incompatible.v1\0";
pub const MAX_SELF_ITERATION_SERVING_SCOPE_FACTS_BYTES_V1: usize = 1024;
pub const MAX_SELF_ITERATION_SERVING_SCOPE_TERMINAL_BYTES_V1: usize = 64 * 1024;

/// Sole original E signing preimage. The journal must match the sealed Round,
/// and the independent evaluator must inspect whole protected actual sources.
pub fn self_iteration_serving_scope_signing_payload_v1(
    facts: &SelfIterationServingScopeIncompatibleFactsV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    let digests = [
        facts.round_identity_digest,
        facts.round_payload_digest,
        facts.canonical_policy_digest,
        facts.execution_envelope_digest,
        facts.enrolled_inputs_digest,
        facts.serving_observation_digest,
        facts.training_material_digest,
        facts.training_registration_digest,
        facts.registry_binding_digest,
        facts.registry_head_digest,
        facts.registry_acknowledgement_digest,
        facts.serving_scope_digest,
        facts.serving_objective_digest,
        facts.training_scope_digest,
        facts.training_objective_digest,
        facts.expected_training_scope_digest,
        facts.expected_training_objective_digest,
        facts.configuration_digest,
        facts.body_bundle_digest,
    ];
    if digests.iter().any(|d| d.is_zero())
        || (facts.expected_training_scope_digest == facts.training_scope_digest
            && facts.expected_training_objective_digest == facts.training_objective_digest)
        || facts.neuron_generation == 0
        || facts.goal_ordinal == Some(0)
        || facts.admitted_at_ms == 0
        || facts.observed_at_ms < facts.admitted_at_ms
        || facts.observed_at_ms >= facts.deadline_ms
    {
        return Err(invalid());
    }
    let mut bytes = DOMAIN.to_vec();
    for d in digests {
        bytes.extend_from_slice(d.as_array());
    }
    bytes.extend_from_slice(&facts.neuron_generation.to_be_bytes());
    bytes.push(u8::from(facts.goal_ordinal.is_some()));
    bytes.extend_from_slice(&facts.goal_ordinal.unwrap_or(0).to_be_bytes());
    for t in [
        facts.admitted_at_ms,
        facts.deadline_ms,
        facts.observed_at_ms,
    ] {
        bytes.extend_from_slice(&t.to_be_bytes());
    }
    Ok(bytes)
}

pub fn decode_self_iteration_serving_scope_facts_v1(
    bytes: &[u8],
) -> Result<SelfIterationServingScopeIncompatibleFactsV1, ProductEvaluationError> {
    if bytes.len() != DOMAIN.len() + 19 * 32 + 5 * 8 + 1 || !bytes.starts_with(DOMAIN) {
        return Err(invalid());
    }
    let mut c = DOMAIN.len();
    let mut digest = || {
        let d = Digest32::from_array(bytes[c..c + 32].try_into().map_err(|_| invalid())?);
        c += 32;
        Ok::<_, ProductEvaluationError>(d)
    };
    let mut facts = SelfIterationServingScopeIncompatibleFactsV1 {
        round_identity_digest: digest()?,
        round_payload_digest: digest()?,
        canonical_policy_digest: digest()?,
        execution_envelope_digest: digest()?,
        enrolled_inputs_digest: digest()?,
        serving_observation_digest: digest()?,
        training_material_digest: digest()?,
        training_registration_digest: digest()?,
        registry_binding_digest: digest()?,
        registry_head_digest: digest()?,
        registry_acknowledgement_digest: digest()?,
        serving_scope_digest: digest()?,
        serving_objective_digest: digest()?,
        training_scope_digest: digest()?,
        training_objective_digest: digest()?,
        expected_training_scope_digest: digest()?,
        expected_training_objective_digest: digest()?,
        configuration_digest: digest()?,
        body_bundle_digest: digest()?,
        neuron_generation: 0,
        goal_ordinal: None,
        admitted_at_ms: 0,
        deadline_ms: 0,
        observed_at_ms: 0,
    };
    let generation = u64::from_be_bytes(bytes[c..c + 8].try_into().map_err(|_| invalid())?);
    c += 8;
    let tag = bytes[c];
    c += 1;
    let ordinal = u64::from_be_bytes(bytes[c..c + 8].try_into().map_err(|_| invalid())?);
    c += 8;
    facts.neuron_generation = generation;
    facts.goal_ordinal = match (tag, ordinal) {
        (0, 0) => None,
        (1, value) if value > 0 => Some(value),
        _ => return Err(invalid()),
    };
    let mut time = || {
        let t = u64::from_be_bytes(bytes[c..c + 8].try_into().map_err(|_| invalid())?);
        c += 8;
        Ok::<_, ProductEvaluationError>(t)
    };
    facts.admitted_at_ms = time()?;
    facts.deadline_ms = time()?;
    facts.observed_at_ms = time()?;
    if self_iteration_serving_scope_signing_payload_v1(&facts)? != bytes {
        return Err(invalid());
    }
    Ok(facts)
}

/// A full purpose-specific original terminal packet, not a generic signer.
pub fn encode_self_iteration_serving_scope_terminal_v1(
    facts: &SelfIterationServingScopeIncompatibleFactsV1,
    evaluator: &SignedLearningEvidenceV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    let facts = self_iteration_serving_scope_signing_payload_v1(facts)?;
    let evidence = crate::encode_untrusted_plasticity_learning_evidence_v1(evaluator)?;
    let mut bytes = b"HPTSSI01".to_vec();
    bytes.extend_from_slice(&(facts.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&(evidence.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&facts);
    bytes.extend_from_slice(&evidence);
    if bytes.len() + 32 > MAX_SELF_ITERATION_SERVING_SCOPE_TERMINAL_BYTES_V1 {
        return Err(invalid());
    }
    bytes.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
    Ok(bytes)
}
pub fn decode_self_iteration_serving_scope_terminal_v1(
    bytes: &[u8],
) -> Result<
    (
        SelfIterationServingScopeIncompatibleFactsV1,
        SignedLearningEvidenceV1,
    ),
    ProductEvaluationError,
> {
    if bytes.len() < 48
        || bytes.len() > MAX_SELF_ITERATION_SERVING_SCOPE_TERMINAL_BYTES_V1
        || !bytes.starts_with(b"HPTSSI01")
    {
        return Err(invalid());
    }
    let f = u32::from_be_bytes(bytes[8..12].try_into().map_err(|_| invalid())?) as usize;
    let e = u32::from_be_bytes(bytes[12..16].try_into().map_err(|_| invalid())?) as usize;
    let end = 16usize
        .checked_add(f)
        .and_then(|n| n.checked_add(e))
        .ok_or_else(invalid)?;
    if f > MAX_SELF_ITERATION_SERVING_SCOPE_FACTS_BYTES_V1
        || end.checked_add(32) != Some(bytes.len())
        || Digest32::of_bytes(&bytes[..end]).as_array() != &bytes[end..]
    {
        return Err(invalid());
    }
    let facts = decode_self_iteration_serving_scope_facts_v1(&bytes[16..16 + f])?;
    let evidence = crate::decode_untrusted_plasticity_learning_evidence_v1(&bytes[16 + f..end])?;
    if encode_self_iteration_serving_scope_terminal_v1(&facts, &evidence)? != bytes {
        return Err(invalid());
    }
    Ok((facts, evidence))
}
fn invalid() -> ProductEvaluationError {
    ProductEvaluationError::Integrity("actual whole Serving scope incompatibility facts")
}
#[cfg(test)]
#[path = "self_iteration_serving_scope_tests.rs"]
mod tests;
