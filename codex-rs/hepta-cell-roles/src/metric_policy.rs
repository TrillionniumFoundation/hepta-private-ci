//! Executable, authority-free role metric acceptance policy.
//!
//! `CellRoleMetricProfileV1` defines which observations a role must provide.
//! It deliberately does not interpret the observations.  This module adds
//! the missing deterministic policy execution layer: a frozen threshold set
//! is checked against a typed metric receipt and produces a replayable
//! disposition.  The disposition is evidence only; retention, activation,
//! route cutover and rollback remain owned by the durable governance owners.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellRoleGateErrorV1;
use crate::CellRoleMetricKindV1;
use crate::CellRoleMetricProfileV1;
use crate::CellRoleMetricReceiptV1;

pub const ROLE_METRIC_POLICY_SCHEMA_V1: &str = "hepta.cell-role.metric-policy.v1";
pub const ROLE_METRIC_DECISION_SCHEMA_V1: &str = "hepta.cell-role.metric-decision.v1";

/// Direction of a scalar acceptance threshold.  The policy is evaluated on
/// the measured integer value, after the metric receipt has validated units.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RoleMetricDirectionV1 {
    AtLeast,
    AtMost,
}

impl RoleMetricDirectionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::AtLeast => 0,
            Self::AtMost => 1,
        }
    }

    fn accepts(self, actual: i64, threshold: i64, tolerance: i64) -> bool {
        match self {
            Self::AtLeast => actual >= threshold.saturating_sub(tolerance),
            Self::AtMost => actual <= threshold.saturating_add(tolerance),
        }
    }
}

/// One frozen threshold.  `tolerance` is expressed in the metric's already
/// validated unit, including raw Q32 units for fixed-point metrics.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RoleMetricThresholdV1 {
    pub kind: CellRoleMetricKindV1,
    pub direction: RoleMetricDirectionV1,
    pub threshold_value: i64,
    pub tolerance: i64,
    pub minimum_sample_count: u64,
}

impl RoleMetricThresholdV1 {
    fn validate(&self, expected_role: CellRoleV1) -> Result<(), RoleMetricPolicyErrorV1> {
        if self.kind.role() != expected_role {
            return Err(RoleMetricPolicyErrorV1::MetricRoleMismatch(self.kind));
        }
        if self.threshold_value < 0 && !self.kind.permits_negative() {
            return Err(RoleMetricPolicyErrorV1::InvalidThreshold(self.kind));
        }
        if self.tolerance < 0 || self.minimum_sample_count == 0 {
            return Err(RoleMetricPolicyErrorV1::InvalidThreshold(self.kind));
        }
        Ok(())
    }
}

/// A frozen executable policy for one role metric profile.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleMetricAcceptancePolicyV1 {
    pub role: CellRoleV1,
    pub profile_digest: Digest32,
    pub no_change_baseline_digest: Digest32,
    pub future_window_digest: Digest32,
    pub thresholds: Vec<RoleMetricThresholdV1>,
    pub authority: AuthorityPosture,
    pub policy_digest: Digest32,
}

impl RoleMetricAcceptancePolicyV1 {
    pub fn new(
        profile: &CellRoleMetricProfileV1,
        thresholds: Vec<RoleMetricThresholdV1>,
    ) -> Result<Self, RoleMetricPolicyErrorV1> {
        profile.validate()?;
        let mut policy = Self {
            role: profile.role,
            profile_digest: profile.content_digest()?,
            no_change_baseline_digest: profile.no_change_baseline_digest,
            future_window_digest: profile.future_window_digest,
            thresholds,
            authority: AuthorityPosture::DENY_ALL,
            policy_digest: Digest32::ZERO,
        };
        policy.policy_digest = policy.content_digest();
        policy.validate_against(profile)?;
        Ok(policy)
    }

