//! Decode the existing complete committed receipt, with a canonical roundtrip.
//! This reconstructs advisory data only and always keeps DENY_ALL authority.

use codex_hepta_neuron::CellExecutionCostV1;
use codex_hepta_neuron::CellPolicyEntryV1;
use codex_hepta_neuron::CellRepresentationV1;
use codex_hepta_types::AuthorityPosture;

use super::*;

pub(super) fn decode_original_decision(
    bytes: &[u8],
    representation: &[u8],
) -> Result<CellDecisionReceiptV1, Error> {
    bounded(bytes)?;
    bounded(representation)?;
    let mut r = Reader(
        bytes
            .strip_prefix(b"hepta.circuit.committed-cell-decision.v1\0")
            .ok_or(Error::InvalidBinding)?,
    );
    let operation_id = r.id()?;
    let agent_id = r.id()?;
    let cell_id = r.id()?;
    let run_id = r.id()?;
    let selected_candidate = r.id()?;
    let operation_digest = r.digest()?;
    let semantic_request_digest = r.digest()?;
    let principal_digest = r.digest()?;
    let bundle_digest = r.digest()?;
    let source_frontier = r.digest()?;
    let checkpoint_before = r.digest()?;
    let checkpoint_after = r.digest()?;
    let model_output_digest = r.digest()?;
    let confidence_ppm = u32::from_be_bytes(r.take()?);
    let ood_ppm = u32::from_be_bytes(r.take()?);
    let deadline_exceeded = match r.take::<1>()? {
        [0] => false,
        [1] => true,
        _ => return Err(Error::InvalidBinding),
    };
    let cost = CellExecutionCostV1 {
        model_latency_micros: u64::from_be_bytes(r.take()?),
        queue_age_micros: u64::from_be_bytes(r.take()?),
        resident_bytes: u64::from_be_bytes(r.take()?),
        transient_allocation_bytes: u64::from_be_bytes(r.take()?),
        checkpoint_bytes: u64::from_be_bytes(r.take()?),
        consumed_input_bytes: u64::from_be_bytes(r.take()?)
            .try_into()
            .map_err(|_| Error::InvalidBinding)?,
        truncated_input_bytes: u64::from_be_bytes(r.take()?)
            .try_into()
            .map_err(|_| Error::InvalidBinding)?,
    };
    let count = u32::from_be_bytes(r.take()?) as usize;
    if !(1..=256).contains(&count) {
        return Err(Error::InvalidBinding);
    }
    let mut policy = Vec::with_capacity(count);
    for _ in 0..count {
        let candidate_id = r.id()?;
        let allowed = match r.take::<1>()? {
            [0] => false,
            [1] => true,
            _ => return Err(Error::InvalidBinding),
        };
        policy.push(CellPolicyEntryV1 {
            candidate_id,
            allowed,
            probability_ppm: u32::from_be_bytes(r.take()?),
        });
    }
    if r.take::<1>()? != [0] {
        return Err(Error::InvalidBinding);
    }
    r.end()?;
    let (drive_q24, prediction_q24): (Vec<i64>, Vec<i64>) =
        serde_json::from_slice(representation).map_err(|_| Error::InvalidBinding)?;
    if json(&(&drive_q24, &prediction_q24))? != representation {
        return Err(Error::InvalidBinding);
    }
    let channels = Arc::new(CellRepresentationV1 {
        drive_q24,
        prediction_q24,
    });
    channels
        .validate()
        .map_err(crate::CircuitCellErrorV1::from)?;
    let receipt = CellDecisionReceiptV1 {
        operation_id,
        operation_digest,
        semantic_request_digest,
        scope: CellScopeV1 {
            agent_id,
            cell_id,
            run_id,
            principal_digest,
        },
        bundle_digest,
        source_frontier,
        checkpoint_before,
        checkpoint_after,
        model_output_digest,
        representation: channels,
        policy,
        selected_candidate,
        confidence_ppm,
        ood_ppm,
        deadline_exceeded,
        cost,
        authority: AuthorityPosture::DENY_ALL,
    };
    if crate::circuit_cell_output::encode_receipt(&receipt)? != bytes {
        return Err(Error::InvalidBinding);
    }
    Ok(receipt)
}
