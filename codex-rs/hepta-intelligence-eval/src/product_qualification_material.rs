//! Complete bounded publication material. Encoding is persistence, not evidence
//! admission. Only the original owner can supply the sealed execution receiver;
//! publication still requires current signature checks and a durable witness.

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::ProductEvaluationExecutionMaterialV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::HoldoutUseDispositionV1;
use crate::IndependentEvaluationBundleV1;
use crate::IndependentEvaluationDispositionV1;
use crate::MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 as LIMIT;
use crate::MetricRoleV2;
use crate::ProductEvaluationError;
use crate::ProductMetricSourceV1;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationEvidenceV1;
use crate::TemporalEvaluationPlan;
use crate::closure::encode_holdout_plan;
use crate::closure::encode_holdout_use;

/// Complete encoding inputs, with no signing, storage or selection authority.
/// The original owner derives `bundle` and `decision` again before persisting.
pub struct ProductQualificationPublicationMaterialV1<'a> {
    pub candidate_plan: &'a TemporalEvaluationPlan,
    pub baseline_plan: &'a TemporalEvaluationPlan,
    pub bundle: &'a IndependentEvaluationBundleV1,
    pub evidence: &'a SignedEvaluationEvidenceV1,
    pub decision: &'a SignedEvaluationDecisionV1,
    pub publication_binding: Digest32,
    pub recorded_at: u64,
}

