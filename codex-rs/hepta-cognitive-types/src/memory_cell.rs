//! Versioned cell requests and readouts. Predictions do not become source facts.

use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::validate_text;

const MAX_WIRE_BYTES: usize = 131_072;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryOperationV1 {
    Current,
    History,
    Semantic,
    Procedure,
    Change,
    Apply,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryReadStatusV1 {
    Ok,
    Abstain,
    Stale,
    Unavailable,
    BudgetExceeded,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryPredictionKindV1 {
    SourceEvidence,
    ModelPrediction,
    Mixed,
    None,
}

/// Query intent is produced separately by a bound router, not supplied as gold.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryRequestV1 {
    pub schema: String,
    pub query_id: ContractIdV1,
    pub scope: ContractIdV1,
    pub entity: ContractIdV1,
    pub text: String,
    pub at: u64,
    pub since: u64,
    pub max_hops: u8,
    pub max_cells: u8,
}

impl MemoryRequestV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema != "hepta.memory.request.v1" {
            return Err(HnmfContractError::Invalid("memory request schema"));
        }
        validate_text(&self.text, 8192, "query text")?;
        if self.since > self.at
            || self.at >= 1_u64 << 53
            || !(1..=8).contains(&self.max_hops)
            || !(1..=8).contains(&self.max_cells)
        {
            return Err(HnmfContractError::Invalid("time or execution budget"));
        }
        Ok(())
    }
}

/// Source IDs are dependencies. A model value remains a prediction even when
/// those source IDs have been independently revalidated by the cognitive owner.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryReadoutV1 {
    pub schema: String,
    pub query_id: ContractIdV1,
    pub operation: Option<MemoryOperationV1>,
    pub status: MemoryReadStatusV1,
    pub value: Value,
    pub source_ids: Vec<ContractDigestV1>,
    pub generation: ContractGenerationV1,
    pub snapshot_digest: ContractDigestV1,
    pub prediction_kind: MemoryPredictionKindV1,
    pub cell_digests: Vec<ContractDigestV1>,
    pub hops: u8,
    pub elapsed_seconds: f64,
    pub reason: Option<String>,
}

impl MemoryReadoutV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema != "hepta.memory.readout.v1"
            || self.hops > 8
            || !self.elapsed_seconds.is_finite()
            || self.elapsed_seconds < 0.0
            || self.generation.get() >= 1_u64 << 53
        {
            return Err(HnmfContractError::Invalid("memory readout envelope"));
        }
        if self.source_ids.len() > 64
            || self.source_ids.iter().collect::<BTreeSet<_>>().len() != self.source_ids.len()
            || self.cell_digests.len() > 8
            || self.cell_digests.iter().collect::<BTreeSet<_>>().len() != self.cell_digests.len()
        {
            return Err(HnmfContractError::Invalid("memory support inventory"));
        }
        let bytes = serde_json::to_vec(&self.value)
            .map_err(|_| HnmfContractError::Invalid("memory value"))?;
        if bytes.len() > 16_384 {
            return Err(HnmfContractError::Invalid("memory value bound"));
        }
        match self.status {
            MemoryReadStatusV1::Ok => {
                if self.operation.is_none()
                    || self.value.is_null()
                    || self.source_ids.is_empty()
                    || self.hops == 0
                    || self.reason.is_some()
                    || self.prediction_kind == MemoryPredictionKindV1::None
                {
                    return Err(HnmfContractError::Invalid("incomplete successful readout"));
                }
                let requires_model = matches!(
                    self.prediction_kind,
                    MemoryPredictionKindV1::ModelPrediction | MemoryPredictionKindV1::Mixed
                );
                if requires_model == self.cell_digests.is_empty() {
                    return Err(HnmfContractError::Invalid("prediction artifact binding"));
                }
            }
            MemoryReadStatusV1::Abstain
            | MemoryReadStatusV1::Stale
            | MemoryReadStatusV1::Unavailable
            | MemoryReadStatusV1::BudgetExceeded => {
                if !self.value.is_null()
                    || !self.source_ids.is_empty()
                    || !self.cell_digests.is_empty()
                    || self.prediction_kind != MemoryPredictionKindV1::None
                {
                    return Err(HnmfContractError::Invalid("partial failed readout"));
                }
                validate_text(
                    self.reason.as_deref().ok_or(HnmfContractError::Missing("failure reason"))?,
                    1024,
                    "failure reason",
                )?;
            }
        }
        Ok(())
    }
}

pub fn decode_memory_request_v1(bytes: &[u8]) -> Result<MemoryRequestV1, HnmfContractError> {
    if bytes.len() > MAX_WIRE_BYTES {
        return Err(HnmfContractError::Invalid("request wire bound"));
    }
    let request: MemoryRequestV1 = serde_json::from_slice(bytes)
        .map_err(|_| HnmfContractError::Invalid("memory request JSON"))?;
    request.validate()?;
    Ok(request)
}

pub fn decode_memory_readout_v1(bytes: &[u8]) -> Result<MemoryReadoutV1, HnmfContractError> {
    if bytes.len() > MAX_WIRE_BYTES {
        return Err(HnmfContractError::Invalid("readout wire bound"));
    }
    let readout: MemoryReadoutV1 = serde_json::from_slice(bytes)
        .map_err(|_| HnmfContractError::Invalid("memory readout JSON"))?;
    readout.validate()?;
    Ok(readout)
}

#[cfg(test)]
#[path = "memory_cell_tests.rs"]
mod tests;
