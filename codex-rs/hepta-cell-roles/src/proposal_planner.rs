//! Governed conversion of long-horizon telemetry into a complete CellSplit.
//!
//! A signal is an observation, not a topology mutation.  The planner joins a
//! signal with a separately authored structural template, checks the
//! proposer/evaluator and future-window fences, fills the independent
//! evaluation receipts, and returns a validated `CellSplitV1`.  It never
//! publishes an artifact, activates a route, or retires a parent cell.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const CELL_SPLIT_PROPOSAL_SIGNAL_SCHEMA_V1: &str =
    "hepta.cell-role.cell-split-proposal-signal.v1";
pub const CELL_SPLIT_PROPOSAL_PLANNER_SCHEMA_V1: &str =
    "hepta.cell-role.cell-split-proposal-planner.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitProposalSignalV1 {
    pub signal_id: StableId,
    pub role: CellRoleV1,
    pub parent_cell_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub template_subject_digest: Digest32,
    pub no_change_baseline_digest: Digest32,
    pub future_window_digest: Digest32,
    pub telemetry_digest: Digest32,
    pub long_term_gain_digest: Digest32,
    pub negative_transfer_digest: Digest32,
    pub resource_pressure_digest: Digest32,
    pub benefit_ppm: u32,
    pub negative_transfer_ppm: u32,
    pub resource_cost_ppm: u32,
    pub evaluation_receipt_digest: Digest32,
    pub retention_receipt_digest: Digest32,
    pub negative_transfer_receipt_digest: Digest32,
    pub cost_receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CellSplitProposalSignalV1 {
    pub fn validate(&self) -> Result<(), CellSplitProposalPlannerErrorV1> {
        for (label, id) in [
            ("signal", &self.signal_id),
            ("parent", &self.parent_cell_id),
            ("proposer", &self.proposer_id),
            ("evaluator", &self.evaluator_id),
        ] {
            if id.as_str().is_empty() {
                return Err(CellSplitProposalPlannerErrorV1::EmptyId(label));
            }
        }
        for (label, digest) in [
            ("template", self.template_subject_digest),
            ("baseline", self.no_change_baseline_digest),
            ("future window", self.future_window_digest),
            ("telemetry", self.telemetry_digest),
            ("long-term gain", self.long_term_gain_digest),
            ("negative transfer", self.negative_transfer_digest),
            ("resource pressure", self.resource_pressure_digest),
            ("evaluation", self.evaluation_receipt_digest),
            ("retention", self.retention_receipt_digest),
            (
                "negative-transfer receipt",
                self.negative_transfer_receipt_digest,
            ),
            ("cost", self.cost_receipt_digest),
        ] {
            if digest.is_zero() {
                return Err(CellSplitProposalPlannerErrorV1::EmptyDigest(label));
            }
        }
        if self.proposer_id == self.evaluator_id {
            return Err(CellSplitProposalPlannerErrorV1::IndependentEvaluator);
        }
        if self.authority.grants_any() {
            return Err(CellSplitProposalPlannerErrorV1::AuthorityGranted);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = CELL_SPLIT_PROPOSAL_SIGNAL_SCHEMA_V1.as_bytes().to_vec();
        for id in [
            &self.signal_id,
            &self.parent_cell_id,
            &self.proposer_id,
            &self.evaluator_id,
        ] {
            let raw = id.as_str().as_bytes();
            bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        bytes.push(self.role.tag());
        for digest in [
            self.template_subject_digest,
            self.no_change_baseline_digest,
            self.future_window_digest,
            self.telemetry_digest,
            self.long_term_gain_digest,
            self.negative_transfer_digest,
            self.resource_pressure_digest,
            self.evaluation_receipt_digest,
            self.retention_receipt_digest,
            self.negative_transfer_receipt_digest,
            self.cost_receipt_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [
            self.benefit_ppm,
            self.negative_transfer_ppm,
            self.resource_cost_ppm,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.push(self.authority.flags().wire_mask());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitProposalGovernanceV1 {
    pub role: CellRoleV1,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub future_window_digest: Digest32,
    pub minimum_benefit_ppm: u32,
    pub maximum_negative_transfer_ppm: u32,
    pub maximum_resource_cost_ppm: u32,
}

impl CellSplitProposalGovernanceV1 {
    fn validate(&self) -> Result<(), CellSplitProposalPlannerErrorV1> {
        if self.proposer_id.as_str().is_empty() || self.evaluator_id.as_str().is_empty() {
            return Err(CellSplitProposalPlannerErrorV1::EmptyId("governance actor"));
        }
        if self.proposer_id == self.evaluator_id {
            return Err(CellSplitProposalPlannerErrorV1::IndependentEvaluator);
        }
        if self.future_window_digest.is_zero() {
            return Err(CellSplitProposalPlannerErrorV1::EmptyDigest(
                "governance future window",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitProposalPlannerErrorV1 {
    Contract(CellRoleContractErrorV1),
    Split(codex_hepta_types::CellSplitContractErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    IndependentEvaluator,
    RoleMismatch,
    ActorMismatch,
    FutureWindowMismatch,
    TemplateMismatch,
    BenefitBelowThreshold,
    NegativeTransferAboveThreshold,
    ResourceCostAboveThreshold,
    AuthorityGranted,
}

impl fmt::Display for CellSplitProposalPlannerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellSplitProposalPlannerErrorV1 {}

impl From<codex_hepta_types::CellSplitContractErrorV1> for CellSplitProposalPlannerErrorV1 {
    fn from(value: codex_hepta_types::CellSplitContractErrorV1) -> Self {
        Self::Split(value)
    }
}

/// Pure, governed proposal planner.  The caller must still pass the result to
/// an independent evaluator and the durable publication owner.
pub struct CellSplitProposalPlannerV1;

impl CellSplitProposalPlannerV1 {
    pub fn plan(
        signal: &CellSplitProposalSignalV1,
        governance: &CellSplitProposalGovernanceV1,
        mut template: CellSplitV1,
    ) -> Result<CellSplitV1, CellSplitProposalPlannerErrorV1> {
        signal.validate()?;
        governance.validate()?;
        if signal.role != governance.role {
            return Err(CellSplitProposalPlannerErrorV1::RoleMismatch);
        }
        if signal.proposer_id != governance.proposer_id
            || signal.evaluator_id != governance.evaluator_id
            || template.proposer_id != signal.proposer_id
            || template.evaluator_id != signal.evaluator_id
            || template.parent_cell_id != signal.parent_cell_id
        {
            return Err(CellSplitProposalPlannerErrorV1::ActorMismatch);
        }
        if signal.future_window_digest != governance.future_window_digest {
            return Err(CellSplitProposalPlannerErrorV1::FutureWindowMismatch);
        }
        if signal.benefit_ppm < governance.minimum_benefit_ppm {
            return Err(CellSplitProposalPlannerErrorV1::BenefitBelowThreshold);
        }
        if signal.negative_transfer_ppm > governance.maximum_negative_transfer_ppm {
            return Err(CellSplitProposalPlannerErrorV1::NegativeTransferAboveThreshold);
        }
        if signal.resource_cost_ppm > governance.maximum_resource_cost_ppm {
            return Err(CellSplitProposalPlannerErrorV1::ResourceCostAboveThreshold);
        }
        template.validate_plan()?;
        if template.evaluation_subject_digest()? != signal.template_subject_digest {
            return Err(CellSplitProposalPlannerErrorV1::TemplateMismatch);
        }
        template.evaluation.evaluation_receipt_digest = signal.evaluation_receipt_digest;
        template.evaluation.retention_receipt_digest = signal.retention_receipt_digest;
        template.evaluation.negative_transfer_receipt_digest =
            signal.negative_transfer_receipt_digest;
        template.evaluation.cost_receipt_digest = signal.cost_receipt_digest;
        template.evidence_digest = signal.content_digest();
        template.validate()?;
        Ok(template)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(seed: u8) -> Digest32 {
        Digest32::from_array([seed; 32])
    }

    fn signal() -> CellSplitProposalSignalV1 {
        CellSplitProposalSignalV1 {
            signal_id: id("signal.1"),
            role: CellRoleV1::Decision,
            parent_cell_id: id("cell.parent"),
            proposer_id: id("proposer"),
            evaluator_id: id("evaluator"),
            template_subject_digest: digest(1),
            no_change_baseline_digest: digest(2),
            future_window_digest: digest(3),
            telemetry_digest: digest(4),
            long_term_gain_digest: digest(5),
            negative_transfer_digest: digest(6),
            resource_pressure_digest: digest(7),
            benefit_ppm: 800_000,
            negative_transfer_ppm: 10_000,
            resource_cost_ppm: 20_000,
            evaluation_receipt_digest: digest(8),
            retention_receipt_digest: digest(9),
            negative_transfer_receipt_digest: digest(10),
            cost_receipt_digest: digest(11),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn signal_is_validated_and_content_digest_is_stable() {
        let value = signal();
        value.validate().expect("valid signal");
        assert_eq!(value.content_digest(), value.content_digest());
    }

    #[test]
    fn governance_keeps_proposer_and_evaluator_separate() {
        let mut governance = CellSplitProposalGovernanceV1 {
            role: CellRoleV1::Decision,
            proposer_id: id("proposer"),
            evaluator_id: id("evaluator"),
            future_window_digest: digest(3),
            minimum_benefit_ppm: 500_000,
            maximum_negative_transfer_ppm: 50_000,
            maximum_resource_cost_ppm: 50_000,
        };
        governance.validate().expect("valid governance");
        governance.evaluator_id = governance.proposer_id.clone();
        assert_eq!(
            governance.validate(),
            Err(CellSplitProposalPlannerErrorV1::IndependentEvaluator)
        );
    }
}
