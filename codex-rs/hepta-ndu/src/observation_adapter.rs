use codex_hepta_neuron::CellEvidenceV1;

use crate::GroupCellObservationV1;
use crate::GroupSystem2Error;

/// Convert authenticated Cell/runtime evidence into the Group NDU's
/// observation shape. Q24 values are widened to Q32 without changing their
/// sign or ordering; resource cost is execution time plus queue age.
pub fn group_cell_observation_from_evidence_v1(
    evidence: &CellEvidenceV1,
) -> Result<GroupCellObservationV1, GroupSystem2Error> {
    if evidence.evidence_digest.is_zero() {
        return Err(GroupSystem2Error::ZeroDigest("cell evidence"));
    }
    if evidence.head_digest.is_zero() {
        return Err(GroupSystem2Error::ZeroDigest("head"));
    }
    if evidence.action_digest.is_zero() {
        return Err(GroupSystem2Error::ZeroDigest("action"));
    }
    if evidence.uncertainty_q24 < 0 {
        return Err(GroupSystem2Error::NegativeUncertainty);
    }
    let value_q32 = q24_to_q32(evidence.value_q24)?;
    let uncertainty_q32 = q24_to_q32(evidence.uncertainty_q24)?;
    let cost_micros = evidence
        .resource_receipt
        .execution_micros
        .checked_add(evidence.resource_receipt.queue_age_micros)
        .ok_or(GroupSystem2Error::ArithmeticOverflow)?;

    Ok(GroupCellObservationV1 {
        cell_id: evidence.cell_id.as_str().to_owned(),
        head_digest: evidence.head_digest,
        action_digest: evidence.action_digest,
        evidence_digest: evidence.evidence_digest,
        value_q32,
        cost_micros,
        uncertainty_q32,
        abstain: evidence.abstain,
    })
}

fn q24_to_q32(value_q24: i64) -> Result<i64, GroupSystem2Error> {
    let widened = i128::from(value_q24)
        .checked_shl(8)
        .ok_or(GroupSystem2Error::ArithmeticOverflow)?;
    i64::try_from(widened).map_err(|_| GroupSystem2Error::ArithmeticOverflow)
}

#[cfg(test)]
#[path = "observation_adapter_tests.rs"]
mod tests;