impl ProductEvaluationExecutionMaterialV1 {
    /// Encode the full original material within the unchanged owner-record cap.
    /// A later verification time is deliberately absent from this identity.
    pub fn qualification_record_bytes(
        &self,
        input: &ProductQualificationPublicationMaterialV1<'_>,
    ) -> Result<Vec<u8>, ProductEvaluationError> {
        let plan = &self.execution.product_plan;
        let bundle = input.bundle;
        if input.publication_binding.is_zero()
            || input.recorded_at == 0
            || bundle.claim_scope != EvaluationClaimScopeV1::Qualification
            || plan.frozen_plan.claim_scope != EvaluationClaimScopeV1::Qualification
            || bundle.frozen_plan != plan.frozen_plan
            || bundle.holdout_use != self.execution.holdout.use_receipt
            || input.decision.decision.authority.grants_any()
            || input.candidate_plan.plan_digest != plan.candidate_temporal_plan_digest
            || input.baseline_plan.plan_digest != plan.baseline_temporal_plan_digest
        {
            return Err(ProductEvaluationError::Binding(
                "complete qualification material",
            ));
        }
        let mut out = Writer(Vec::new());
        out.raw(b"HPQPUB01")?;
        out.raw(&input.recorded_at.to_be_bytes())?;
        out.raw(input.publication_binding.as_array())?;
        out.id(&self.key.plan_id)?;
        out.raw(self.key.binding_digest.as_array())?;
        out.blob(&self.envelope)?; // Original execution signature and complete body.
        out.raw(&[match self.execution.holdout.disposition {
            HoldoutUseDispositionV1::Recorded => 0,
            HoldoutUseDispositionV1::IdempotentReplay => 1,
        }])?;
        out.raw(&self.execution.holdout.sequence.to_be_bytes())?;
        out.raw(self.execution.holdout.record_digest.as_array())?;
        out.raw(self.execution.holdout.head_digest.as_array())?;
        out.blob(&encode_holdout_use(&self.execution.holdout.use_receipt)?)?;
        // The private original execution readback admits only DENY_ALL receipts.
        out.raw(&[0])?;

        // Complete sealed product plan; original private seals remain intact.
        out.blob(&encode_holdout_plan(&plan.frozen_plan)?)?;
        out.count(plan.metric_roles.len())?;
        for role in &plan.metric_roles {
            out.id(&role.metric_id)?;
            match &role.role {
                MetricRoleV2::PrimarySuperiority {
                    minimum_improvement,
                } => {
                    out.raw(&[0])?;
                    out.raw(&minimum_improvement.raw().to_be_bytes())?;
                }
                MetricRoleV2::NonInferiority { maximum_regression } => {
                    out.raw(&[1])?;
                    out.raw(&maximum_regression.raw().to_be_bytes())?;
                }
                MetricRoleV2::AbsoluteConstraint => out.raw(&[2])?,
            }
        }
        out.count(plan.metric_contracts.len())?;
        for contract in &plan.metric_contracts {
            out.id(&contract.metric_id)?;
            out.direction(contract.direction)?;
            out.optional_fixed(contract.safety_floor)?;
        }
        out.count(plan.metric_sources.len())?;
        for source in &plan.metric_sources {
            out.id(&source.metric_id)?;
            out.raw(&[match source.source {
                ProductMetricSourceV1::Ips => 0,
                ProductMetricSourceV1::Snips => 1,
                ProductMetricSourceV1::DoublyRobust => 2,
            }])?;
        }
        for digest in [
            plan.base_estimand_digest,
            plan.candidate_temporal_plan_digest,
            plan.baseline_temporal_plan_digest,
            plan.receipt_seal,
        ] {
            out.raw(digest.as_array())?;
        }
        for temporal in [input.candidate_plan, input.baseline_plan] {
            out.temporal_plan(temporal)?;
        }

        // Complete bundle, including the original context and all metric values.
        for id in [
            &bundle.evaluation_id,
            &bundle.candidate_id,
            &bundle.baseline_id,
        ] {
            out.id(id)?;
        }
        out.raw(&[0])?; // Exact Qualification scope; v3 is not admitted here.
        for principal in [&bundle.generator, &bundle.evaluator] {
            out.principal(principal)?;
        }
        out.blob(&encode_holdout_plan(&bundle.frozen_plan)?)?;
        out.blob(&encode_holdout_use(&bundle.holdout_use)?)?;
        for digest in [
            bundle.objective_digest,
            bundle.dataset_digest,
            bundle.estimand_digest,
            bundle.estimate_receipt_digest,
            bundle.support_audit_digest,
            bundle.confidence_receipt_digest,
            bundle.unlearning_receipt_digest,
        ] {
            out.raw(digest.as_array())?;
        }
        out.count(bundle.retention_receipt_digests.len())?;
        for digest in &bundle.retention_receipt_digests {
            out.raw(digest.as_array())?;
        }
        out.ids(&bundle.snapshot_ids)?;
        out.ids(&bundle.future_window_ids)?;
        out.raw(&bundle.family_alpha_ppm.to_be_bytes())?;
        out.raw(&bundle.simultaneous_comparisons.to_be_bytes())?;
        out.count(bundle.metrics.len())?;
        for metric in &bundle.metrics {
            out.id(&metric.metric_id)?;
            out.direction(metric.direction)?;
            for value in [
                metric.candidate.lower,
                metric.candidate.upper,
                metric.baseline.lower,
                metric.baseline.upper,
            ] {
                out.raw(&value.raw().to_be_bytes())?;
            }
            out.optional_fixed(metric.safety_floor)?;
            out.raw(metric.support_digest.as_array())?;
        }
        // signing_bytes contains every original evidence field, not its digest.
        for signed in [
            &input.evidence.generator_plan,
            &input.evidence.evaluator_bundle,
        ] {
            out.blob(&signed.signing_bytes())?;
            out.raw(&signed.signature)?;
        }
        let decision = &input.decision.decision;
        for id in [
            &decision.evaluation_id,
            &decision.candidate_id,
            &decision.baseline_id,
        ] {
            out.id(id)?;
        }
        out.raw(&[match decision.disposition {
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
            IndependentEvaluationDispositionV1::Ineligible => 1,
            IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
        }])?;
        out.ids(&decision.failed_metrics)?;
        for digest in [
            decision.evidence_digest,
            input.decision.trust_digest,
            input.decision.authentication_digest,
        ] {
            out.raw(digest.as_array())?;
        }
        out.raw(&[0])?; // The public decision's authority was checked above.
        Ok(out.0)
    }
}

struct Writer(Vec<u8>);