    pub fn validate_against(
        &self,
        profile: &CellRoleMetricProfileV1,
    ) -> Result<(), RoleMetricPolicyErrorV1> {
        profile.validate()?;
        if self.role != profile.role
            || self.profile_digest != profile.content_digest()?
            || self.no_change_baseline_digest != profile.no_change_baseline_digest
            || self.future_window_digest != profile.future_window_digest
            || self.authority.grants_any()
        {
            return Err(RoleMetricPolicyErrorV1::PolicyBinding);
        }
        if self.thresholds.len() != profile.required_metrics.len() {
            return Err(RoleMetricPolicyErrorV1::MetricSetMismatch);
        }
        for (index, threshold) in self.thresholds.iter().enumerate() {
            threshold.validate(self.role)?;
            if self.thresholds[..index]
                .iter()
                .any(|previous| previous.kind == threshold.kind)
            {
                return Err(RoleMetricPolicyErrorV1::DuplicateMetric(threshold.kind));
            }
        }
        for required in &profile.required_metrics {
            if !self.thresholds.iter().any(|item| item.kind == *required) {
                return Err(RoleMetricPolicyErrorV1::MissingMetric(*required));
            }
        }
        if self.policy_digest.is_zero() || self.policy_digest != self.content_digest() {
            return Err(RoleMetricPolicyErrorV1::PolicyDigestMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::from(ROLE_METRIC_POLICY_SCHEMA_V1.as_bytes());
        bytes.push(self.role.tag());
        bytes.extend_from_slice(self.profile_digest.as_array());
        bytes.extend_from_slice(self.no_change_baseline_digest.as_array());
        bytes.extend_from_slice(self.future_window_digest.as_array());
        for threshold in &self.thresholds {
            bytes.push(threshold.kind.tag());
            bytes.push(threshold.direction.tag());
            bytes.extend_from_slice(&threshold.threshold_value.to_be_bytes());
            bytes.extend_from_slice(&threshold.tolerance.to_be_bytes());
            bytes.extend_from_slice(&threshold.minimum_sample_count.to_be_bytes());
        }
        bytes.push(self.authority.flags().wire_mask());
        Digest32::of_bytes(&bytes)
    }

    /// Execute the frozen policy.  A `Pass` means the measured receipt meets
    /// this policy; it never means that the candidate may be retained or
    /// activated.
    pub fn evaluate(
        &self,
        profile: &CellRoleMetricProfileV1,
        receipt: &CellRoleMetricReceiptV1,
    ) -> Result<RoleMetricDecisionReceiptV1, RoleMetricPolicyErrorV1> {
        self.validate_against(profile)?;
        receipt.validate_structure_against(profile)?;
        if receipt.profile_digest != self.profile_digest
            || receipt.baseline_digest != self.no_change_baseline_digest
            || receipt.evaluation_window_digest != self.future_window_digest
        {
            return Err(RoleMetricPolicyErrorV1::ReceiptBinding);
        }
        let mut failed_metrics = Vec::new();
        let mut insufficient_metrics = Vec::new();
        for threshold in &self.thresholds {
            let metric = receipt
                .metrics
                .iter()
                .find(|item| item.kind == threshold.kind)
                .ok_or(RoleMetricPolicyErrorV1::MissingMetric(threshold.kind))?;
            if metric.sample_count < threshold.minimum_sample_count {
                insufficient_metrics.push(threshold.kind);
            } else if !threshold.direction.accepts(
                metric.value,
                threshold.threshold_value,
                threshold.tolerance,
            ) {
                failed_metrics.push(threshold.kind);
            }
        }
        let disposition = if !insufficient_metrics.is_empty() {
            RoleMetricDecisionDispositionV1::InsufficientEvidence
        } else if !failed_metrics.is_empty() {
            RoleMetricDecisionDispositionV1::Fail
        } else {
            RoleMetricDecisionDispositionV1::Pass
        };
        let mut decision = RoleMetricDecisionReceiptV1 {
            schema: ROLE_METRIC_DECISION_SCHEMA_V1,
            cell_id: receipt.cell_id.clone(),
            generation: receipt.generation,
            role: receipt.role,
            profile_digest: self.profile_digest,
            policy_digest: self.policy_digest,
            metric_receipt_digest: receipt.content_digest(profile)?,
            disposition,
            failed_metrics,
            insufficient_metrics,
            authority: AuthorityPosture::DENY_ALL,
            decision_digest: Digest32::ZERO,
        };
        decision.decision_digest = decision.content_digest();
        decision.validate_against(self, profile, receipt)?;
        Ok(decision)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RoleMetricDecisionDispositionV1 {
    Pass,
    Fail,
    InsufficientEvidence,
}

impl RoleMetricDecisionDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Pass => 0,
            Self::Fail => 1,
            Self::InsufficientEvidence => 2,
        }
    }
}

/// Replayable threshold decision.  It has no promotion or activation field.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleMetricDecisionReceiptV1 {
    pub schema: &'static str,
    pub cell_id: StableId,
    pub generation: Generation,
    pub role: CellRoleV1,
    pub profile_digest: Digest32,
    pub policy_digest: Digest32,
    pub metric_receipt_digest: Digest32,
    pub disposition: RoleMetricDecisionDispositionV1,
    pub failed_metrics: Vec<CellRoleMetricKindV1>,
    pub insufficient_metrics: Vec<CellRoleMetricKindV1>,
    pub authority: AuthorityPosture,
    pub decision_digest: Digest32,
}

