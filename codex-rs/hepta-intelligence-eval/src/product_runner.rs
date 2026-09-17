//! Product-composed independent evaluation runner.
//!
//! The runner deliberately separates holdout evaluation from the signed
//! qualification decision. Final-holdout use is durably recorded and its
//! independently owned anchor is committed before the estimator is allowed to
//! inspect held-out outcomes. A successful evaluation or qualification receipt
//! remains `DENY_ALL`: selection, promotion, deployment and release stay in
//! separate authorities.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::ClusterAssignment;
use crate::CrossFoldPlanReceiptV1;
use crate::DurableFinalHoldoutJournalV1;
use crate::DurableHoldoutError;
use crate::EvaluationClaimScopeV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::HeldOutTarget;
use crate::HoldoutAnchorV1;
use crate::IndependentEvaluationBundleV1;
use crate::LongitudinalTimeEvidenceV1;
use crate::MetricRoleContractV2;
use crate::OpeRow;
use crate::OutcomeTrainingSample;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::TemporalEvaluationError;
use crate::TemporalEvaluationPlan;
use crate::TemporalEvaluationReceipt;
use crate::decide_with_signed_evidence_v2;
use crate::decide_with_signed_longitudinal_evidence_v3;
use crate::evaluate_temporal_holdout;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HoldoutAnchorStoreError {
    Missing,
    Conflict,
    Unavailable,
    Corrupt,
    Indeterminate,
}

impl fmt::Display for HoldoutAnchorStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for HoldoutAnchorStoreError {}

/// Independently retained currentness witness for the final-holdout journal.
///
/// Implementations are host-owned. `compare_and_swap` must durably commit the
/// new anchor before returning success. A store colocated with a restorable
/// journal backup does not establish independent currentness merely by
/// implementing this trait.
pub trait HoldoutAnchorStoreV1 {
    fn initialize(
        &mut self,
        binding: Digest32,
        initial: HoldoutAnchorV1,
    ) -> Result<(), HoldoutAnchorStoreError>;