impl Writer {
    fn raw(&mut self, bytes: &[u8]) -> Result<(), ProductEvaluationError> {
        if self
            .0
            .len()
            .checked_add(bytes.len())
            .is_none_or(|len| len > LIMIT)
        {
            return Err(ProductEvaluationError::Binding(
                "qualification record capacity",
            ));
        }
        self.0.extend_from_slice(bytes);
        Ok(())
    }

    fn count(&mut self, count: usize) -> Result<(), ProductEvaluationError> {
        let count = u32::try_from(count)
            .ok()
            .filter(|count| *count as usize <= LIMIT)
            .ok_or(ProductEvaluationError::Binding(
                "qualification record capacity",
            ))?;
        self.raw(&count.to_be_bytes())
    }

    fn blob(&mut self, bytes: &[u8]) -> Result<(), ProductEvaluationError> {
        self.count(bytes.len())?;
        self.raw(bytes)
    }

    fn id(&mut self, id: &StableId) -> Result<(), ProductEvaluationError> {
        self.blob(id.as_str().as_bytes())
    }

    fn ids(&mut self, ids: &[StableId]) -> Result<(), ProductEvaluationError> {
        self.count(ids.len())?;
        for id in ids {
            self.id(id)?;
        }
        Ok(())
    }

    fn direction(
        &mut self,
        direction: EvaluationDirectionV1,
    ) -> Result<(), ProductEvaluationError> {
        self.raw(&[match direction {
            EvaluationDirectionV1::Maximize => 0,
            EvaluationDirectionV1::Minimize => 1,
        }])
    }

    fn optional_fixed(&mut self, value: Option<FixedQ32>) -> Result<(), ProductEvaluationError> {
        match value {
            Some(value) => {
                self.raw(&[1])?;
                self.raw(&value.raw().to_be_bytes())
            }
            None => self.raw(&[0]),
        }
    }

    fn principal(
        &mut self,
        value: &AuthenticatedPrincipalV1,
    ) -> Result<(), ProductEvaluationError> {
        self.id(&value.principal_id)?;
        for digest in [
            value.credential_chain_digest,
            value.signing_key_digest,
            value.scope_digest,
        ] {
            self.raw(digest.as_array())?;
        }
        for integer in [
            value.authority_epoch,
            value.authenticated_at,
            value.expires_at,
        ] {
            self.raw(&integer.to_be_bytes())?;
        }
        Ok(())
    }

    fn temporal_plan(
        &mut self,
        plan: &TemporalEvaluationPlan,
    ) -> Result<(), ProductEvaluationError> {
        if plan.plan_digest != plan.canonical_digest()? {
            return Err(ProductEvaluationError::Binding("complete temporal plan"));
        }
        self.raw(plan.plan_digest.as_array())?;
        self.id(&plan.evaluation_id)?;
        self.raw(plan.objective_digest.as_array())?;
        self.raw(plan.fold.plan_digest.as_array())?;
        self.id(&plan.fold.fold_id)?;
        self.raw(&plan.fold.training_watermark.to_be_bytes())?;
        self.raw(&plan.fold.evaluation_start.to_be_bytes())?;
        self.usize_word(plan.fold.minimum_per_action)?;
        self.raw(plan.ope.plan_digest.as_array())?;
        self.raw(&plan.ope.outcome_watermark.to_be_bytes())?;
        self.usize_word(plan.ope.minimum_rows)?;
        self.raw(&plan.ope.minimum_ess.raw().to_be_bytes())?;
        self.raw(&plan.ope.maximum_weight.raw().to_be_bytes())?;
        self.raw(plan.confidence.plan_digest.as_array())?;
        self.raw(plan.confidence.assumptions_digest.as_array())?;
        self.raw(&plan.confidence.family_alpha_ppm.to_be_bytes())?;
        self.raw(&plan.confidence.simultaneous_comparisons.to_be_bytes())?;
        self.usize_word(plan.confidence.minimum_clusters)
    }

    fn usize_word(&mut self, value: usize) -> Result<(), ProductEvaluationError> {
        let value = u64::try_from(value)
            .map_err(|_| ProductEvaluationError::Binding("temporal plan integer"))?;
        self.raw(&value.to_be_bytes())
    }
}
