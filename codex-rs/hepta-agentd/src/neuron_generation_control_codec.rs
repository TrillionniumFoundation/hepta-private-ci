//! Bounded observations of existing owner values; no second persistent state.

use codex_hepta_agent_protocol::GenerationCostSummaryV1;
use codex_hepta_agent_protocol::GenerationCostTotalV1;
use codex_hepta_agent_protocol::GenerationDispositionV1;
use codex_hepta_agent_protocol::GenerationOutputReferenceV1;
use codex_hepta_agent_protocol::GenerationPendingV1;
use codex_hepta_agent_protocol::GenerationReceiptV1;
use codex_hepta_agent_protocol::GenerationStepV1;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellCostTotalV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2 as Error;
use codex_hepta_neuron::CellGenerationReceiptV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellOutputChunkV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;
use serde::Serialize;

pub(super) fn digest(domain: &[u8], value: &impl Serialize) -> Result<[u8; 32], Error> {
    let bytes = serde_json::to_vec(value).map_err(|_| Error::InvalidBinding)?;
    Ok(Digest32::of_parts(&[domain, &bytes]).into_array())
}

pub(super) fn operation_id(request: &GenerationStepV1) -> Result<String, Error> {
    Ok(format!(
        "generation-control-v1-{}",
        Digest32::from_array(digest(b"hepta.agentd.generation-step.v1\0", request)?)
    ))
}

pub(super) fn pending(request: &CellGenerationRequestV2) -> Result<GenerationPendingV1, Error> {
    Ok(GenerationPendingV1 {
        operation_id: request.operation_id.clone(),
        request_digest: request.digest()?,
        admitted_at_micros: request.admitted_at_micros,
        deadline_micros: request.deadline_micros,
    })
}

pub(super) fn output(chunk: &CellOutputChunkV2) -> Result<GenerationOutputReferenceV1, Error> {
    Ok(GenerationOutputReferenceV1 {
        operation_id: chunk.operation_id.clone(),
        request_digest: chunk.request_digest,
        prefix_offset: chunk.prefix_offset,
        bytes: chunk.bytes.len() as u32,
        chunk_digest: digest(b"hepta.agentd.generation-output.v1\0", chunk)?,
    })
}

pub(super) fn receipt(value: CellGenerationReceiptV2) -> Result<GenerationReceiptV1, Error> {
    Ok(GenerationReceiptV1 {
        operation_id: value.operation_id,
        request_digest: value.request_digest,
        proposal_digest: value.proposal_digest,
        checkpoint_after: value.checkpoint_after,
        disposition: match value.disposition {
            CellGenerationDispositionV2::Advanced => GenerationDispositionV1::Advanced,
            CellGenerationDispositionV2::Stopped => GenerationDispositionV1::Stopped,
            CellGenerationDispositionV2::Cancelled => GenerationDispositionV1::Cancelled,
            CellGenerationDispositionV2::Failed => GenerationDispositionV1::Failed,
            CellGenerationDispositionV2::Rejected => GenerationDispositionV1::Rejected,
            CellGenerationDispositionV2::DeadlineExceeded => {
                GenerationDispositionV1::DeadlineExceeded
            }
        },
        cost_digest: digest(b"hepta.agentd.generation-cost.v1\0", &value.cost)?,
        cost_entries: value.cost.entries().len() as u32,
    })
}

pub(super) fn cost(value: &CellTaskCostV2) -> Result<GenerationCostSummaryV1, Error> {
    let summary = value.summary().map_err(|_| Error::InvalidBinding)?;
    Ok(GenerationCostSummaryV1 {
        task_digest: value.identity().task_digest,
        source_digest: value.identity().source_digest,
        ledger_digest: digest(b"hepta.agentd.generation-cost.v1\0", value)?,
        wall_work_micros: total(summary.wall_work_micros),
        cpu_micros: total(summary.cpu_micros),
        energy_microjoules: total(summary.energy_microjoules),
        storage_read_bytes: total(summary.storage_read_bytes),
        storage_write_bytes: total(summary.storage_write_bytes),
        storage_byte_micros: total(summary.storage_byte_micros),
        communication_bytes: total(summary.communication_bytes),
        missing_stages: summary
            .missing_stages
            .into_iter()
            .map(|stage| {
                match stage {
                    CellCostStageV2::Encoder => "encoder",
                    CellCostStageV2::Routing => "routing",
                    CellCostStageV2::Inference => "inference",
                    CellCostStageV2::Training => "training",
                    CellCostStageV2::Planning => "planning",
                    CellCostStageV2::Critic => "critic",
                    CellCostStageV2::Codec => "codec",
                    CellCostStageV2::Queue => "queue",
                    CellCostStageV2::Persistence => "persistence",
                    CellCostStageV2::Recovery => "recovery",
                    CellCostStageV2::Communication => "communication",
                    CellCostStageV2::Evaluation => "evaluation",
                }
                .to_string()
            })
            .collect(),
        exclusive_entries: summary.exclusive_entries as u32,
        inclusive_envelopes: summary.inclusive_envelopes as u32,
        unsuccessful_entries: summary.unsuccessful_entries as u32,
        unknown_outcome_entries: summary.unknown_outcome_entries as u32,
    })
}

fn total(value: CellCostTotalV2) -> GenerationCostTotalV1 {
    GenerationCostTotalV1 {
        known_sum: value.known_sum,
        unknown_entries: value.unknown_entries,
    }
}
