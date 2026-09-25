//! Signing proposal for publication through the existing evidence owner.
//! Proposal bytes are not a persisted qualification receipt or an authority.
use super::*;

/// Exact terminal bytes an evidence owner must durably publish. This encoder
/// grants nothing and never constructs a product qualification receipt.
pub fn product_qualification_publication_payload_v1(
    execution_digest: Digest32,
    decision: &SignedEvaluationDecisionV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    if execution_digest.is_zero()
        || decision.decision.evidence_digest.is_zero()
        || decision.trust_digest.is_zero()
        || decision.authentication_digest.is_zero()
        || decision.decision.authority.grants_any()
        || decision.decision.failed_metrics.len() > 128
    {
        return Err(ProductEvaluationError::Integrity("publication proposal"));
    }
    let mut bytes = b"hepta.intelligence-eval.terminal-publication.v1".to_vec();
    bytes.extend_from_slice(execution_digest.as_array());
    push_signed_evaluation_decision(&mut bytes, decision);
    Ok(bytes)
}

impl<S: FinalHoldoutCasStoreV1> ProductEvaluationRunnerV1<S> {
    /// Prepare the exact evidence-owner signing payload, without publishing or
    /// returning qualification. The host durably retains the signed publication
    /// intent, then calls `qualify_and_persist` with fresh current trust/time.
    /// That call reauthenticates everything and its sink must compare the exact
    /// bytes; a proposal cannot extend an attestation's lifetime.
    #[allow(clippy::too_many_arguments)]
    pub fn qualification_publication_payload(
        &self,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<Vec<u8>, ProductEvaluationError> {
        let bundle = self.qualification_bundle(temporal, context)?;
        let decision = verify_qualification(
            bundle,
            temporal.product_plan.metric_roles.clone(),
            evidence,
            timing,
            verifier,
            now,
        )?;
        product_qualification_publication_payload_v1(temporal.execution_digest, &decision)
    }
}

pub(super) fn verify_qualification(
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    timing: ProductTimingEvidenceV1<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedEvaluationDecisionV1, ProductEvaluationError> {
    match timing {
        ProductTimingEvidenceV1::Qualification => {
            if bundle.claim_scope != EvaluationClaimScopeV1::Qualification {
                return Err(ProductEvaluationError::Binding("qualification scope"));
            }
            Ok(decide_with_signed_evidence_v2(
                bundle, roles, evidence, verifier, now,
            )?)
        }
        ProductTimingEvidenceV1::SystemLongitudinal {
            timing,
            minimum_window_micros,
        } => {
            if bundle.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal {
                return Err(ProductEvaluationError::Binding("longitudinal scope"));
            }
            Ok(decide_with_signed_longitudinal_evidence_v3(
                bundle,
                roles,
                evidence,
                timing,
                minimum_window_micros,
                verifier,
                now,
            )?)
        }
    }
}
