//! Advisory check selection; these estimates never authorize effects or settle them.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::ActionSkillBindingV1;
use crate::ActionSkillError;
use crate::ActionSkillObservationV1;
use crate::action_skill::evidence_digest;

const PROBABILITY_SCALE: u128 = 1_000_000;

/// All probabilities are conditional estimates in millionths, not certificates.
/// Detection/false positive rates condition on an erroneous/correct effect;
/// remediation success conditions on a true positive. Response cost is paid
/// even when remediation fails. Both response costs include all follow-up work;
/// false-positive response cost also includes any induced harm in the same unit.
/// Costs are conditional expectations in that single additive unit. No
/// conversion between currency, time, energy or work units is inferred.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionCheckEstimateV1 {
    pub error_ppm: u32,
    pub detection_ppm: u32,
    pub false_positive_ppm: u32,
    pub remediation_success_ppm: u32,
    pub error_loss: u64,
    pub check_cost: u64,
    pub true_positive_response_cost: u64,
    pub false_positive_response_cost: u64,
}

/// Host-supplied clock evidence. Matching identifiers do not authenticate clocks.
/// Missing timing remains Unknown; it is never replaced with zero elapsed time.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum ActionCheckTimeV1 {
    Unknown,
    Known {
        clock_id: String,
        occurred_at_ms: u64,
        available_at_ms: u64,
        max_age_ms: u64,
    },
}

/// A separately supplied current cut, rather than a timestamp replayed inside
/// the plan. The host must obtain it from the named clock for this assessment.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum ActionCheckClockV1 {
    Unknown,
    Known { clock_id: String, at_ms: u64 },
}

/// Pins supplied by the host's frozen prediction/check policy. These digests
/// name that policy; this shape check does not authenticate its model, source,
/// calibration, remediation implementation or cost-unit conversion.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionCheckPlanV1 {
    pub binding: ActionSkillBindingV1,
    pub generation: u64,
    pub effective_model_digest: Sha256Digest,
    pub source_frontier_digest: Sha256Digest,
    pub checker_digest: Sha256Digest,
    pub remediation_digest: Sha256Digest,
    pub cost_unit: String,
    pub timing: ActionCheckTimeV1,
    pub estimate: ActionCheckEstimateV1,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionCheckRecommendationV1 {
    Check,
    Skip,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionCheckAssessmentV1 {
    pub assessment_digest: Sha256Digest,
    pub recommendation: ActionCheckRecommendationV1,
}

/// The original ACT observation is retained without turning Unknown, Partial,
/// a provider error or a prediction into a terminal business outcome.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionCheckReadbackV1 {
    pub observation: ActionSkillObservationV1,
    pub assessment: ActionCheckAssessmentV1,
}

impl ActionCheckPlanV1 {
    pub fn assess(
        &self,
        original_binding: &ActionSkillBindingV1,
        current: &ActionCheckClockV1,
    ) -> Result<ActionCheckAssessmentV1, ActionSkillError> {
        let estimate = &self.estimate;
        if self.binding != *original_binding
            || original_binding.provider_intent.validate().is_err()
            || original_binding.destination_id.is_empty()
            || original_binding.destination_id.len() > 128
            || original_binding
                .destination_id
                .chars()
                .any(char::is_whitespace)
            || self.generation == 0
            || self.cost_unit.is_empty()
            || self.cost_unit.len() > 64
            || self.cost_unit.chars().any(char::is_whitespace)
            || [
                &original_binding.effect_intent_digest,
                &original_binding.contract_digest,
                &self.effective_model_digest,
                &self.source_frontier_digest,
                &self.checker_digest,
                &self.remediation_digest,
            ]
            .into_iter()
            .any(|digest| Sha256Digest::parse(digest.as_str()).is_err())
            || [
                estimate.error_ppm,
                estimate.detection_ppm,
                estimate.false_positive_ppm,
                estimate.remediation_success_ppm,
            ]
            .into_iter()
            .any(|probability| u128::from(probability) > PROBABILITY_SCALE)
        {
            return Err(ActionSkillError::Invocation);
        }
        // Unknown availability must not bypass the bounds on supplied evidence.
        // Validate each present clock before serializing it into the receipt.
        let source_clock = match &self.timing {
            ActionCheckTimeV1::Unknown => None,
            ActionCheckTimeV1::Known {
                clock_id,
                occurred_at_ms,
                available_at_ms,
                ..
            } => {
                if occurred_at_ms > available_at_ms {
                    return Err(ActionSkillError::Observation);
                }
                Some(clock_id)
            }
        };
        let current_clock = match current {
            ActionCheckClockV1::Unknown => None,
            ActionCheckClockV1::Known { clock_id, .. } => Some(clock_id),
        };
        if source_clock
            .into_iter()
            .chain(current_clock)
            .any(|id| id.is_empty() || id.len() > 128 || id.chars().any(char::is_whitespace))
        {
            return Err(ActionSkillError::Observation);
        }
        let fresh = match (&self.timing, current) {
            (ActionCheckTimeV1::Unknown, _) | (_, ActionCheckClockV1::Unknown) => false,
            (
                ActionCheckTimeV1::Known {
                    clock_id,
                    occurred_at_ms,
                    available_at_ms,
                    max_age_ms,
                },
                ActionCheckClockV1::Known {
                    clock_id: current_clock,
                    at_ms,
                },
            ) => {
                if clock_id != current_clock {
                    false
                } else if available_at_ms > at_ms {
                    return Err(ActionSkillError::Observation);
                } else {
                    at_ms - occurred_at_ms <= *max_age_ms
                }
            }
        };
        // Compare exact rational expectations with common denominator 10^18.
        // Each product fits u128 even at u64::MAX costs; the three cost terms
        // sum to at most 3 * u64::MAX * 10^18, also below u128::MAX.
        let risk = u128::from(estimate.error_ppm);
        let detection = u128::from(estimate.detection_ppm);
        let true_positive = risk * detection;
        let benefit = true_positive
            * u128::from(estimate.remediation_success_ppm)
            * u128::from(estimate.error_loss);
        let costs =
            true_positive * PROBABILITY_SCALE * u128::from(estimate.true_positive_response_cost)
                + (PROBABILITY_SCALE - risk)
                    * u128::from(estimate.false_positive_ppm)
                    * PROBABILITY_SCALE
                    * u128::from(estimate.false_positive_response_cost)
                + PROBABILITY_SCALE.pow(3) * u128::from(estimate.check_cost);
        Ok(ActionCheckAssessmentV1 {
            assessment_digest: evidence_digest(
                b"hepta.action-check.assessment.v1\0",
                &(self, current),
            )?,
            recommendation: if !fresh {
                ActionCheckRecommendationV1::Unknown
            } else if benefit > costs {
                ActionCheckRecommendationV1::Check
            } else {
                ActionCheckRecommendationV1::Skip
            },
        })
    }
}

#[cfg(test)]
#[path = "action_check_tests.rs"]
mod tests;
