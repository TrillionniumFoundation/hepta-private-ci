//! A partial negative result cannot certify a complete comparison. These
//! mechanism fixtures retain frozen metric roles and the known failed metric;
//! they supply no deployed task, independent measurement or adoption evidence.

use super::*;
use pretty_assertions::assert_eq;

#[test]
fn known_failure_keeps_missing_evidence_unknown_under_both_claim_scopes()
-> Result<(), EvaluationClosureError> {
    for scope in [
        EvaluationClaimScopeV1::Qualification,
        EvaluationClaimScopeV1::SystemLongitudinal,
    ] {
        let (mut complete, roles) = mixed_role_bundle()?;
        complete.claim_scope = scope;
        let mut frozen = plan();
        frozen.claim_scope = scope;
        frozen.metric_contracts = metric_contracts(&complete.metrics);
        frozen.simultaneous_comparisons = complete.simultaneous_comparisons;
        complete.frozen_plan = freeze_cross_fold_plan_v2(frozen, roles.clone())?;
        complete.holdout_use = FinalHoldoutRegistry::new().consume(&complete.frozen_plan)?;
        let eligible = decide_independently_v2(complete.clone(), roles.clone(), 50)?;
        assert_eq!(
            (
                eligible.disposition,
                eligible.failed_metrics,
                eligible.authority
            ),
            (
                IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
                Vec::new(),
                AuthorityPosture::DENY_ALL,
            )
        );

        // The primary metric now fails both superiority and its safety floor.
        // Every other metric remains within its preregistered constraints.
        complete.metrics[0].candidate.lower = FixedQ32::from_raw(69);
        let negative = decide_independently_v2(complete.clone(), roles.clone(), 50)?;
        assert_eq!(
            (
                &negative.disposition,
                &negative.failed_metrics,
                negative.authority
            ),
            (
                &IndependentEvaluationDispositionV1::Ineligible,
                &vec![id("task-utility")],
                AuthorityPosture::DENY_ALL,
            )
        );

        for missing in ["metric-support", "snapshot", "future-window"] {
            let mut incomplete = complete.clone();
            match missing {
                "metric-support" => incomplete.metrics[1].support_digest = Digest32::ZERO,
                "snapshot" => incomplete.snapshot_ids.clear(),
                "future-window" => incomplete.future_window_ids.clear(),
                _ => unreachable!(),
            }
            let decision = decide_independently_v2(incomplete, roles.clone(), 50)?;
            assert_eq!(
                (
                    decision.disposition,
                    decision.failed_metrics,
                    decision.authority
                ),
                (
                    IndependentEvaluationDispositionV1::InsufficientEvidence,
                    vec![id("task-utility")],
                    AuthorityPosture::DENY_ALL,
                ),
                "{scope:?}: missing {missing}"
            );
            assert_ne!(decision.evidence_digest, negative.evidence_digest);
        }
        // Rechecking complete original evidence keeps the complete negative
        // result. Insufficiency never erases or restamps the original result.
        assert_eq!(decide_independently_v2(complete, roles, 50)?, negative);
    }
    Ok(())
}

#[test]
fn known_failure_does_not_replace_longitudinal_retention_or_unlearning()
-> Result<(), EvaluationClosureError> {
    let (mut complete, roles) = mixed_role_bundle()?;
    complete.metrics[2].candidate.upper = FixedQ32::from_raw(101);
    let negative = decide_independently_v2(complete.clone(), roles.clone(), 50)?;
    assert_eq!(
        (&negative.disposition, &negative.failed_metrics),
        (
            &IndependentEvaluationDispositionV1::Ineligible,
            &vec![id("resource-cost")],
        )
    );
    for missing in ["retention", "unlearning"] {
        let mut incomplete = complete.clone();
        match missing {
            "retention" => incomplete.retention_receipt_digests.clear(),
            "unlearning" => incomplete.unlearning_receipt_digest = Digest32::ZERO,
            _ => unreachable!(),
        }
        let decision = decide_independently_v2(incomplete, roles.clone(), 50)?;
        assert_eq!(
            (
                decision.disposition,
                decision.failed_metrics,
                decision.authority
            ),
            (
                IndependentEvaluationDispositionV1::InsufficientEvidence,
                vec![id("resource-cost")],
                AuthorityPosture::DENY_ALL,
            ),
            "missing {missing}"
        );
        assert_ne!(decision.evidence_digest, negative.evidence_digest);
    }
    Ok(())
}

#[test]
fn legacy_negative_evaluation_also_requires_complete_evidence() -> Result<(), EvaluationClosureError>
{
    let mut complete = bundle();
    complete.metrics[0].candidate.lower = FixedQ32::from_raw(69);
    let negative = decide_independently(complete.clone(), 50)?;
    assert_eq!(
        negative.disposition,
        IndependentEvaluationDispositionV1::Ineligible
    );
    complete.retention_receipt_digests.clear();
    let decision = decide_independently(complete, 50)?;
    assert_eq!(
        (
            decision.disposition,
            decision.failed_metrics,
            decision.authority
        ),
        (
            IndependentEvaluationDispositionV1::InsufficientEvidence,
            vec![id("task-utility")],
            AuthorityPosture::DENY_ALL,
        )
    );
    assert_ne!(decision.evidence_digest, negative.evidence_digest);
    Ok(())
}
