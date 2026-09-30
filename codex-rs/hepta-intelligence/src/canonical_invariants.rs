//! Revalidation of the mutable canonical DTOs at product boundaries.
//!
//! Digests describe immutable semantics, not authority. Rebuild the legal set,
//! advisory decision, context binding and envelope before accepting a DTO. The
//! execution trace still requires the producing runner's provenance; this gate
//! does not authenticate an arbitrary caller merely because it can hash bytes.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AdvisoryDecisionV1;
use crate::AdvisoryDecisionReceiptV1;
use crate::CanonicalIntelligenceError;
use crate::CanonicalIntelligenceRunRequestV1;
use crate::CanonicalPortDecisionV1;
use crate::CanonicalPortReceiptV1;
use crate::CanonicalRunOutcomeV1;
use crate::CanonicalStageV1;
use crate::LegalActionCandidateSetRequestV1;
use crate::LegalActionCandidateSetV1;
use crate::assemble_context;
use crate::build_legal_candidates;
use crate::decide_boundary;

/// Recompute decision semantics without claiming owner provenance or membership.
/// Membership is checked against the legal set at admission and product use.
pub(super) fn advisory_decision_digest_v1(
    receipt: &AdvisoryDecisionReceiptV1,
) -> Result<Digest32, CanonicalIntelligenceError> {
    if receipt.authority.grants_any() {
        return Err(CanonicalIntelligenceError::AuthorityWidening);
    }
    if receipt.candidate_set_digest.is_zero() || receipt.intuition_receipt_digest.is_zero() {
        return Err(CanonicalIntelligenceError::EmptyDigest("decision"));
    }
    let mut bytes = b"hepta.intelligence.advisory-decision.v1\0".to_vec();
    push_id(&mut bytes, &receipt.run_id)?;
    bytes.extend_from_slice(receipt.candidate_set_digest.as_array());
    bytes.extend_from_slice(receipt.intuition_receipt_digest.as_array());
    match &receipt.decision {
        AdvisoryDecisionV1::Selected {
            candidate_id,
            propensity,
        } => {
            if propensity.raw() == 0 {
                return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                    "selected candidate propensity",
                ));
            }
            bytes.push(0);
            push_id(&mut bytes, candidate_id)?;
            bytes.extend_from_slice(&propensity.raw().to_be_bytes());
        }
        AdvisoryDecisionV1::Abstained => bytes.push(1),
        AdvisoryDecisionV1::SlowPath => bytes.push(2),
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), CanonicalIntelligenceError> {
    let raw = id.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

pub fn canonical_candidate_ids_v1(
    request: &LegalActionCandidateSetRequestV1,
) -> Result<Vec<StableId>, CanonicalIntelligenceError> {
    Ok(build_legal_candidates(request.clone())?
        .candidates
        .into_iter()
        .map(|candidate| candidate.candidate_id)
        .collect())
}

fn rebuild_legal(
    legal: &LegalActionCandidateSetV1,
) -> Result<LegalActionCandidateSetV1, CanonicalIntelligenceError> {
    if legal.authority.grants_any() {
        return Err(CanonicalIntelligenceError::AuthorityWidening);
    }
    let rebuilt = build_legal_candidates(LegalActionCandidateSetRequestV1 {
        candidate_set_id: legal.candidate_set_id.clone(),
        state_digest: legal.state_digest,
        generator_id: legal.generator_id.clone(),
        grammar_digest: legal.grammar_digest,
        candidates: legal.candidates.clone(),
        support_floor_ppm: legal.support_floor_ppm,
    })?;
    if rebuilt.candidate_set_digest != legal.candidate_set_digest {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "canonical candidate digest",
        ));
    }
    Ok(rebuilt)
}

