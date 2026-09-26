//! Authenticated intuition gate on the canonical Agentd serving path.
//!
//! The canonical seven-owner runner may retain its historical advisory stage for
//! replay compatibility, but a configured product host must authenticate the
//! current V3 evidence, durably append a selected Decision, and agree with that
//! advisory result before Agentd admits or returns the physical run outcome.

use codex_hepta_intelligence::AdvisoryDecisionV1;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::ProductionDispositionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::intelligence_ingress::AgentdIntuitionProductInvocationV1;
use crate::intelligence_product::AgentdIntelligenceProductOutcomeV1;
use crate::intuition_policy::AgentdIntuitionDecisionReceiptV2;
use crate::state::AgentdState;

#[allow(clippy::too_many_arguments)]
pub(crate) fn authenticate_canonical_intuition(
    state: &AgentdState,
    product: Option<AgentdIntuitionProductInvocationV1>,
    request: CalibratedDecisionRequestV1,
    episode_id: StableId,
    run_snapshot_digest: Digest32,
    canonical: &AgentdIntelligenceProductOutcomeV1,
    now: u64,
) -> Result<Option<AgentdIntuitionDecisionReceiptV2>, AgentdError> {
    let host_configured = state.intuition_policy.get().is_some();
    let product = match (host_configured, product) {
        (false, None) => return Ok(None),
        (true, Some(product)) => product,
        (true, None) => {
            return Err(AgentdError::Invalid(
                "configured intuition product host requires authenticated invocation material"
                    .to_string(),
            ));
        }
        (false, Some(_)) => {
            return Err(AgentdError::Invalid(
                "authenticated intuition invocation material requires a configured product host"
                    .to_string(),
            ));
        }
    };

    let AgentdIntuitionProductInvocationV1 {
        profile,
        scoring,
        assignment,
        completeness_evidence,
        profile_qualification_evidence,
        runtime_evidence,
        expected_ledger_head,
        decision_evidence,
    } = product;
    let policy_prepared = {
        let qualification = IntuitionQualificationEvidenceV2 {
            completeness: &completeness_evidence,
            profile_qualification: &profile_qualification_evidence,
            runtime: &runtime_evidence,
        };
        state
            .prepare_intuition_policy_v3(
                request,
                profile,
                scoring,
                assignment,
                qualification,
                episode_id,
                run_snapshot_digest,
                now,
            )
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "authenticated intuition preparation failed: {}",
                    error.code()
                ))
            })?
    };
    require_outcome_parity(
        canonical,
        &policy_prepared.decision().decision.disposition,
        &policy_prepared.decision().decision.propensities,
    )?;

    let committed = state
        .commit_intuition_policy_v3(
            policy_prepared,
            expected_ledger_head,
            decision_evidence,
            now,
        )
        .map_err(|error| {
            AgentdError::Protocol(format!(
                "authenticated intuition commit failed: {}",
                error.code()
            ))
        })?;
    require_outcome_parity(
        canonical,
        &committed.decision.decision.disposition,
        &committed.decision.decision.propensities,
    )?;

    match &committed.decision.decision.disposition {
        ProductionDispositionV1::Selected(_) if committed.learning.is_none() => {
            return Err(AgentdError::Protocol(
                "selected intuition result reached serving without a durable Decision append"
                    .to_string(),
            ));
        }
        ProductionDispositionV1::Abstained(_) | ProductionDispositionV1::SlowPath(_)
            if committed.learning.is_some() =>
        {
            return Err(AgentdError::Protocol(
                "non-selected intuition result unexpectedly appended a Decision".to_string(),
            ));
        }
        _ => {}
    }
    Ok(Some(committed))
}

fn require_outcome_parity(
    canonical: &AgentdIntelligenceProductOutcomeV1,
    authenticated: &ProductionDispositionV1,
    propensities: &[codex_hepta_intuition::CalibratedCandidatePropensityV1],
) -> Result<(), AgentdError> {
    let matches = match canonical {
        AgentdIntelligenceProductOutcomeV1::Ready(prepared) => require_decision_parity(
            &prepared.envelope.decision.decision,
            authenticated,
            propensities,
        ),
        AgentdIntelligenceProductOutcomeV1::Abstained => {
            matches!(authenticated, ProductionDispositionV1::Abstained(_))
        }
        AgentdIntelligenceProductOutcomeV1::SlowPath => {
            matches!(authenticated, ProductionDispositionV1::SlowPath(_))
        }
    };
    if matches {
        Ok(())
    } else {
        Err(AgentdError::Protocol(
            "authenticated intuition result diverged from the canonical advisory stage".to_string(),
        ))
    }
}

