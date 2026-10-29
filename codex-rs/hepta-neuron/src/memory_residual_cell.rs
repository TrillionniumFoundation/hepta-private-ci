//! Exact float32 tensor transport with a factored, bounded residual evaluator.
//!
//! This profile has its own inventory output contract. It does not extend V1
//! catalog values or grant owner, source, publication, or execution authority.

use std::collections::BTreeMap;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryInventoryPolicyV1;
use codex_hepta_cognitive_types::MemoryInventoryProgramV1;
use codex_hepta_cognitive_types::MemoryInventoryValueV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::AssociativeMemoryError;
use crate::memory_residual_wire::ResidualData;
use crate::memory_residual_wire::load;

pub const MEMORY_RESIDUAL_SCHEMA_V1: &str = "hepta.memory.residual-native.v1";
pub const MEMORY_RESIDUAL_ADDRESS_PROFILE_V1: &str = "hepta.memory.canonical-minilm-cache.v1";
pub const MEMORY_RESIDUAL_NUMERIC_PROFILE_V1: &str = "hepta.memory.f32-f64-residual.v1";
pub const MEMORY_RESIDUAL_POLICY_PROFILE_V1: &str = "hepta.memory.inventory-policy.bits12.v1";
pub const MEMORY_RESIDUAL_PROGRAM_PROFILE_V1: &str = "hepta.memory.inventory-program.ops4x7.v1";
pub const MAX_MEMORY_RESIDUAL_BYTES: usize = 32 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryResidualAbstentionV1 {
    OutsideWrittenSupport,
    BelowSelectionMargin,
}

/// A parameter prediction, requiring the host's current-source revalidation.
/// Margin is an uncalibrated raw-logit gap, not a probability of correctness.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct MemoryResidualPredictionV1 {
    pub kind: MemoryCellKindV1,
    pub value: Option<MemoryInventoryValueV1>,
    pub logits: Vec<f64>,
    pub minimum_margin: f64,
    pub source_ids: Vec<String>,
    pub artifact_digest: String,
    pub parameter_digest: String,
    pub abstain: Option<MemoryResidualAbstentionV1>,
}

/// Encoded and decoded categories overlap. These counts are neither RSS nor a
/// full cost: the host must also charge its shared encoder and owner/runtime.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct MemoryResidualCostV1 {
    pub serialized_bytes: u64,
    pub parameter_bytes: u64,
    pub head_parameter_bytes: u64,
    pub feature_bytes: u64,
    pub support_metadata_bytes: u64,
    pub lineage_metadata_bytes: u64,
    /// Full JSON feature cache, including hex vectors; overlaps feature_bytes.
    pub feature_metadata_bytes: u64,
}

/// Immutable tensors and a declared canonical feature cache, containing no
/// key-to-answer catalog. Input features come only from the pinned artifact.
pub struct MemoryResidualCellV1 {
    data: ResidualData,
}

impl MemoryResidualCellV1 {
    pub fn from_bytes(bytes: &[u8], expected: Digest32) -> Result<Self, AssociativeMemoryError> {
        Ok(Self { data: load(bytes, expected)? })
    }

    pub fn digest(&self) -> Digest32 { self.data.digest }
    pub fn parameters_digest(&self) -> Digest32 { self.data.parameter_digest }
    pub fn head_digest(&self) -> Digest32 { self.data.head_digest }
    pub fn encoder_digest(&self) -> Digest32 { self.data.encoder_digest }
    pub fn owner_cut_digest(&self) -> Digest32 { self.data.owner_cut_digest }
    pub fn kind(&self) -> MemoryCellKindV1 { self.data.kind }
    pub fn supports(&self) -> &BTreeMap<String, Vec<String>> { &self.data.supports }
    pub fn lineage_sources(&self) -> &[String] { &self.data.lineage }
    pub fn numeric_profile(&self) -> &'static str { MEMORY_RESIDUAL_NUMERIC_PROFILE_V1 }
    pub fn address_profile(&self) -> &'static str { MEMORY_RESIDUAL_ADDRESS_PROFILE_V1 }
    pub fn output_profile(&self) -> &'static str { self.data.output_profile }
    pub fn serialized_bytes(&self) -> usize { self.data.cost.serialized_bytes as usize }
    pub fn cost(&self) -> MemoryResidualCostV1 { self.data.cost }

