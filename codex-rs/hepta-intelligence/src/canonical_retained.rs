//! Read validation of an original preparation. No stage, decision or selection
//! is executed and no replacement receipt is produced. Callers still need the
//! original storage owner and current seven-owner freshness checks.

use super::*;

pub fn validate_retained_envelope_v1(request: &CanonicalIntelligenceRunRequestV1,
    envelope: &IntelligenceHostEnvelopeV1) -> Result<(), CanonicalIntelligenceError> {
    request.budget.validate()?;
    let snapshot = &request.snapshot;
    if request.run_id != envelope.run_id || snapshot.digest() != envelope.snapshot_digest
        || snapshot.objective_digest() != envelope.objective_digest
        || envelope.authority.grants_any() || envelope.decision.authority.grants_any() {
        return Err(CanonicalIntelligenceError::SnapshotMismatch);
    }
    let legal = &request.legal_candidates;
    if legal.generator_id.as_str() != "intelligence.control" || legal.state_digest != snapshot.objective_digest()
        || legal.grammar_digest.is_zero() || legal.candidates.is_empty() || legal.candidates.len() > MAX_CANDIDATES
        || legal.support_floor_ppm > MAX_SUPPORT_FLOOR_PPM {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet("retained legal candidates"));
    }
    let mut candidates = legal.candidates.iter().collect::<Vec<_>>();
    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut bytes = b"hepta.intelligence.legal-action-candidate-set.v1\0".to_vec();
    push_id(&mut bytes, &legal.candidate_set_id)?;
    bytes.extend_from_slice(legal.state_digest.as_array());
    push_id(&mut bytes, &legal.generator_id)?;
    bytes.extend_from_slice(legal.grammar_digest.as_array());
    bytes.extend_from_slice(&legal.support_floor_ppm.to_be_bytes());
    let mut seen = BTreeSet::new();
    for candidate in &candidates {
        if candidate.support_digest.is_zero() || !seen.insert(candidate.candidate_id.clone()) {
            return Err(CanonicalIntelligenceError::InvalidCandidateSet("retained duplicate or unsupported candidate"));
        }
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    if Digest32::of_bytes(&bytes) != envelope.candidate_set_digest { return Err(CanonicalIntelligenceError::SnapshotMismatch); }
    let stages = [CanonicalStageV1::ObjectiveValidated, CanonicalStageV1::UtilityEvaluated,
        CanonicalStageV1::NeuralSignalCollected, CanonicalStageV1::PromptPortfolioBuilt,
        CanonicalStageV1::IntuitionDecided, CanonicalStageV1::ContextCompiled, CanonicalStageV1::EvaluationAdmitted];
    if envelope.stage_trace.len() != stages.len() { return Err(CanonicalIntelligenceError::StageMismatch); }
    let expected_outputs = [None, Some(envelope.utility_receipt_digest), Some(envelope.neural_receipt_digest),
        Some(envelope.prompt_receipt_digest), Some(envelope.decision.intuition_receipt_digest),
        Some(envelope.context_receipt_digest), Some(envelope.evaluation_receipt_digest)];
    let mut predecessor = envelope.candidate_set_digest;
    for ((trace, stage), expected) in envelope.stage_trace.iter().zip(stages).zip(expected_outputs) {
        if trace.stage != stage || trace.producer.as_str() != stage.owner() || trace.predecessor_digest != predecessor
            || trace.output_digest.is_zero() || expected.is_some_and(|expected| trace.output_digest != expected) {
            return Err(CanonicalIntelligenceError::StageMismatch);
        }
        predecessor = trace.output_digest;
    }
    if digest_trace(&request.run_id, snapshot.digest(), envelope.candidate_set_digest, &envelope.stage_trace)? != envelope.trace_digest {
        return Err(CanonicalIntelligenceError::SnapshotMismatch);
    }
    let decision = &envelope.decision;
    let AdvisoryDecisionV1::Selected { candidate_id, propensity } = &decision.decision else {
        return Err(CanonicalIntelligenceError::UnexpectedDecision);
    };
    if decision.run_id != request.run_id || decision.candidate_set_digest != envelope.candidate_set_digest
        || !seen.contains(candidate_id) || propensity.raw() == 0 {
        return Err(CanonicalIntelligenceError::UnexpectedDecision);
    }
    let mut bytes = b"hepta.intelligence.advisory-decision.v1\0".to_vec();
    push_id(&mut bytes, &request.run_id)?;
    bytes.extend_from_slice(envelope.candidate_set_digest.as_array());
    bytes.extend_from_slice(decision.intuition_receipt_digest.as_array());
    bytes.push(0);
    push_id(&mut bytes, candidate_id)?;
    bytes.extend_from_slice(&propensity.raw().to_be_bytes());
    if Digest32::of_bytes(&bytes) != decision.decision_digest { return Err(CanonicalIntelligenceError::SnapshotMismatch); }
    let mut bytes = b"hepta.intelligence.context-boundary.v1\0".to_vec();
    push_id(&mut bytes, &request.run_id)?;
    bytes.extend_from_slice(decision.decision_digest.as_array());
    bytes.extend_from_slice(envelope.context_receipt_digest.as_array());
    if Digest32::of_bytes(&bytes) != envelope.context_binding_digest { return Err(CanonicalIntelligenceError::SnapshotMismatch); }
    let mut bytes = b"hepta.intelligence.host-envelope.v1\0".to_vec();
    push_id(&mut bytes, &request.run_id)?;
    for digest in [snapshot.digest(), envelope.objective_digest, envelope.candidate_set_digest,
        envelope.utility_receipt_digest, envelope.neural_receipt_digest, envelope.prompt_receipt_digest,
        decision.decision_digest, envelope.context_receipt_digest, envelope.context_binding_digest,
        envelope.evaluation_receipt_digest, envelope.trace_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    if Digest32::of_bytes(&bytes) != envelope.envelope_digest { return Err(CanonicalIntelligenceError::SnapshotMismatch); }
    Ok(())
}
