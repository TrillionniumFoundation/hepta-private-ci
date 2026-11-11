//! Exact generation bindings, bounded result encoding and measured control costs.

use std::time::Duration;

use codex_hepta_infer_core::durable_control::Error as ControlError;
use codex_hepta_infer_core::durable_control::generation::GenerationBindingV1;
use codex_hepta_infer_core::durable_control::generation::MAX_GENERATION_PAYLOAD_BYTES;
use codex_hepta_infer_core::durable_control::generation::MAX_GENERATION_RESULT_BYTES;
use codex_hepta_types::Digest32;
use serde::Serialize;

use super::ControlledCellGenerationConfigV2;
use crate::cell_generation_types::*;
use crate::cell_task_cost::*;

pub(super) fn prepare(
    config: &ControlledCellGenerationConfigV2,
    request: &CellGenerationRequestV2,
) -> Result<(GenerationBindingV1, Vec<u8>), CellGenerationErrorV2> {
    let request_digest = request.digest()?;
    let manifest_digest = config.manifest.digest()?;
    if request.predecessor.scope != config.scope
        || request.predecessor.manifest_digest != manifest_digest
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    if request.input.len() > config.manifest.max_input_bytes as usize
        || request.predecessor.state.len() > config.manifest.max_state_bytes as usize
        || request.predecessor.prefix.len() > config.manifest.max_prefix_bytes as usize
    {
        return Err(CellGenerationErrorV2::Capacity);
    }
    #[derive(Serialize)]
    struct Payload<'a> {
        schema_version: u32,
        manifest: &'a CellBackendManifestV2,
        request: &'a CellGenerationRequestV2,
    }
    let payload = serde_json::to_vec(&Payload {
        schema_version: 2,
        manifest: &config.manifest,
        request,
    })
    .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    if payload.len() > MAX_GENERATION_PAYLOAD_BYTES {
        return Err(CellGenerationErrorV2::Capacity);
    }
    let identity = digest(
        b"hepta.cell.control-operation.v2\0",
        &(&config.scope, &request.operation_id),
    )?;
    let binding = GenerationBindingV1 {
        request_id: Digest32::from_array(identity).to_string(),
        principal_id: Digest32::from_array(config.scope.principal_digest).to_string(),
        worker_generation: config.worker_generation,
        manifest_digest,
        request_digest,
        predecessor_digest: request.predecessor.digest()?,
        payload_digest: Digest32::of_bytes(&payload).into_array(),
        payload_bytes: u32::try_from(payload.len()).map_err(|_| CellGenerationErrorV2::Capacity)?,
        result_limit_bytes: MAX_GENERATION_RESULT_BYTES as u32,
        deadline_micros: request.deadline_micros,
    };
    Ok((binding, payload))
}

pub(super) fn validate(
    manifest: &CellBackendManifestV2,
    request: &CellGenerationRequestV2,
    proposal: &CellGenerationProposalV2,
) -> Result<(), CellGenerationErrorV2> {
    if proposal.request_digest != request.digest()?
        || proposal.bundle_digest != manifest.bundle_digest
        || proposal.runtime_digest != manifest.runtime_digest
        || proposal.device_digest != manifest.device_digest
        || proposal.cost.identity()
            != (CellTaskCostIdentityV2 {
                task_digest: request.task_digest,
                source_digest: manifest.source_digest,
            })
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    proposal
        .cost
        .validate()
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    if proposal.successor_state.len() > manifest.max_state_bytes as usize
        || proposal.output_delta.len() > manifest.max_delta_bytes as usize
        || proposal.cost.entries().len() > manifest.max_step_cost_entries as usize
    {
        return Err(CellGenerationErrorV2::Capacity);
    }
    if !matches!(
        proposal.disposition,
        CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped
    ) && (proposal.successor_state != request.predecessor.state
        || !proposal.output_delta.is_empty())
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(())
}

pub(super) fn encode(
    manifest: &CellBackendManifestV2,
    request: &CellGenerationRequestV2,
    proposal: &CellGenerationProposalV2,
) -> Result<Vec<u8>, CellGenerationErrorV2> {
    validate(manifest, request, proposal)?;
    let bytes = serde_json::to_vec(proposal).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    if bytes.len() > MAX_GENERATION_RESULT_BYTES {
        return Err(CellGenerationErrorV2::Capacity);
    }
    Ok(bytes)
}

pub(super) fn no_compute(
    manifest: &CellBackendManifestV2,
    request: &CellGenerationRequestV2,
    disposition: CellGenerationDispositionV2,
) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
    Ok(CellGenerationProposalV2 {
        request_digest: request.digest()?,
        bundle_digest: manifest.bundle_digest,
        runtime_digest: manifest.runtime_digest,
        device_digest: manifest.device_digest,
        successor_state: request.predecessor.state.clone(),
        output_delta: Vec::new(),
        disposition,
        cost: CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: request.task_digest,
            source_digest: manifest.source_digest,
        })
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
    })
}

pub(super) fn add_cost(
    proposal: &mut CellGenerationProposalV2,
    queue_micros: u64,
    control_micros: u64,
) -> Result<(), CellGenerationErrorV2> {
    for (domain, stage, wall) in [
        (b"queue".as_slice(), CellCostStageV2::Queue, queue_micros),
        (
            b"control".as_slice(),
            CellCostStageV2::Persistence,
            control_micros,
        ),
    ] {
        proposal
            .cost
            .record(CellCostEntryV2 {
                event_id: Digest32::of_parts(&[
                    b"hepta.cell.control-cost.v2\0",
                    &proposal.request_digest,
                    domain,
                ])
                .into_array(),
                identity: proposal.cost.identity(),
                stage,
                outcome: CellCostOutcomeV2::Succeeded,
                accounting: CellCostAccountingV2::Exclusive,
                metrics: CellCostMetricsV2 {
                    wall_micros: Some(wall),
                    ..CellCostMetricsV2::default()
                },
            })
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    }
    Ok(())
}

pub(super) fn micros(duration: Duration) -> Result<u64, CellGenerationErrorV2> {
    u64::try_from(duration.as_micros()).map_err(|_| CellGenerationErrorV2::Capacity)
}

pub(super) fn control_error(error: ControlError) -> CellGenerationErrorV2 {
    match error {
        ControlError::InvalidIdentity(_)
        | ControlError::InvalidDigest(_)
        | ControlError::InvalidTokens => CellGenerationErrorV2::InvalidBinding,
        ControlError::InvalidTime => CellGenerationErrorV2::Deadline,
        ControlError::CapacityExceeded
        | ControlError::UsageExceeded
        | ControlError::ArithmeticOverflow => CellGenerationErrorV2::Capacity,
        ControlError::RequestNotFound
        | ControlError::Conflict
        | ControlError::InvalidTransition
        | ControlError::StaleRevision
        | ControlError::ReservationMismatch
        | ControlError::AssignmentMismatch => CellGenerationErrorV2::Conflict,
        ControlError::TerminalObservationMissing => CellGenerationErrorV2::Pending,
        ControlError::CorruptJournal(_) => CellGenerationErrorV2::Corrupt,
        ControlError::Io(_) | ControlError::WriterUnavailable => {
            CellGenerationErrorV2::CommitUncertain
        }
    }
}
