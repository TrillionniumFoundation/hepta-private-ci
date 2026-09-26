//! Defense-in-depth invariants for the canonical intelligence product boundary.
//!
//! The historical canonical facade remains source compatible, while product
//! callers use these checks before publishing a prepared envelope.  The checks
//! deliberately rebuild the legal candidate set so raw caller ordering cannot
//! substitute a different semantic set.

use codex_hepta_types::StableId;

use crate::AdvisoryDecisionV1;
use crate::CanonicalIntelligenceError;
use crate::CanonicalIntelligenceRunRequestV1;
use crate::CanonicalRunOutcomeV1;
use crate::LegalActionCandidateSetRequestV1;
use crate::LegalActionCandidateSetV1;
use crate::build_legal_candidates;

/// Return the canonical candidate identity order after the normal candidate-set
/// admission checks have run.
pub fn canonical_candidate_ids_v1(
    request: &LegalActionCandidateSetRequestV1,
) -> Result<Vec<StableId>, CanonicalIntelligenceError> {
    let admitted = build_legal_candidates(request.clone())?;
    Ok(admitted
        .candidates
        .into_iter()
        .map(|candidate| candidate.candidate_id)
        .collect())
}

/// Prove that a selected advisory decision names a member of the admitted legal
/// set and carries a non-zero propensity.  Abstain and slow-path decisions do
/// not select a candidate and therefore pass this membership check.
pub fn validate_selected_candidate_v1(
    legal: &LegalActionCandidateSetV1,
    decision: &AdvisoryDecisionV1,
) -> Result<(), CanonicalIntelligenceError> {
    let AdvisoryDecisionV1::Selected {
        candidate_id,
        propensity,
    } = decision
    else {
        return Ok(());
    };
    if propensity.raw() == 0 {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "selected candidate propensity",
        ));
    }
    if !legal
        .candidates
        .iter()
        .any(|candidate| &candidate.candidate_id == candidate_id)
    {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "selected candidate membership",
        ));
    }
    Ok(())
}

/// Rebuild and compare the canonical candidate-set digest, then validate the
/// terminal outcome's run/snapshot/decision bindings.  This is the last pure
/// invariant gate before Agentd derives a dispatch proposal.
pub fn validate_canonical_outcome_v1(
    request: &CanonicalIntelligenceRunRequestV1,
    outcome: &CanonicalRunOutcomeV1,
) -> Result<(), CanonicalIntelligenceError> {
    let legal = build_legal_candidates(request.legal_candidates.clone())?;
    let (run_id, snapshot_digest, candidate_set_digest, decision) = match outcome {
        CanonicalRunOutcomeV1::Ready(envelope) => (
            &envelope.run_id,
            envelope.snapshot_digest,
            envelope.candidate_set_digest,
            &envelope.decision,
        ),
        CanonicalRunOutcomeV1::Abstained(terminal) | CanonicalRunOutcomeV1::SlowPath(terminal) => (
            &terminal.run_id,
            terminal.snapshot_digest,
            terminal.candidate_set_digest,
            &terminal.decision,
        ),
    };
    if run_id != &request.run_id {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "run identity",
        ));
    }
    if snapshot_digest != request.snapshot.digest() {
        return Err(CanonicalIntelligenceError::SnapshotMismatch);
    }
    if candidate_set_digest != legal.candidate_set_digest
        || decision.candidate_set_digest != legal.candidate_set_digest
    {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "canonical candidate digest",
        ));
    }
    validate_selected_candidate_v1(&legal, &decision.decision)?;
    match (outcome, &decision.decision) {
        (CanonicalRunOutcomeV1::Ready(_), AdvisoryDecisionV1::Selected { .. })
        | (CanonicalRunOutcomeV1::Abstained(_), AdvisoryDecisionV1::Abstained)
        | (CanonicalRunOutcomeV1::SlowPath(_), AdvisoryDecisionV1::SlowPath) => Ok(()),
        _ => Err(CanonicalIntelligenceError::UnexpectedDecision),
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::ProbabilityQ32;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::LegalActionCandidateV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn candidates(order: &[&str]) -> LegalActionCandidateSetRequestV1 {
        LegalActionCandidateSetRequestV1 {
            candidate_set_id: id("set.canonical"),
            state_digest: digest("state"),
            generator_id: id("intelligence.control"),
            grammar_digest: digest("grammar"),
            candidates: order
                .iter()
                .map(|value| LegalActionCandidateV1 {
                    candidate_id: id(value),
                    support_digest: digest(&format!("support:{value}")),
                })
                .collect(),
            support_floor_ppm: 1,
        }
    }

    #[test]
    fn raw_candidate_order_does_not_change_canonical_identity() {
        let left = build_legal_candidates(candidates(&["action.b", "action.a"]))
            .expect("left candidate set");
        let right = build_legal_candidates(candidates(&["action.a", "action.b"]))
            .expect("right candidate set");
        assert_eq!(left.candidates, right.candidates);
        assert_eq!(left.candidate_set_digest, right.candidate_set_digest);
    }

    #[test]
    fn malicious_selected_candidate_outside_legal_set_is_rejected() {
        let legal = build_legal_candidates(candidates(&["action.a"])).expect("candidate set");
        let decision = AdvisoryDecisionV1::Selected {
            candidate_id: id("action.outside"),
            propensity: ProbabilityQ32::ONE,
        };
        assert_eq!(
            validate_selected_candidate_v1(&legal, &decision),
            Err(CanonicalIntelligenceError::InvalidCandidateSet(
                "selected candidate membership"
            ))
        );
    }

    #[test]
    fn zero_propensity_selection_is_rejected() {
        let legal = build_legal_candidates(candidates(&["action.a"])).expect("candidate set");
        let decision = AdvisoryDecisionV1::Selected {
            candidate_id: id("action.a"),
            propensity: ProbabilityQ32::ZERO,
        };
        assert_eq!(
            validate_selected_candidate_v1(&legal, &decision),
            Err(CanonicalIntelligenceError::InvalidCandidateSet(
                "selected candidate propensity"
            ))
        );
    }
}
