//! Bounded, untrusted realization of a typed memory read. This is not an
//! admission, exact tokenization receipt, or proof of current source authority.
//! The consumer must acquire and revalidate through the actual owning daemon.

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::MemoryReadoutV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::validate_memory_cell_value_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Serialize;

use crate::ContextRealizedItemV2;
use crate::ContextRoleV2;

/// Hard byte cap, not a tokenizer estimate. A host must apply its own provider
/// context budget; this realization supplies no exact-token admission claim.
pub const MAX_MEMORY_CELL_EVIDENCE_BYTES_V1: usize = 768;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCellEvidenceV1 {
    realized: ContextRealizedItemV2,
    request_digest: Digest32,
    evidence_digest: Digest32,
    host_binding: Vec<u8>,
}

impl MemoryCellEvidenceV1 {
    pub fn realized(&self) -> &ContextRealizedItemV2 {
        &self.realized
    }
    pub const fn request_digest(&self) -> Digest32 {
        self.request_digest
    }
    pub const fn evidence_digest(&self) -> Digest32 {
        self.evidence_digest
    }
    pub fn host_binding(&self) -> &[u8] {
        &self.host_binding
    }
}

#[derive(Serialize)]
struct EvidenceWire<'a> {
    schema: &'static str,
    request_digest: String,
    scope: &'a str,
    entity: &'a str,
    at: u64,
    since: u64,
    readout: MemoryReadoutV1,
}

#[derive(Serialize)]
struct DisplayWire<'a> {
    schema: &'static str,
    entity: &'a str,
    operation: MemoryOperationV1,
    prediction_kind: MemoryPredictionKindV1,
    value: &'a serde_json::Value,
    generation: codex_hepta_cognitive_types::hnmf::ContractGenerationV1,
    bundle: codex_hepta_cognitive_types::hnmf::ContractDigestV1,
    evidence: String,
}

/// Preserve source versus prediction provenance and all selected model/version
/// bindings. Elapsed time is normalized because it changes on every fresh read;
/// no content, source, operation, version, or dependency is removed.
pub fn realize_memory_cell_evidence_v1(
    request: &MemoryRequestV1,
    readout: &MemoryReadoutV1,
) -> Result<MemoryCellEvidenceV1, String> {
    request.validate().map_err(|error| error.to_string())?;
    readout.validate().map_err(|error| error.to_string())?;
    if readout.query_id != request.query_id || readout.status != MemoryReadStatusV1::Ok {
        return Err("memory evidence requires a successful matching query".to_string());
    }
    let operation = readout
        .operation
        .ok_or("memory evidence operation is missing")?;
    let (cells, hops, prediction, model_count) = match operation {
        MemoryOperationV1::Current | MemoryOperationV1::History => {
            (1, 1, MemoryPredictionKindV1::SourceEvidence, 0)
        }
        MemoryOperationV1::Change => (1, 2, MemoryPredictionKindV1::SourceEvidence, 0),
        MemoryOperationV1::Semantic | MemoryOperationV1::Procedure => {
            (1, 1, MemoryPredictionKindV1::ModelPrediction, 1)
        }
        MemoryOperationV1::Apply => (3, 3, MemoryPredictionKindV1::Mixed, 2),
    };
    if request.max_cells < cells
        || request.max_hops < hops
        || readout.hops != hops
        || readout.prediction_kind != prediction
        || readout.cell_digests.len() != model_count
    {
        return Err("memory evidence operation, provenance or budget mismatch".to_string());
    }
    let source_count_valid = match operation {
        MemoryOperationV1::Change => (1..=2).contains(&readout.source_ids.len()),
        MemoryOperationV1::Apply => readout.source_ids.len() == 3,
        _ => readout.source_ids.len() == 1,
    };
    if !source_count_valid {
        return Err("memory evidence has unexpected source dependencies".to_string());
    }
    match operation {
        MemoryOperationV1::Current | MemoryOperationV1::History => {
            validate_memory_cell_value_v1(MemoryCellKindV1::Event, &readout.value)
        }
        MemoryOperationV1::Semantic => {
            validate_memory_cell_value_v1(MemoryCellKindV1::Semantic, &readout.value)
        }
        MemoryOperationV1::Procedure => {
            validate_memory_cell_value_v1(MemoryCellKindV1::Procedure, &readout.value)
        }
        MemoryOperationV1::Change | MemoryOperationV1::Apply => {
            if readout.value.as_i64().is_none() {
                return Err("memory computation evidence is not an integer".to_string());
            }
            Ok(())
        }
    }
    .map_err(|error| error.to_string())?;
    let request_digest =
        Digest32::of_bytes(&serde_json::to_vec(request).map_err(|error| error.to_string())?);
    let mut normalized = readout.clone();
    normalized.elapsed_seconds = 0.0;
    let host_binding = serde_json::to_vec(&EvidenceWire {
        schema: "hepta.context.memory-evidence.v1",
        request_digest: request_digest.to_string(),
        scope: request.scope.as_str(),
        entity: request.entity.as_str(),
        at: request.at,
        since: request.since,
        readout: normalized,
    })
    .map_err(|error| error.to_string())?;
    let evidence_digest = Digest32::of_bytes(&host_binding);
    let content = serde_json::to_vec(&DisplayWire {
        schema: "hepta.memory.evidence.v1",
        entity: request.entity.as_str(),
        operation,
        prediction_kind: readout.prediction_kind,
        value: &readout.value,
        generation: readout.generation,
        bundle: readout.snapshot_digest,
        evidence: evidence_digest.to_string(),
    })
    .map_err(|error| error.to_string())?;
    if content.len() > MAX_MEMORY_CELL_EVIDENCE_BYTES_V1 {
        return Err("memory evidence exceeds the 768-byte attachment limit".to_string());
    }
    let realized = ContextRealizedItemV2 {
        item_id: StableId::new(format!("memory-evidence:{request_digest}"))
            .map_err(|error| error.to_string())?,
        role: ContextRoleV2::UntrustedEvidence,
        content,
    };
    Ok(MemoryCellEvidenceV1 {
        realized,
        request_digest,
        evidence_digest,
        host_binding,
    })
}

#[cfg(test)]
#[path = "memory_cell_tests.rs"]
mod tests;
