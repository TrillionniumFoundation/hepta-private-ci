//! Readonly commitment preimages from actual sealed Product evidence.
//! There is deliberately no decoder or constructor for any old receipt seal.

use super::*;
use crate::closure::evaluation_bundle_commitment_bytes;
use crate::closure::evaluation_role_commitment_bytes;
use crate::revalidate_product_qualification_v1;

pub struct OriginalProductQualificationCommitmentsV1 {
    holdout: Vec<u8>,
    plan: Vec<u8>,
    request: Vec<u8>,
    decision: Vec<u8>,
    qualification: Vec<u8>,
    estimand: Vec<u8>,
    roles: Vec<u8>,
    evaluator_payload: Vec<u8>,
}

impl OriginalProductQualificationCommitmentsV1 {
    pub fn holdout(&self) -> &[u8] { &self.holdout }
    pub fn plan(&self) -> &[u8] { &self.plan }
    pub fn request(&self) -> &[u8] { &self.request }
    pub fn decision(&self) -> &[u8] { &self.decision }
    pub fn qualification(&self) -> &[u8] { &self.qualification }
    pub fn estimand(&self) -> &[u8] { &self.estimand }
    pub fn roles(&self) -> &[u8] { &self.roles }
    pub fn evaluator_payload(&self) -> &[u8] { &self.evaluator_payload }
    pub fn authority(&self) -> AuthorityPosture { AuthorityPosture::DENY_ALL }
}

impl<S: FinalHoldoutCasStoreV1> ProductEvaluationRunnerV1<S> {
    /// Only a concrete original host may export these existing preimages.
    /// Original qualification and execution owners must be physically read
    /// separately before and after this pure projection. No sink is accepted.
    pub fn original_qualification_commitments(
        &self,
        temporal: &ProductTemporalEvaluationReceiptV1,
        qualification: &ProductQualificationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<OriginalProductQualificationCommitmentsV1, ProductEvaluationError> {
        if qualification.claim_scope != EvaluationClaimScopeV1::Qualification
            || qualification.temporal_execution_digest != temporal.execution_digest
        {
            return Err(ProductEvaluationError::Binding("original Qualification material"));
        }
        let bundle = self.qualification_bundle(temporal, context)?;
        let roles = &temporal.product_plan.metric_roles;
        let decision = revalidate_product_qualification_v1(
            qualification, bundle.clone(), roles.clone(), evidence,
            ProductTimingEvidenceV1::Qualification, verifier, now,
        )?;
        if decision != qualification.decision {
            return Err(ProductEvaluationError::Binding("original full qualification decision"));
        }
        let plan = &temporal.product_plan;
        Ok(OriginalProductQualificationCommitmentsV1 {
            holdout: crate::closure::original_holdout_commitment_bytes(&plan.frozen_plan, &temporal.holdout.use_receipt)?,
            plan: product_plan_commitment_bytes(plan)?,
            request: evaluation_bundle_commitment_bytes(
                &bundle, IndependentEvaluationDispositionV1::InsufficientEvidence, &[],
            )?,
            decision: evaluation_bundle_commitment_bytes(
                &bundle, decision.decision.disposition, &decision.decision.failed_metrics,
            )?,
            qualification: product_qualification_commitment_bytes(qualification),
            estimand: product_estimand_commitment_bytes(
                plan.base_estimand_digest, plan.candidate_temporal_plan_digest,
                plan.baseline_temporal_plan_digest, &plan.metric_sources,
            )?,
            roles: evaluation_role_commitment_bytes(&bundle, roles)?,
            evaluator_payload: crate::evaluation_signing_payload_v2(&bundle, roles)?,
        })
    }
}