impl RoleMetricDecisionReceiptV1 {
    pub fn validate_against(
        &self,
        policy: &RoleMetricAcceptancePolicyV1,
        profile: &CellRoleMetricProfileV1,
        receipt: &CellRoleMetricReceiptV1,
    ) -> Result<(), RoleMetricPolicyErrorV1> {
        policy.validate_against(profile)?;
        receipt.validate_structure_against(profile)?;
        let (disposition, mut failed_metrics, mut insufficient_metrics) =
            evaluate_metric_outcome(policy, receipt)?;
        failed_metrics.sort_by_key(|metric| metric.tag());
        insufficient_metrics.sort_by_key(|metric| metric.tag());
        let mut actual_failed = self.failed_metrics.clone();
        let mut actual_insufficient = self.insufficient_metrics.clone();
        actual_failed.sort_by_key(|metric| metric.tag());
        actual_insufficient.sort_by_key(|metric| metric.tag());
        if self.schema != ROLE_METRIC_DECISION_SCHEMA_V1
            || self.cell_id != receipt.cell_id
            || self.generation != receipt.generation
            || self.role != receipt.role
            || self.profile_digest != policy.profile_digest
            || self.policy_digest != policy.policy_digest
            || self.metric_receipt_digest != receipt.content_digest(profile)?
            || self.disposition != disposition
            || actual_failed != failed_metrics
            || actual_insufficient != insufficient_metrics
            || self.authority.grants_any()
            || self.decision_digest != self.content_digest()
        {
            return Err(RoleMetricPolicyErrorV1::DecisionBinding);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::from(ROLE_METRIC_DECISION_SCHEMA_V1.as_bytes());
        bytes.extend_from_slice(self.cell_id.as_str().as_bytes());
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.push(self.role.tag());
        bytes.extend_from_slice(self.profile_digest.as_array());
        bytes.extend_from_slice(self.policy_digest.as_array());
        bytes.extend_from_slice(self.metric_receipt_digest.as_array());
        bytes.push(self.disposition.tag());
        for metric in self
            .failed_metrics
            .iter()
            .chain(self.insufficient_metrics.iter())
        {
            bytes.push(metric.tag());
        }
        bytes.push(self.authority.flags().wire_mask());
        Digest32::of_bytes(&bytes)
    }
}

fn evaluate_metric_outcome(
    policy: &RoleMetricAcceptancePolicyV1,
    receipt: &CellRoleMetricReceiptV1,
) -> Result<
    (
        RoleMetricDecisionDispositionV1,
        Vec<CellRoleMetricKindV1>,
        Vec<CellRoleMetricKindV1>,
    ),
    RoleMetricPolicyErrorV1,
> {
    let mut failed_metrics = Vec::new();
    let mut insufficient_metrics = Vec::new();
    for threshold in &policy.thresholds {
        let metric = receipt
            .metrics
            .iter()
            .find(|item| item.kind == threshold.kind)
            .ok_or(RoleMetricPolicyErrorV1::MissingMetric(threshold.kind))?;
        if metric.sample_count < threshold.minimum_sample_count {
            insufficient_metrics.push(threshold.kind);
        } else if !threshold.direction.accepts(
            metric.value,
            threshold.threshold_value,
            threshold.tolerance,
        ) {
            failed_metrics.push(threshold.kind);
        }
    }
    let disposition = if !insufficient_metrics.is_empty() {
        RoleMetricDecisionDispositionV1::InsufficientEvidence
    } else if !failed_metrics.is_empty() {
        RoleMetricDecisionDispositionV1::Fail
    } else {
        RoleMetricDecisionDispositionV1::Pass
    };
    Ok((disposition, failed_metrics, insufficient_metrics))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RoleMetricPolicyErrorV1 {
    Metric(CellRoleGateErrorV1),
    MetricRoleMismatch(CellRoleMetricKindV1),
    InvalidThreshold(CellRoleMetricKindV1),
    DuplicateMetric(CellRoleMetricKindV1),
    MissingMetric(CellRoleMetricKindV1),
    MetricSetMismatch,
    PolicyBinding,
    PolicyDigestMismatch,
    ReceiptBinding,
    DecisionBinding,
}

impl fmt::Display for RoleMetricPolicyErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RoleMetricPolicyErrorV1 {}

impl From<CellRoleGateErrorV1> for RoleMetricPolicyErrorV1 {
    fn from(value: CellRoleGateErrorV1) -> Self {
        Self::Metric(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::role_gates::CellRoleMetricV1;
    use codex_hepta_types::AuthorityPosture;

    fn digest(seed: u8) -> Digest32 {
        Digest32::from_array([seed; 32])
    }

    fn profile() -> CellRoleMetricProfileV1 {
        CellRoleMetricProfileV1::standard_for_role(
            CellRoleV1::Representation,
            digest(1),
            digest(2),
            digest(3),
            digest(4),
        )
    }

    fn policy(profile: &CellRoleMetricProfileV1) -> RoleMetricAcceptancePolicyV1 {
        RoleMetricAcceptancePolicyV1::new(
            profile,
            profile
                .required_metrics
                .iter()
                .map(|kind| RoleMetricThresholdV1 {
                    kind: *kind,
                    direction: if kind.permits_negative() {
                        RoleMetricDirectionV1::AtMost
                    } else {
                        RoleMetricDirectionV1::AtMost
                    },
                    threshold_value: 900_000,
                    tolerance: 0,
                    minimum_sample_count: 2,
                })
                .collect(),
        )
        .expect("policy")
    }

    fn receipt(
        profile: &CellRoleMetricProfileV1,
        sample_count: u64,
        value: i64,
    ) -> CellRoleMetricReceiptV1 {
        CellRoleMetricReceiptV1 {
            cell_id: StableId::new("cell.metric-policy").expect("id"),
            generation: Generation::new(1).expect("generation"),
            role: profile.role,
            proposer_id: StableId::new("proposal.metric-policy").expect("id"),
            evaluator_id: StableId::new("evaluator.metric-policy").expect("id"),
            profile_digest: profile.content_digest().expect("profile"),
            baseline_digest: profile.no_change_baseline_digest,
            evaluation_window_digest: profile.future_window_digest,
            metrics: profile
                .required_metrics
                .iter()
                .map(|kind| CellRoleMetricV1 {
                    kind: *kind,
                    unit: kind.unit(),
                    value,
                    sample_count,
                    observation_digest: digest(kind.tag().saturating_add(10)),
                })
                .collect(),
            evidence_digest: digest(30),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn executable_policy_produces_replayable_pass() {
        let profile = profile();
        let mut policy = policy(&profile);
        policy.policy_digest = policy.content_digest();
        let receipt = receipt(&profile, 2, 900_000);
        let decision = policy.evaluate(&profile, &receipt).expect("decision");
        assert_eq!(decision.disposition, RoleMetricDecisionDispositionV1::Pass);
        decision
            .validate_against(&policy, &profile, &receipt)
            .expect("replay");
    }

    #[test]
    fn executable_policy_rejects_threshold_and_low_support() {
        let profile = profile();
        let mut policy = policy(&profile);
        policy.policy_digest = policy.content_digest();
        let failed = receipt(&profile, 2, 900_001);
        assert_eq!(
            policy
                .evaluate(&profile, &failed)
                .expect("decision")
                .disposition,
            RoleMetricDecisionDispositionV1::Fail
        );
        let insufficient = receipt(&profile, 1, 900_000);
        assert_eq!(
            policy
                .evaluate(&profile, &insufficient)
                .expect("decision")
                .disposition,
            RoleMetricDecisionDispositionV1::InsufficientEvidence
        );
    }

    #[test]
    fn replay_rejects_forged_pass_disposition_and_metric_lists() {
        let profile = profile();
        let mut policy = policy(&profile);
        policy.policy_digest = policy.content_digest();
        let failed = receipt(&profile, 2, 900_001);
        let mut forged = policy.evaluate(&profile, &failed).expect("decision");
        forged.disposition = RoleMetricDecisionDispositionV1::Pass;
        forged.failed_metrics.clear();
        forged.decision_digest = forged.content_digest();
        assert_eq!(
            forged.validate_against(&policy, &profile, &failed),
            Err(RoleMetricPolicyErrorV1::DecisionBinding)
        );
    }
}
