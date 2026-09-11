//! Complete request commitments for calibrated intuition receipts.
//!
//! Artifact digests retain their meaning as references to external artifacts.
//! Binding their supplied metadata prevents substitution under one V2 receipt;
//! it does not establish that metadata matches the artifact bytes. The host
//! must authenticate those artifacts and the random source independently.

use super::*;

/// Commit to every supplied request field, including the ordered candidates,
/// artifact metadata, assignment mode, random stream and exact draw.
///
/// This is a bounded encoding for host signatures and replay. Decision-time
/// validation still checks canonical order, artifact windows and probabilities.
pub fn canonical_calibrated_request_digest_v1(
    request: &CalibratedDecisionRequestV1,
) -> Result<Digest32, CalibratedError> {
    if !(1..=MAX_CANDIDATES).contains(&request.candidates.len()) {
        return Err(CalibratedError::CandidateCountOutOfRange);
    }
    let mut bytes = b"hepta.intuition.calibrated-request.v1".to_vec();
    push_id(&mut bytes, &request.decision_id)?;
    for digest in [
        request.objective_digest,
        request.objective_class_digest,
        request.state_digest,
        request.policy_digest,
        canonical_candidate_set_digest_v1(&request.candidates)?,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&request.sequence.to_be_bytes());
    bytes.extend_from_slice(&request.minimum_confidence.raw().to_be_bytes());
    bytes.extend_from_slice(&request.maximum_ece_ppm.to_be_bytes());
    bytes.extend_from_slice(&request.maximum_ood_false_acceptance_ppm.to_be_bytes());
    bytes.push(risk_code(request.risk_class));

    let completeness = &request.completeness;
    for digest in [
        completeness.receipt_digest,
        completeness.generator_digest,
        completeness.grammar_digest,
        completeness.hard_filter_digest,
        completeness.truncation_digest,
        completeness.candidate_set_digest,
        completeness.canonical_order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&completeness.candidate_count.to_be_bytes());
    bytes.extend_from_slice(&completeness.omitted_count_bound.to_be_bytes());

    let calibration = &request.calibration;
    for digest in [
        calibration.artifact_digest,
        calibration.policy_digest,
        calibration.objective_class_digest,
        calibration.subgroup_audit_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&calibration.generation.to_be_bytes());
    bytes.extend_from_slice(&calibration.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&calibration.expires_after_sequence.to_be_bytes());
    bytes.extend_from_slice(&calibration.measured_ece_ppm.to_be_bytes());

    let ood = &request.ood;
    for digest in [
        ood.artifact_digest,
        ood.policy_digest,
        ood.detector_digest,
        ood.support_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&ood.generation.to_be_bytes());
    bytes.extend_from_slice(&ood.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&ood.expires_after_sequence.to_be_bytes());
    bytes.extend_from_slice(&ood.maximum_in_domain_score.raw().to_be_bytes());
    bytes.extend_from_slice(&ood.measured_false_acceptance_ppm.to_be_bytes());
    match &request.assignment {
        AssignmentModeV1::Deterministic => bytes.push(0),
        AssignmentModeV1::CounterBased {
            random_stream_digest,
            draw,
            abstain_probability,
        } => {
            bytes.push(1);
            bytes.extend_from_slice(random_stream_digest.as_array());
            bytes.extend_from_slice(&draw.raw().to_be_bytes());
            bytes.extend_from_slice(&abstain_probability.raw().to_be_bytes());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Apply the existing calibrated policy with a receipt bound to the complete
/// request. Output fields retain the V1 shape; the receipt uses a V2 domain.
/// [`decide_calibrated`] remains available for replaying historical V1 receipts.
pub fn decide_calibrated_v2(
    request: CalibratedDecisionRequestV1,
) -> Result<CalibratedIntuitionReceiptV1, CalibratedError> {
    let request_digest = canonical_calibrated_request_digest_v1(&request)?;
    let mut receipt = decide_calibrated(request)?;
    let mut bytes = b"hepta.intuition.calibrated-decision.v2".to_vec();
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(receipt.receipt_digest.as_array());
    receipt.receipt_digest = Digest32::of_bytes(&bytes);
    Ok(receipt)
}
