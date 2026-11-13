//! Canonical data for the fixed task lane. None of these decoders constructs
//! an AutomationStore admission, a committed trace or a task receipt.

use std::sync::Arc;

use codex_hepta_automation::CircuitDispatchV2;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::CellExecutionCostV1;
use codex_hepta_neuron::CellPolicyEntryV1;
use codex_hepta_neuron::CellRepresentationV1;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::Error;
use super::wire::Reader;
use super::wire::blob;
use super::wire::bounded;

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct DispatchData {
    run_id: String,
    activation_id: u64,
    program_id: String,
    node_id: String,
    round: u32,
    input_digest: Sha256Digest,
    input_schema: Sha256Digest,
    output_schema: Sha256Digest,
    scope_digest: Sha256Digest,
    parameter_bundle_digest: Sha256Digest,
    route_policy_digest: Sha256Digest,
    max_work: u64,
    candidate_edges: Vec<String>,
    invocation_digest: Sha256Digest,
}

pub(super) fn dispatch(bytes: &[u8]) -> Result<CircuitDispatchV2, Error> {
    bounded(bytes)?;
    let data: DispatchData = serde_json::from_slice(bytes).map_err(|_| Error::InvalidBinding)?;
    if data.candidate_edges.len() > 256 {
        return Err(Error::InvalidBinding);
    }
    for text in [&data.run_id, &data.program_id, &data.node_id]
        .into_iter().chain(&data.candidate_edges)
    {
        if text.is_empty() || text.len() > 128 || text.chars().any(char::is_control) {
            return Err(Error::InvalidBinding);
        }
    }
    let value = CircuitDispatchV2 {
        run_id: data.run_id, activation_id: data.activation_id,
        program_id: data.program_id, node_id: data.node_id, round: data.round,
        input_digest: data.input_digest, input_schema: data.input_schema,
        output_schema: data.output_schema, scope_digest: data.scope_digest,
        parameter_bundle_digest: data.parameter_bundle_digest,
        route_policy_digest: data.route_policy_digest, max_work: data.max_work,
        candidate_edges: data.candidate_edges, invocation_digest: data.invocation_digest,
    };
    if encode_dispatch(&value)? != bytes { return Err(Error::InvalidBinding); }
    Ok(value)
}

pub(super) fn encode_dispatch(value: &CircuitDispatchV2) -> Result<Vec<u8>, Error> {
    let bytes = serde_json::to_vec(value).map_err(|_| Error::InvalidBinding)?;
    bounded(&bytes)?;
    Ok(bytes)
}

pub(super) fn encode_decision(value: &CellDecisionReceiptV1) -> Result<Vec<u8>, Error> {
    value.representation.validate().map_err(crate::CircuitCellErrorV1::from)?;
    let canonical = crate::circuit_cell_output::encode_receipt(value)?;
    let representation = serde_json::to_vec(&(
        &value.representation.drive_q24, &value.representation.prediction_q24,
    )).map_err(|_| Error::InvalidBinding)?;
    let mut bytes = b"HCRTDEC1".to_vec();
    blob(&mut bytes, &canonical)?;
    blob(&mut bytes, &representation)?;
    Ok(bytes)
}

/// Decode advisory data only, then require the original complete canonical
/// receipt encoding. Its authority is fixed DENY_ALL. Only the actual Cell
/// owner or its pinned readback lane can establish where these data came from.
pub(super) fn decision(bytes: &[u8]) -> Result<CellDecisionReceiptV1, Error> {
    let mut outer = Reader::new(bytes, b"HCRTDEC1")?;
    let encoded = outer.blob()?;
    let representation = outer.blob()?;
    outer.end()?;
    let mut r = Reader::new(encoded, b"hepta.circuit.committed-cell-decision.v1\0")?;
    let operation_id = id(&mut r)?;
    let agent_id = id(&mut r)?;
    let cell_id = id(&mut r)?;
    let run_id = id(&mut r)?;
    let selected_candidate = id(&mut r)?;
    let operation_digest = digest(&mut r)?;
    let semantic_request_digest = digest(&mut r)?;
    let principal_digest = digest(&mut r)?;
    let bundle_digest = digest(&mut r)?;
    let source_frontier = digest(&mut r)?;
    let checkpoint_before = digest(&mut r)?;
    let checkpoint_after = digest(&mut r)?;
    let model_output_digest = digest(&mut r)?;
    let confidence_ppm = u32::from_be_bytes(r.take()?);
    let ood_ppm = u32::from_be_bytes(r.take()?);
    let deadline_exceeded = boolean(&mut r)?;
    let cost = CellExecutionCostV1 {
        model_latency_micros: r.u64()?, queue_age_micros: r.u64()?,
        resident_bytes: r.u64()?, transient_allocation_bytes: r.u64()?,
        checkpoint_bytes: r.u64()?,
        consumed_input_bytes: usize::try_from(r.u64()?).map_err(|_| Error::InvalidBinding)?,
        truncated_input_bytes: usize::try_from(r.u64()?).map_err(|_| Error::InvalidBinding)?,
    };
    let count = u32::from_be_bytes(r.take()?);
    if !(1..=256).contains(&count) { return Err(Error::InvalidBinding); }
    let mut policy = Vec::new();
    for _ in 0..count {
        policy.push(CellPolicyEntryV1 {
            candidate_id: id(&mut r)?, allowed: boolean(&mut r)?,
            probability_ppm: u32::from_be_bytes(r.take()?),
        });
    }
    if r.take::<1>()? != [0] { return Err(Error::InvalidBinding); }
    r.end()?;
    let (drive_q24, prediction_q24): (Vec<i64>, Vec<i64>) =
        serde_json::from_slice(representation).map_err(|_| Error::InvalidBinding)?;
    let value = CellDecisionReceiptV1 {
        operation_id, operation_digest, semantic_request_digest,
        scope: CellScopeV1 { agent_id, cell_id, run_id, principal_digest },
        bundle_digest, source_frontier, checkpoint_before, checkpoint_after,
        model_output_digest, representation: Arc::new(CellRepresentationV1 {
            drive_q24, prediction_q24,
        }), policy, selected_candidate, confidence_ppm, ood_ppm,
        deadline_exceeded, cost, authority: AuthorityPosture::DENY_ALL,
    };
    if encode_decision(&value)? != bytes { return Err(Error::InvalidBinding); }
    Ok(value)
}

fn id(reader: &mut Reader<'_>) -> Result<StableId, Error> {
    StableId::new(std::str::from_utf8(reader.blob()?).map_err(|_| Error::InvalidBinding)?)
        .map_err(|_| Error::InvalidBinding)
}
fn digest(reader: &mut Reader<'_>) -> Result<Digest32, Error> {
    Ok(Digest32::from_array(reader.take()?))
}
fn boolean(reader: &mut Reader<'_>) -> Result<bool, Error> {
    match reader.take::<1>()? {
        [0] => Ok(false), [1] => Ok(true), _ => Err(Error::InvalidBinding),
    }
}
