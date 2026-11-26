//! Role-generic split metric binding.
//!
//! The historical `RoleSplitAdmissionV1` record predates the role catalogue
//! and carries four Plasticity-named observation fields.  That record remains
//! replayable for compatibility, but new split owners must use this contract:
//! every required metric for the selected role is bound by kind and
//! observation digest.  No role is admitted by silently borrowing Plasticity
//! thresholds.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellRoleGateErrorV1;
use crate::CellRoleMetricKindV1;
use crate::CellRoleMetricProfileV1;
use crate::CellRoleMetricReceiptV1;

pub const ROLE_SPLIT_METRIC_BINDING_SCHEMA_V1: &str =
    "hepta.cell-role.role-split-metric-binding.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleSplitMetricObservationBindingV1 {
    pub kind: CellRoleMetricKindV1,
    pub observation_digest: Digest32,
}

impl RoleSplitMetricObservationBindingV1 {
    fn validate(&self, role: CellRoleV1) -> Result<(), RoleSplitMetricBindingErrorV1> {
        if self.kind.role() != role {
            return Err(RoleSplitMetricBindingErrorV1::MetricRoleMismatch {
                expected: role,
                actual: self.kind.role(),
            });
        }
        if self.observation_digest.is_zero() {
            return Err(RoleSplitMetricBindingErrorV1::EmptyObservation(self.kind));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleSplitMetricBindingSetV1 {
    pub role: CellRoleV1,
    pub profile_digest: Digest32,
    pub metric_receipt_digest: Digest32,
    pub observations: Vec<RoleSplitMetricObservationBindingV1>,
    pub authority: AuthorityPosture,
}

impl RoleSplitMetricBindingSetV1 {
    pub fn validate_against(
        &self,
        profile: &CellRoleMetricProfileV1,
        metrics: &CellRoleMetricReceiptV1,
    ) -> Result<(), RoleSplitMetricBindingErrorV1> {
        profile.validate()?;
        metrics.validate_structure_against(profile)?;
        if self.role != profile.role || self.role != metrics.role {
            return Err(RoleSplitMetricBindingErrorV1::RoleMismatch);
        }
        if self.profile_digest != profile.content_digest()? {
            return Err(RoleSplitMetricBindingErrorV1::ProfileDigestMismatch);
        }
        if self.metric_receipt_digest != metrics.content_digest(profile)? {
            return Err(RoleSplitMetricBindingErrorV1::MetricReceiptDigestMismatch);
        }
        if self.authority.grants_any() {
            return Err(RoleSplitMetricBindingErrorV1::AuthorityGranted);
        }
        if self.observations.len() != profile.required_metrics.len() {
            return Err(RoleSplitMetricBindingErrorV1::ObservationSetIncomplete);
        }
        for (index, binding) in self.observations.iter().enumerate() {
            binding.validate(self.role)?;
            if self.observations[..index]
                .iter()
                .any(|previous| previous.kind == binding.kind)
            {
                return Err(RoleSplitMetricBindingErrorV1::DuplicateMetric(binding.kind));
            }
            let measured = metrics
                .metrics
                .iter()
                .find(|metric| metric.kind == binding.kind)
                .ok_or(RoleSplitMetricBindingErrorV1::MissingMetric(binding.kind))?;
            if measured.observation_digest != binding.observation_digest {
                return Err(RoleSplitMetricBindingErrorV1::ObservationMismatch(
                    binding.kind,
                ));
            }
        }
        for required in &profile.required_metrics {
            if !self
                .observations
                .iter()
                .any(|binding| binding.kind == *required)
            {
                return Err(RoleSplitMetricBindingErrorV1::MissingMetric(*required));
            }
        }
        Ok(())
    }

    pub fn content_digest(&self) -> Result<Digest32, RoleSplitMetricBindingErrorV1> {
        if self.authority.grants_any() {
            return Err(RoleSplitMetricBindingErrorV1::AuthorityGranted);
        }
        let mut bytes = ROLE_SPLIT_METRIC_BINDING_SCHEMA_V1.as_bytes().to_vec();
        bytes.push(self.role.tag());
        bytes.extend_from_slice(self.profile_digest.as_array());
        bytes.extend_from_slice(self.metric_receipt_digest.as_array());
        for observation in &self.observations {
            bytes.push(observation.kind.tag());
            bytes.extend_from_slice(observation.observation_digest.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleSplitMetricAdmissionReceiptV1 {
    pub schema: &'static str,
    pub role: CellRoleV1,
    pub parent_cell_id: StableId,
    pub successor_generation: Generation,
    pub split_subject_digest: Digest32,
    pub binding_digest: Digest32,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub authority: AuthorityPosture,
    pub admission_digest: Digest32,
}

impl RoleSplitMetricAdmissionReceiptV1 {
    pub fn verify(
        &self,
        split: &CellSplitV1,
        profile: &CellRoleMetricProfileV1,
        metrics: &CellRoleMetricReceiptV1,
        bindings: &RoleSplitMetricBindingSetV1,
    ) -> Result<(), RoleSplitMetricBindingErrorV1> {
        if self.schema != ROLE_SPLIT_METRIC_BINDING_SCHEMA_V1
            || self.authority.grants_any()
            || self.parent_cell_id != split.parent_cell_id
            || self.successor_generation != split.successor_generation
            || self.role != bindings.role
            || self.proposer_id != split.proposer_id
            || self.evaluator_id != split.evaluator_id
            || self.evaluator_id != split.evaluation.evaluator_id
            || self.split_subject_digest != split.evaluation_subject_digest()?
            || self.binding_digest != bindings.content_digest()?
            || self.admission_digest != digest_admission(self)
        {
            return Err(RoleSplitMetricBindingErrorV1::ReceiptMismatch);
        }
        bindings.validate_against(profile, metrics)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RoleSplitMetricBindingErrorV1 {
    Split(codex_hepta_types::CellSplitContractErrorV1),
    Gate(CellRoleGateErrorV1),
    RoleMismatch,
    MetricRoleMismatch {
        expected: CellRoleV1,
        actual: CellRoleV1,
    },
    ProfileDigestMismatch,
    MetricReceiptDigestMismatch,
    EmptyObservation(CellRoleMetricKindV1),
    ObservationSetIncomplete,
    DuplicateMetric(CellRoleMetricKindV1),
    MissingMetric(CellRoleMetricKindV1),
    ObservationMismatch(CellRoleMetricKindV1),
    AuthorityGranted,
    ReceiptMismatch,
}

impl fmt::Display for RoleSplitMetricBindingErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RoleSplitMetricBindingErrorV1 {}

impl From<codex_hepta_types::CellSplitContractErrorV1> for RoleSplitMetricBindingErrorV1 {
    fn from(value: codex_hepta_types::CellSplitContractErrorV1) -> Self {
        Self::Split(value)
    }
}

impl From<CellRoleGateErrorV1> for RoleSplitMetricBindingErrorV1 {
    fn from(value: CellRoleGateErrorV1) -> Self {
        Self::Gate(value)
    }
}

pub struct RoleSplitMetricAdmissionV1;

impl RoleSplitMetricAdmissionV1 {
    pub fn admit(
        split: &CellSplitV1,
        profile: &CellRoleMetricProfileV1,
        metrics: &CellRoleMetricReceiptV1,
        bindings: RoleSplitMetricBindingSetV1,
    ) -> Result<RoleSplitMetricAdmissionReceiptV1, RoleSplitMetricBindingErrorV1> {
        split.validate()?;
        bindings.validate_against(profile, metrics)?;
        if metrics.cell_id != split.parent_cell_id
            || metrics.generation != split.successor_generation
            || metrics.proposer_id != split.proposer_id
            || metrics.evaluator_id != split.evaluation.evaluator_id
        {
            return Err(RoleSplitMetricBindingErrorV1::ReceiptMismatch);
        }
        let receipt_without_digest = RoleSplitMetricAdmissionReceiptV1 {
            schema: ROLE_SPLIT_METRIC_BINDING_SCHEMA_V1,
            role: profile.role,
            parent_cell_id: split.parent_cell_id.clone(),
            successor_generation: split.successor_generation,
            split_subject_digest: split.evaluation_subject_digest()?,
            binding_digest: bindings.content_digest()?,
            proposer_id: split.proposer_id.clone(),
            evaluator_id: split.evaluation.evaluator_id.clone(),
            authority: AuthorityPosture::DENY_ALL,
            admission_digest: Digest32::ZERO,
        };
        let mut receipt = receipt_without_digest;
        receipt.admission_digest = digest_admission(&receipt);
        Ok(receipt)
    }
}

fn digest_admission(receipt: &RoleSplitMetricAdmissionReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.cell-role.role-split-metric-admission.v1".to_vec();
    bytes.push(receipt.role.tag());
    bytes.extend_from_slice(receipt.parent_cell_id.as_str().as_bytes());
    bytes.extend_from_slice(&receipt.successor_generation.get().to_be_bytes());
    bytes.extend_from_slice(receipt.split_subject_digest.as_array());
    bytes.extend_from_slice(receipt.binding_digest.as_array());
    bytes.extend_from_slice(receipt.proposer_id.as_str().as_bytes());
    bytes.extend_from_slice(receipt.evaluator_id.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CellRoleMetricV1;

    #[test]
    fn generic_binding_covers_all_communication_metrics() {
        let digest = |value: u8| Digest32::of_bytes(&[value]);
        let profile = CellRoleMetricProfileV1::standard_for_role(
            CellRoleV1::Communication,
            digest(1),
            digest(2),
            digest(3),
            digest(4),
        );
        let cell_id = StableId::new("communication.cell").expect("cell");
        let proposer_id = StableId::new("proposer").expect("proposer");
        let evaluator_id = StableId::new("evaluator").expect("evaluator");
        let metrics = profile
            .required_metrics
            .iter()
            .enumerate()
            .map(|(index, kind)| CellRoleMetricV1 {
                kind: *kind,
                unit: kind.unit(),
                value: 100,
                sample_count: 10,
                observation_digest: digest(10 + index as u8),
            })
            .collect::<Vec<_>>();
        let mut metrics = CellRoleMetricReceiptV1 {
            cell_id,
            generation: Generation::new(2).expect("generation"),
            role: CellRoleV1::Communication,
            proposer_id,
            evaluator_id,
            profile_digest: profile.content_digest().expect("profile"),
            baseline_digest: profile.no_change_baseline_digest,
            evaluation_window_digest: profile.future_window_digest,
            metrics,
            evidence_digest: digest(30),
            authority: AuthorityPosture::DENY_ALL,
        };
        let observations = metrics
            .metrics
            .iter()
            .map(|metric| RoleSplitMetricObservationBindingV1 {
                kind: metric.kind,
                observation_digest: metric.observation_digest,
            })
            .collect::<Vec<_>>();
        let bindings = RoleSplitMetricBindingSetV1 {
            role: CellRoleV1::Communication,
            profile_digest: profile.content_digest().expect("profile"),
            metric_receipt_digest: metrics.content_digest(&profile).expect("metrics"),
            observations,
            authority: AuthorityPosture::DENY_ALL,
        };
        bindings
            .validate_against(&profile, &metrics)
            .expect("validate");
        metrics.metrics[0].observation_digest = Digest32::of_bytes(b"tamper");
        assert!(bindings.validate_against(&profile, &metrics).is_err());
    }
}