pub fn validate_selected_candidate_v1(
    legal: &LegalActionCandidateSetV1,
    decision: &AdvisoryDecisionV1,
) -> Result<(), CanonicalIntelligenceError> {
    let legal = rebuild_legal(legal)?;
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

/// Validate a caller-retained outcome against the original admitted request.
/// In particular, changing a selected member to a *different legal member* is
/// still a semantic change and cannot retain the old decision/envelope digest.
pub fn validate_canonical_outcome_v1(
    request: &CanonicalIntelligenceRunRequestV1,
    outcome: &CanonicalRunOutcomeV1,
) -> Result<(), CanonicalIntelligenceError> {
    if request.legal_candidates.state_digest != request.snapshot.objective_digest() {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "objective/state binding",
        ));
    }
    let legal = build_legal_candidates(request.legal_candidates.clone())?;
    let (run_id, snapshot_digest, candidate_set_digest, decision, trace_digest, authority) =
        match outcome {
            CanonicalRunOutcomeV1::Ready(envelope) => (
                &envelope.run_id,
                envelope.snapshot_digest,
                envelope.candidate_set_digest,
                &envelope.decision,
                envelope.trace_digest,
                envelope.authority,
            ),
            CanonicalRunOutcomeV1::Abstained(terminal)
            | CanonicalRunOutcomeV1::SlowPath(terminal) => (
                &terminal.run_id,
                terminal.snapshot_digest,
                terminal.candidate_set_digest,
                &terminal.decision,
                terminal.trace_digest,
                terminal.authority,
            ),
        };
    if run_id != &request.run_id || decision.run_id != request.run_id {
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
    if authority.grants_any() || decision.authority.grants_any() {
        return Err(CanonicalIntelligenceError::AuthorityWidening);
    }
    if trace_digest.is_zero() {
        return Err(CanonicalIntelligenceError::EmptyDigest("trace"));
    }
    validate_selected_candidate_v1(&legal, &decision.decision)?;
    let port_decision = match &decision.decision {
        AdvisoryDecisionV1::Selected {
            candidate_id,
            propensity,
        } => CanonicalPortDecisionV1::Selected {
            candidate_id: candidate_id.clone(),
            propensity: *propensity,
        },
        AdvisoryDecisionV1::Abstained => CanonicalPortDecisionV1::Abstained,
        AdvisoryDecisionV1::SlowPath => CanonicalPortDecisionV1::SlowPath,
    };
    let intuition = CanonicalPortReceiptV1 {
        stage: CanonicalStageV1::IntuitionDecided,
        producer: owner_id("intuition.policy")?,
        snapshot_digest,
        predecessor_digest: legal.candidate_set_digest,
        output_digest: decision.intuition_receipt_digest,
        decision: port_decision,
        authority: decision.authority,
    };
    if &decide_boundary(&request.run_id, &legal, &intuition)? != decision {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "decision digest",
        ));
    }
    match (outcome, &decision.decision) {
        (CanonicalRunOutcomeV1::Abstained(_), AdvisoryDecisionV1::Abstained)
        | (CanonicalRunOutcomeV1::SlowPath(_), AdvisoryDecisionV1::SlowPath) => Ok(()),
        (CanonicalRunOutcomeV1::Ready(envelope), AdvisoryDecisionV1::Selected { .. }) => {
            if envelope.objective_digest != request.snapshot.objective_digest() {
                return Err(CanonicalIntelligenceError::SnapshotMismatch);
            }
            let context = CanonicalPortReceiptV1 {
                stage: CanonicalStageV1::ContextCompiled,
                producer: owner_id("context.compiler")?,
                snapshot_digest,
                predecessor_digest: decision.intuition_receipt_digest,
                output_digest: envelope.context_receipt_digest,
                decision: CanonicalPortDecisionV1::Continue,
                authority: envelope.authority,
            };
            if assemble_context(decision, &context)?.assembly_digest
                != envelope.context_binding_digest
            {
                return Err(CanonicalIntelligenceError::PredecessorMismatch);
            }
            let digests = [
                snapshot_digest,
                envelope.objective_digest,
                candidate_set_digest,
                envelope.utility_receipt_digest,
                envelope.neural_receipt_digest,
                envelope.prompt_receipt_digest,
                decision.decision_digest,
                envelope.context_receipt_digest,
                envelope.context_binding_digest,
                envelope.evaluation_receipt_digest,
                trace_digest,
            ];
            if digests.iter().any(|value| value.is_zero()) {
                return Err(CanonicalIntelligenceError::EmptyDigest(
                    "envelope dependency",
                ));
            }
            let mut bytes = b"hepta.intelligence.host-envelope.v1\0".to_vec();
            let raw = run_id.as_str().as_bytes();
            let length =
                u32::try_from(raw.len()).map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
            bytes.extend_from_slice(&length.to_be_bytes());
            bytes.extend_from_slice(raw);
            for digest in digests {
                bytes.extend_from_slice(digest.as_array());
            }
            if Digest32::of_bytes(&bytes) != envelope.envelope_digest {
                return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                    "envelope digest",
                ));
            }
            Ok(())
        }
        _ => Err(CanonicalIntelligenceError::UnexpectedDecision),
    }
}

fn owner_id(value: &str) -> Result<StableId, CanonicalIntelligenceError> {
    StableId::new(value).map_err(|_| CanonicalIntelligenceError::Arithmetic)
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::ProbabilityQ32;

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

    #[test]
    fn membership_gate_rejects_mutated_legal_support() {
        let mut legal = build_legal_candidates(candidates(&["action.a"])).expect("candidate set");
        legal.candidates[0].support_digest = digest("different support");
        assert!(validate_selected_candidate_v1(&legal, &AdvisoryDecisionV1::Abstained).is_err());
    }
}