    /// Preserve A/B/head factors and evaluate left-to-right scalar f64 reductions
    /// over the original float32 values. A and B start at zero; the residual is
    /// added after B's reduction, and the head reduction starts at its bias.
    /// Torch BLAS parity is tolerance-qualified.
    pub fn predict(&self, key: &str) -> Result<MemoryResidualPredictionV1, AssociativeMemoryError> {
        if key.is_empty() || key.len() > 4096 {
            return Err(AssociativeMemoryError::InvalidInput);
        }
        let mut result = MemoryResidualPredictionV1 {
            kind: self.kind(), value: None, logits: Vec::new(), minimum_margin: 0.0,
            source_ids: Vec::new(), artifact_digest: self.digest().to_string(),
            parameter_digest: self.parameters_digest().to_string(),
            abstain: Some(MemoryResidualAbstentionV1::OutsideWrittenSupport),
        };
        let address = Digest32::of_bytes(key.as_bytes()).to_string();
        let Some(sources) = self.data.supports.get(&address) else { return Ok(result); };
        let features = self.data.features.get(&address)
            .ok_or(AssociativeMemoryError::InvalidArtifact)?;
        let dimension = features.len();
        let mut reduced = vec![0.0_f64; self.data.rank];
        for (row, value) in reduced.iter_mut().enumerate() {
            for (column, feature) in features.iter().enumerate() {
                *value += f64::from(self.data.a[row * dimension + column]) * f64::from(*feature);
            }
        }
        let mut adapted = vec![0.0_f64; dimension];
        for (row, value) in adapted.iter_mut().enumerate() {
            for (column, reduced_value) in reduced.iter().enumerate() {
                *value += f64::from(self.data.b[row * self.data.rank + column]) * reduced_value;
            }
            *value = f64::from(features[row]) + *value;
        }
        result.logits = self.data.head_bias.iter().copied().map(f64::from).collect();
        for (row, value) in result.logits.iter_mut().enumerate() {
            for (column, feature) in adapted.iter().enumerate() {
                *value += f64::from(self.data.head_weight[row * dimension + column]) * feature;
            }
        }
        if result.logits.iter().any(|value| !value.is_finite()) {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        let value = match self.kind() {
            MemoryCellKindV1::Semantic => {
                result.minimum_margin = result.logits.iter().map(|value| value.abs())
                    .fold(f64::INFINITY, f64::min);
                let mut values = [0_u8; 3];
                for (group, value) in values.iter_mut().enumerate() {
                    for bit in 0..4 {
                        if result.logits[4 * group + bit] >= 0.0 { *value |= 1 << bit; }
                    }
                }
                MemoryInventoryValueV1::Semantic(MemoryInventoryPolicyV1 {
                    reserve: values[0], pack: values[1], limit: values[2],
                })
            }
            MemoryCellKindV1::Procedure => {
                let mut opcodes = [0_u8; 4];
                result.minimum_margin = f64::INFINITY;
                for (head, opcode) in opcodes.iter_mut().enumerate() {
                    let scores = &result.logits[7 * head..7 * (head + 1)];
                    let mut winner = 0;
                    for index in 1..7 { if scores[index] > scores[winner] { winner = index; } }
                    let runner_up = scores.iter().enumerate().filter(|(i, _)| *i != winner)
                        .map(|(_, value)| *value).fold(f64::NEG_INFINITY, f64::max);
                    result.minimum_margin = result.minimum_margin.min(scores[winner] - runner_up);
                    *opcode = winner as u8;
                }
                MemoryInventoryValueV1::Procedure(MemoryInventoryProgramV1 { opcodes })
            }
            MemoryCellKindV1::Event => return Err(AssociativeMemoryError::InvalidArtifact),
        };
        result.abstain = Some(MemoryResidualAbstentionV1::BelowSelectionMargin);
        if result.minimum_margin >= self.data.minimum_margin {
            result.value = Some(value);
            result.source_ids.clone_from(sources);
            result.abstain = None;
        }
        Ok(result)
    }
}

#[cfg(test)]
#[path = "memory_residual_cell_tests.rs"]
mod tests;