fn require_decision_parity(
    canonical: &AdvisoryDecisionV1,
    authenticated: &ProductionDispositionV1,
    propensities: &[codex_hepta_intuition::CalibratedCandidatePropensityV1],
) -> bool {
    match (canonical, authenticated) {
        (
            AdvisoryDecisionV1::Selected {
                candidate_id,
                propensity,
            },
            ProductionDispositionV1::Selected(authenticated_id),
        ) if candidate_id == authenticated_id => propensities
            .iter()
            .find(|row| &row.candidate_id == authenticated_id)
            .is_some_and(|row| row.probability == *propensity),
        (AdvisoryDecisionV1::Abstained, ProductionDispositionV1::Abstained(_)) => true,
        (AdvisoryDecisionV1::SlowPath, ProductionDispositionV1::SlowPath(_)) => true,
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_intelligence::AdvisoryDecisionReceiptV1;
    use codex_hepta_intuition::CalibratedCandidatePropensityV1;
    use codex_hepta_intuition::ProductionSlowPathReasonV1;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::ProbabilityQ32;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn ready(decision: AdvisoryDecisionV1) -> AgentdIntelligenceProductOutcomeV1 {
        AgentdIntelligenceProductOutcomeV1::Ready(crate::PreparedAgentdIntelligenceRunV1 {
            envelope: codex_hepta_intelligence::IntelligenceHostEnvelopeV1 {
                run_id: id("run:parity"),
                objective_digest: Digest32::of_bytes(b"objective"),
                decision: AdvisoryDecisionReceiptV1 {
                    run_id: id("run:parity"),
                    candidate_set_digest: Digest32::of_bytes(b"set"),
                    intuition_receipt_digest: Digest32::of_bytes(b"intuition"),
                    decision,
                    decision_digest: Digest32::of_bytes(b"decision"),
                    authority: AuthorityPosture::DENY_ALL,
                },
                context_receipt_digest: Digest32::of_bytes(b"context"),
                evaluation_receipt_digest: Digest32::of_bytes(b"evaluation"),
                trace_digest: Digest32::of_bytes(b"trace"),
                envelope_digest: Digest32::of_bytes(b"envelope"),
                authority: AuthorityPosture::DENY_ALL,
            },
            dispatch_proposal_digest: Digest32::of_bytes(b"dispatch"),
            snapshot: unreachable_snapshot(),
            candidate_ids: Vec::new(),
            run_snapshot: unreachable_run_snapshot(),
            context_attachment: unreachable_context_attachment(),
        })
    }

    fn unreachable_snapshot() -> codex_hepta_intelligence::CanonicalIntelligenceSnapshotV1 {
        panic!("parity fixture must not inspect the canonical snapshot")
    }

    fn unreachable_run_snapshot() -> crate::AgentRunSnapshot {
        panic!("parity fixture must not inspect the run snapshot")
    }

    fn unreachable_context_attachment() -> crate::AgentContextAttachment {
        panic!("parity fixture must not inspect the context attachment")
    }

    #[test]
    fn decision_parity_requires_exact_selected_candidate_and_propensity() {
        let candidate = id("candidate:one");
        let canonical = AdvisoryDecisionV1::Selected {
            candidate_id: candidate.clone(),
            propensity: ProbabilityQ32::ONE,
        };
        let rows = vec![CalibratedCandidatePropensityV1 {
            candidate_id: candidate.clone(),
            probability: ProbabilityQ32::ONE,
        }];
        assert!(require_decision_parity(
            &canonical,
            &ProductionDispositionV1::Selected(candidate),
            &rows,
        ));
        assert!(!require_decision_parity(
            &canonical,
            &ProductionDispositionV1::Selected(id("candidate:two")),
            &rows,
        ));
    }

    #[test]
    fn terminal_outcome_parity_preserves_disposition_class() {
        assert!(
            require_outcome_parity(
                &AgentdIntelligenceProductOutcomeV1::SlowPath,
                &ProductionDispositionV1::SlowPath(
                    ProductionSlowPathReasonV1::ProfileRiskRule,
                ),
                &[],
            )
            .is_ok()
        );
        assert!(
            require_outcome_parity(
                &AgentdIntelligenceProductOutcomeV1::Abstained,
                &ProductionDispositionV1::SlowPath(
                    ProductionSlowPathReasonV1::ProfileRiskRule,
                ),
                &[],
            )
            .is_err()
        );
    }

    #[test]
    fn ready_outcome_uses_exact_advisory_selection() {
        let candidate = id("candidate:ready");
        let outcome = ready(AdvisoryDecisionV1::Selected {
            candidate_id: candidate.clone(),
            propensity: ProbabilityQ32::ONE,
        });
        let rows = vec![CalibratedCandidatePropensityV1 {
            candidate_id: candidate.clone(),
            probability: ProbabilityQ32::ONE,
        }];
        assert!(
            require_outcome_parity(
                &outcome,
                &ProductionDispositionV1::Selected(candidate),
                &rows,
            )
            .is_ok()
        );
    }
}
