//! Additive inventory requests. The host resolves intent; callers supply no gold operation.

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::MemoryInventoryExecutionStatusV1;
use crate::MemoryInventoryExecutionV1;
use crate::MemoryInventoryKindV1;
use crate::MemoryInventoryOpcodeV1;
use crate::MemoryOperationV1;
use crate::MemoryPredictionKindV1;
use crate::MemoryReadStatusV1;
use crate::MemoryReadoutV1;
use crate::MemoryRequestV1;
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::validate_memory_inventory_value_v1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventoryRequestV1 {
    pub schema: String,
    pub query_id: ContractIdV1,
    pub scope: ContractIdV1,
    pub entity_key: ContractIdV1,
    pub workflow_key: ContractIdV1,
    pub text: String,
    pub at: u64,
    pub since: u64,
    pub max_hops: u8,
    pub max_cells: u8,
    pub max_steps: u8,
}

impl MemoryInventoryRequestV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema != "hepta.memory.inventory-request.v1" || !(1..=4).contains(&self.max_steps) {
            return Err(HnmfContractError::Invalid("inventory request envelope"));
        }
        // Reuse only the established identifier/text/time/budget constraints.
        // The V1 decoder and its old single-key value profile stay unchanged.
        MemoryRequestV1 {
            schema: "hepta.memory.request.v1".to_string(),
            query_id: self.query_id.clone(),
            scope: self.scope.clone(),
            entity: self.entity_key.clone(),
            text: self.text.clone(),
            at: self.at,
            since: self.since,
            max_hops: self.max_hops,
            max_cells: self.max_cells,
        }.validate()
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventoryReadoutV1 {
    pub schema: String,
    pub query_id: ContractIdV1,
    pub operation: Option<MemoryOperationV1>,
    pub status: MemoryReadStatusV1,
    pub value: Value,
    pub source_ids: Vec<ContractDigestV1>,
    pub generation: ContractGenerationV1,
    /// Identity of the selected bundle, which separately binds its full owner cut.
    pub snapshot_digest: ContractDigestV1,
    pub prediction_kind: MemoryPredictionKindV1,
    pub cell_digests: Vec<ContractDigestV1>,
    pub hops: u8,
    pub elapsed_seconds: f64,
    pub reason: Option<String>,
}

impl MemoryInventoryReadoutV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema != "hepta.memory.inventory-readout.v1" {
            return Err(HnmfContractError::Invalid("inventory readout schema"));
        }
        // The common envelope enforces bounded/unique dependencies and excludes
        // all partial values, source claims and model claims from failed reads.
        MemoryReadoutV1 {
            schema: "hepta.memory.readout.v1".to_string(),
            query_id: self.query_id.clone(),
            operation: self.operation,
            status: self.status,
            value: self.value.clone(),
            source_ids: self.source_ids.clone(),
            generation: self.generation,
            snapshot_digest: self.snapshot_digest,
            prediction_kind: self.prediction_kind,
            cell_digests: self.cell_digests.clone(),
            hops: self.hops,
            elapsed_seconds: self.elapsed_seconds,
            reason: self.reason.clone(),
        }.validate()?;
        if self.status != MemoryReadStatusV1::Ok {
            return Ok(());
        }
        match self.operation {
            Some(MemoryOperationV1::Current | MemoryOperationV1::History | MemoryOperationV1::Change) => {
                if self.value.as_i64().is_none() || self.prediction_kind != MemoryPredictionKindV1::SourceEvidence {
                    return Err(HnmfContractError::Invalid("inventory event evidence"));
                }
            }
            Some(MemoryOperationV1::Semantic | MemoryOperationV1::Procedure) => {
                let kind = if self.operation == Some(MemoryOperationV1::Semantic) {
                    MemoryInventoryKindV1::Semantic
                } else {
                    MemoryInventoryKindV1::Procedure
                };
                validate_memory_inventory_value_v1(kind, &self.value)?;
                if self.prediction_kind != MemoryPredictionKindV1::ModelPrediction {
                    return Err(HnmfContractError::Invalid("inventory prediction label"));
                }
            }
            Some(MemoryOperationV1::Apply) => {
                let execution: MemoryInventoryExecutionV1 = serde_json::from_value(self.value.clone())
                    .map_err(|_| HnmfContractError::Invalid("inventory execution shape"))?;
                if self.prediction_kind != MemoryPredictionKindV1::Mixed
                    || execution.status != MemoryInventoryExecutionStatusV1::Completed
                    || execution.trace.is_empty() || execution.trace.len() > 4
                    || execution.trace.last().is_none_or(|step| {
                        step.op != MemoryInventoryOpcodeV1::Stop || Some(step.after) != execution.value
                    })
                    || execution.trace[..execution.trace.len() - 1].iter().any(|step| step.op == MemoryInventoryOpcodeV1::Stop)
                    || execution.trace.windows(2).any(|steps| steps[0].after != steps[1].before)
                    || execution.trace.iter().any(|step| match step.op {
                        MemoryInventoryOpcodeV1::Keep | MemoryInventoryOpcodeV1::Stop => step.after != step.before,
                        MemoryInventoryOpcodeV1::Halve => step.after != step.before.div_euclid(2),
                        MemoryInventoryOpcodeV1::ReserveGap
                        | MemoryInventoryOpcodeV1::Pack
                        | MemoryInventoryOpcodeV1::Cap
                        | MemoryInventoryOpcodeV1::AddReserve => false,
                    })
                {
                    return Err(HnmfContractError::Invalid("inventory completed trace"));
                }
            }
            None => return Err(HnmfContractError::Invalid("inventory operation absent")),
        }
        Ok(())
    }
}

pub fn decode_memory_inventory_request_v1(bytes: &[u8]) -> Result<MemoryInventoryRequestV1, HnmfContractError> {
    if bytes.len() > 131_072 {
        return Err(HnmfContractError::Invalid("inventory request wire bound"));
    }
    let request: MemoryInventoryRequestV1 = serde_json::from_slice(bytes)
        .map_err(|_| HnmfContractError::Invalid("inventory request JSON"))?;
    request.validate()?;
    Ok(request)
}

pub fn decode_memory_inventory_readout_v1(bytes: &[u8]) -> Result<MemoryInventoryReadoutV1, HnmfContractError> {
    if bytes.len() > 131_072 {
        return Err(HnmfContractError::Invalid("inventory readout wire bound"));
    }
    let readout: MemoryInventoryReadoutV1 = serde_json::from_slice(bytes)
        .map_err(|_| HnmfContractError::Invalid("inventory readout JSON"))?;
    readout.validate()?;
    Ok(readout)
}
