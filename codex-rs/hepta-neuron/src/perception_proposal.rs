//! Read-only active-observation advice. A positive assessment is neither a
//! reservation nor permission to read. The host's decision/budget owners must
//! recheck admission, reserve work and record all actual attempts in the existing
//! CellTaskCostV2 ledger, including unsuccessful or indeterminate acquisition.

use std::error::Error;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::CellCostMetricsV2;
use crate::CellTaskCostErrorV2;
use crate::CellTaskCostIdentityV2;
use crate::CellTaskCostV2;
use crate::perception::PerceptionObservationV1;
use crate::perception_source::MAX_PERCEPTION_RAW_BYTES;
use crate::perception_source::PerceptionCoordinatesV1;
use crate::perception_source::PerceptionSourceLayoutV1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PerceptionObservationTargetV1 {
    pub source_id: String,
    pub origin_digest: [u8; 32],
    pub coordinates: PerceptionCoordinatesV1,
}

/// Estimated cost covers all additional acquisition, encoding, communication,
/// prediction and decision work. Missing measurements remain None, never zero.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PerceptionObservationProposalV1 {
    pub schema: String,
    pub proposal_id: String,
    pub scope_digest: [u8; 32],
    pub source_frontier: [u8; 32],
    pub evidence_digest: [u8; 32],
    pub predictor_digest: [u8; 32],
    pub ndu_snapshot_digest: [u8; 32],
    pub target: PerceptionObservationTargetV1,
    /// Predicted change in final-task success probability, in [-1, 1] Q24.
    pub expected_task_gain_q24: i64,
    pub estimated_cost: CellCostMetricsV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PerceptionProposalPolicyV1 {
    pub predictor_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub cost_identity: CellTaskCostIdentityV2,
    /// Total task limits. A wall-work cap is mandatory; other None fields mean
    /// the policy does not cap that metric, not that its usage is measured zero.
    pub maximum_total_cost: CellCostMetricsV2,
    pub minimum_task_gain_q24: i64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PerceptionProposalDispositionV1 {
    Eligible,
    InsufficientGain,
    UnmeasuredCost,
    BudgetExceeded,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PerceptionProposalAssessmentV1 {
    pub proposal_digest: Digest32,
    pub cost_ledger_digest: Digest32,
    pub disposition: PerceptionProposalDispositionV1,
    pub authority: AuthorityPosture,
}

impl PerceptionObservationProposalV1 {
    pub fn assess(
        &self,
        observation: &PerceptionObservationV1,
        policy: &PerceptionProposalPolicyV1,
        cost: &CellTaskCostV2,
    ) -> Result<PerceptionProposalAssessmentV1, PerceptionProposalErrorV1> {
        const Q: i64 = 1 << 24;
        if self.schema != "hepta.perception.proposal.v1"
            || StableId::new(self.proposal_id.as_str()).is_err()
            || !(-Q..=Q).contains(&self.expected_task_gain_q24)
        {
            return Err(PerceptionProposalErrorV1::InvalidProposal);
        }
        if policy.predictor_digest.is_zero() || policy.ndu_snapshot_digest.is_zero()
            || policy.maximum_total_cost.wall_micros.is_none()
            || !(0..=Q).contains(&policy.minimum_task_gain_q24)
        {
            return Err(PerceptionProposalErrorV1::InvalidPolicy);
        }
        if self.predictor_digest != policy.predictor_digest.into_array()
            || self.ndu_snapshot_digest != policy.ndu_snapshot_digest.into_array()
        {
            return Err(PerceptionProposalErrorV1::BindingMismatch);
        }
        let evidence = observation.evidence_digest().map_err(|_| PerceptionProposalErrorV1::StaleObservation)?;
        if self.scope_digest != observation.scope_digest || self.source_frontier != observation.source_frontier
            || self.evidence_digest != evidence.into_array()
        {
            return Err(PerceptionProposalErrorV1::StaleObservation);
        }
        let source = &observation.evidence.iter().find(|evidence| evidence.source.source_id == self.target.source_id
            && evidence.source.origin_digest == self.target.origin_digest)
            .ok_or(PerceptionProposalErrorV1::InvalidTarget)?.source;
        match (&source.layout, &self.target.coordinates) {
            (PerceptionSourceLayoutV1::Bytes { origin_length, .. }, PerceptionCoordinatesV1::Bytes { start, end }) => {
                if start >= end || end > origin_length || end - start > MAX_PERCEPTION_RAW_BYTES as u64 {
                    return Err(PerceptionProposalErrorV1::InvalidTarget);
                }
            }
            _ => { source.raw_ranges(&self.target.coordinates).map_err(|_| PerceptionProposalErrorV1::InvalidTarget)?; }
        }
        if cost.identity() != policy.cost_identity {
            return Err(PerceptionProposalErrorV1::CostIdentityMismatch);
        }
        let summary = cost.summary().map_err(PerceptionProposalErrorV1::InvalidCostLedger)?;
        let disposition = if self.expected_task_gain_q24 <= policy.minimum_task_gain_q24 {
            PerceptionProposalDispositionV1::InsufficientGain
        } else if !summary.missing_stages.is_empty() || summary.unknown_outcome_entries != 0 {
            // The frozen metering contract must explicitly account for no-work
            // stages. An absent stage or unresolved attempt is not free work.
            PerceptionProposalDispositionV1::UnmeasuredCost
        } else {
            let predicted = self.estimated_cost;
            let maximum = policy.maximum_total_cost;
            let metrics = [
                (summary.wall_work_micros, predicted.wall_micros, maximum.wall_micros),
                (summary.cpu_micros, predicted.cpu_micros, maximum.cpu_micros),
                (summary.energy_microjoules, predicted.energy_microjoules, maximum.energy_microjoules),
                (summary.storage_read_bytes, predicted.storage_read_bytes, maximum.storage_read_bytes),
                (summary.storage_write_bytes, predicted.storage_write_bytes, maximum.storage_write_bytes),
                (summary.storage_byte_micros, predicted.storage_byte_micros, maximum.storage_byte_micros),
                (summary.communication_bytes, predicted.communication_bytes, maximum.communication_bytes),
            ];
            let mut disposition = PerceptionProposalDispositionV1::Eligible;
            for (actual, estimate, limit) in metrics {
                if let Some(limit) = limit {
                    let Some(estimate) = estimate.filter(|_| actual.unknown_entries == 0) else {
                        disposition = PerceptionProposalDispositionV1::UnmeasuredCost;
                        break;
                    };
                    if actual.known_sum.checked_add(estimate).is_none_or(|total| total > limit) {
                        disposition = PerceptionProposalDispositionV1::BudgetExceeded;
                        break;
                    }
                }
            }
            disposition
        };
        let proposal_bytes = serde_json::to_vec(self).map_err(|_| PerceptionProposalErrorV1::InvalidProposal)?;
        let ledger_bytes = serde_json::to_vec(cost).map_err(|_| PerceptionProposalErrorV1::InvalidProposal)?;
        Ok(PerceptionProposalAssessmentV1 {
            proposal_digest: Digest32::of_bytes(&proposal_bytes),
            cost_ledger_digest: Digest32::of_bytes(&ledger_bytes),
            disposition,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PerceptionProposalErrorV1 {
    InvalidProposal, InvalidPolicy, InvalidTarget, BindingMismatch,
    StaleObservation, CostIdentityMismatch, InvalidCostLedger(CellTaskCostErrorV2),
}

impl fmt::Display for PerceptionProposalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result { write!(formatter, "{self:?}") }
}
impl Error for PerceptionProposalErrorV1 {}

#[cfg(test)]
#[path = "perception_proposal_tests.rs"]
mod tests;