    fn load(&mut self, binding: Digest32) -> Result<HoldoutAnchorV1, HoldoutAnchorStoreError>;

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: HoldoutAnchorV1,
        next: HoldoutAnchorV1,
    ) -> Result<(), HoldoutAnchorStoreError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductTemporalEvaluationReceiptV1 {
    pub holdout: FinalHoldoutJournalReceiptV1,
    pub evaluation: TemporalEvaluationReceipt,
    pub frozen_plan: CrossFoldPlanReceiptV1,
    pub observed_holdout_digest: Digest32,
    pub objective_digest: Digest32,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub execution_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductQualificationReceiptV1 {
    pub temporal_execution_digest: Digest32,
    pub decision: SignedEvaluationDecisionV1,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub enum ProductTimingEvidenceV1<'a> {
    Qualification,
    SystemLongitudinal {
        timing: &'a LongitudinalTimeEvidenceV1,
        minimum_window_micros: u64,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductEvaluationError {
    Binding(&'static str),
    Holdout(DurableHoldoutError),
    Anchor(HoldoutAnchorStoreError),
    Temporal(TemporalEvaluationError),
    Signed(SignedEvaluationError),
    Poisoned,
}

impl fmt::Display for ProductEvaluationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductEvaluationError {}

impl From<DurableHoldoutError> for ProductEvaluationError {
    fn from(value: DurableHoldoutError) -> Self {
        Self::Holdout(value)
    }
}

impl From<HoldoutAnchorStoreError> for ProductEvaluationError {
    fn from(value: HoldoutAnchorStoreError) -> Self {
        Self::Anchor(value)
    }
}

impl From<TemporalEvaluationError> for ProductEvaluationError {
    fn from(value: TemporalEvaluationError) -> Self {
        Self::Temporal(value)
    }
}

impl From<SignedEvaluationError> for ProductEvaluationError {
    fn from(value: SignedEvaluationError) -> Self {
        Self::Signed(value)
    }
}

/// Stateful product adapter for durable holdout consumption and qualification.
///
/// The journal file and anchor store are distinct authority inputs. If an
/// anchor commit becomes indeterminate the runner is poisoned; the caller must
/// reopen it through `recover` before any further holdout access.
pub struct ProductEvaluationRunnerV1 {
    binding: Digest32,
    holdout: DurableFinalHoldoutJournalV1,
    poisoned: bool,
}

impl ProductEvaluationRunnerV1 {
    pub fn create(
        file: File,
        binding: Digest32,
        anchor_store: &mut dyn HoldoutAnchorStoreV1,
    ) -> Result<Self, ProductEvaluationError> {
        if binding.is_zero() {
            return Err(ProductEvaluationError::Binding("holdout binding"));
        }
        let holdout = DurableFinalHoldoutJournalV1::create(file, binding)?;
        anchor_store.initialize(binding, holdout.anchor())?;
        Ok(Self {
            binding,
            holdout,
            poisoned: false,
        })
    }

    pub fn recover(
        file: File,
        binding: Digest32,
        anchor_store: &mut dyn HoldoutAnchorStoreV1,
    ) -> Result<Self, ProductEvaluationError> {
        if binding.is_zero() {
            return Err(ProductEvaluationError::Binding("holdout binding"));
        }
        let retained = match anchor_store.load(binding) {
            Ok(anchor) => Some(anchor),
            Err(HoldoutAnchorStoreError::Missing) => None,
            Err(error) => return Err(error.into()),
        };
        let minimum = retained.unwrap_or(HoldoutAnchorV1 {
            sequence: 0,
            head: Digest32::ZERO,
        });
        let holdout = DurableFinalHoldoutJournalV1::recover(file, binding, minimum)?;
        let actual = holdout.anchor();
        match retained {
            Some(previous) if previous != actual => {
                // Conservative recovery for a crash after journal fsync but
                // before the independently retained anchor commit.
                anchor_store.compare_and_swap(binding, previous, actual)?;
            }
            None if actual.sequence == 0 && actual.head.is_zero() => {
                anchor_store.initialize(binding, actual)?;
            }
            None => return Err(HoldoutAnchorStoreError::Missing.into()),
            Some(_) => {}
        }
        Ok(Self {
            binding,
            holdout,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn anchor(&self) -> HoldoutAnchorV1 {
        self.holdout.anchor()
    }

    /// Consume the exact final holdout before evaluating it.
    ///
    /// `observed_holdout_digest` is the authenticated holdout-manifest/content
    /// digest supplied by the product data owner. It must equal the digest
    /// frozen into the cross-fold plan. The runner never derives this identity
    /// from outcome values after the fact.
    #[allow(clippy::too_many_arguments)]
    pub fn evaluate_temporal_candidate(
        &mut self,
        anchor_store: &mut dyn HoldoutAnchorStoreV1,
        frozen_plan: &CrossFoldPlanReceiptV1,
        observed_holdout_digest: Digest32,
        temporal_plan: &TemporalEvaluationPlan,
        training: &[OutcomeTrainingSample],
        targets: &[HeldOutTarget],
        observations: &[OpeRow],
        assignments: &[ClusterAssignment],
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
        if self.poisoned {
            return Err(ProductEvaluationError::Poisoned);
        }
        validate_product_binding(
            frozen_plan,
            observed_holdout_digest,
            temporal_plan,
            targets,
        )?;
        let retained = anchor_store.load(self.binding)?;
        if retained != self.holdout.anchor() {
            return Err(HoldoutAnchorStoreError::Conflict.into());
        }

        // Persist holdout use first. Any later estimator failure still burns the
        // holdout, which is conservative once execution has crossed the
        // confirmatory-data boundary.
        let holdout = self.holdout.consume(retained, frozen_plan)?;
        let next = self.holdout.anchor();
        if next != retained {
            if let Err(error) = anchor_store.compare_and_swap(self.binding, retained, next) {
                self.poisoned = true;
                return Err(ProductEvaluationError::Anchor(error));
            }
        }

        let evaluation = evaluate_temporal_holdout(
            temporal_plan,
            training,
            targets,
            observations,
            assignments,
        )?;
        let mut bytes = b"hepta.intelligence-eval.product-temporal-execution.v1\0".to_vec();
        for digest in [
            self.binding,
            frozen_plan.plan_digest,
            observed_holdout_digest,
            holdout.record_digest,
            holdout.use_receipt.use_digest,
            evaluation.evidence_digest,
            evaluation.estimate.point.evidence_digest,
            evaluation.estimate.evidence_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&temporal_plan.confidence.family_alpha_ppm.to_be_bytes());
        bytes.extend_from_slice(
            &temporal_plan
                .confidence
                .simultaneous_comparisons
                .to_be_bytes(),
        );
        Ok(ProductTemporalEvaluationReceiptV1 {
            holdout,
            evaluation,
            frozen_plan: frozen_plan.clone(),
            observed_holdout_digest,
            objective_digest: temporal_plan.objective_digest,
            family_alpha_ppm: temporal_plan.confidence.family_alpha_ppm,
            simultaneous_comparisons: temporal_plan.confidence.simultaneous_comparisons,
            execution_digest: Digest32::of_bytes(&bytes),
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    /// Authenticate generator/evaluator evidence and qualify the exact temporal
    /// execution receipt. Caller-supplied estimate/support/confidence digests
    /// cannot be substituted for another evaluation run.
    pub fn qualify_candidate(
        &self,
        temporal: &ProductTemporalEvaluationReceiptV1,
        bundle: IndependentEvaluationBundleV1,
        metric_roles: Vec<MetricRoleContractV2>,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<ProductQualificationReceiptV1, ProductEvaluationError> {
        if self.poisoned {
            return Err(ProductEvaluationError::Poisoned);
        }
        validate_qualification_binding(temporal, &bundle)?;
        let decision = match timing {
            ProductTimingEvidenceV1::Qualification => {
                if bundle.claim_scope != EvaluationClaimScopeV1::Qualification {
                    return Err(ProductEvaluationError::Binding("qualification scope"));
                }
                decide_with_signed_evidence_v2(bundle, metric_roles, evidence, verifier, now)?
            }
            ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => {
                if bundle.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal {
                    return Err(ProductEvaluationError::Binding("longitudinal scope"));
                }
                decide_with_signed_longitudinal_evidence_v3(
                    bundle,
                    metric_roles,
                    evidence,
                    timing,
                    minimum_window_micros,
                    verifier,
                    now,
                )?
            }
        };
        let mut bytes = b"hepta.intelligence-eval.product-qualification.v1\0".to_vec();
        for digest in [
            temporal.execution_digest,
            decision.decision.evidence_digest,
            decision.trust_digest,
            decision.authentication_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(ProductQualificationReceiptV1 {
            temporal_execution_digest: temporal.execution_digest,
            decision,
            evidence_digest: Digest32::of_bytes(&bytes),
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

fn validate_product_binding(
    frozen_plan: &CrossFoldPlanReceiptV1,
    observed_holdout_digest: Digest32,
    temporal_plan: &TemporalEvaluationPlan,
    targets: &[HeldOutTarget],
) -> Result<(), ProductEvaluationError> {
    if observed_holdout_digest.is_zero()
        || frozen_plan.final_holdout_digest != observed_holdout_digest
    {
        return Err(ProductEvaluationError::Binding("final holdout digest"));
    }
    if frozen_plan.objective_digest != temporal_plan.objective_digest {
        return Err(ProductEvaluationError::Binding("objective"));
    }
    if frozen_plan.family_alpha_ppm != temporal_plan.confidence.family_alpha_ppm
        || frozen_plan.simultaneous_comparisons
            != temporal_plan.confidence.simultaneous_comparisons
    {
        return Err(ProductEvaluationError::Binding("multiplicity"));
    }
    if targets.is_empty()
        || targets
            .iter()
            .any(|target| target.window_id != frozen_plan.final_holdout_window_id)
    {
        return Err(ProductEvaluationError::Binding("final holdout window"));
    }
    Ok(())
}

fn validate_qualification_binding(
    temporal: &ProductTemporalEvaluationReceiptV1,
    bundle: &IndependentEvaluationBundleV1,
) -> Result<(), ProductEvaluationError> {
    if bundle.frozen_plan != temporal.frozen_plan
        || bundle.holdout_use != temporal.holdout.use_receipt
        || bundle.evaluation_id != temporal.evaluation.evaluation_id
        || bundle.objective_digest != temporal.objective_digest
    {
        return Err(ProductEvaluationError::Binding("evaluation identity"));
    }
    if bundle.estimate_receipt_digest != temporal.evaluation.evidence_digest
        || bundle.support_audit_digest != temporal.evaluation.estimate.point.evidence_digest
        || bundle.confidence_receipt_digest != temporal.evaluation.estimate.evidence_digest
        || bundle.family_alpha_ppm != temporal.family_alpha_ppm
        || bundle.simultaneous_comparisons != temporal.simultaneous_comparisons
    {
        return Err(ProductEvaluationError::Binding("evaluation evidence"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "product_runner_tests.rs"]
mod tests;
