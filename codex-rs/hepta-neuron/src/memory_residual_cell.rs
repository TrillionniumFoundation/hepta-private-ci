//! Native evaluation of the original residual TensorCell checkpoint operator.
//!
//! This is a numeric model port. Encoder hashes bind the declared input profile;
//! they do not authenticate a caller or confer source, publication or effect authority.

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::AssociativeMemoryError;
use crate::memory_residual_wire::ResidualWire;

pub const MEMORY_RESIDUAL_SCHEMA_V1: &str = "hepta.memory.residual-native.v1";
pub const MEMORY_RESIDUAL_NUMERIC_PROFILE_V1: &str = "hepta.memory.f32-factored-residual.v1";

/// Exact output vocabularies of the existing inventory TensorCell experiment.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryResidualOutputProfileV1 {
    InventorySemantic,
    InventorySkill,
}

impl MemoryResidualOutputProfileV1 {
    pub(super) fn width(self) -> usize {
        match self {
            Self::InventorySemantic => 12,
            Self::InventorySkill => 28,
        }
    }
}

/// Predictions retain inventory fields and all four skill steps; they are not
/// the unrelated legacy factor/label or single-opcode memory value schema.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum MemoryResidualValueV1 {
    Semantic { reserve: u8, pack: u8, limit: u8 },
    Skill { program: [u8; 4] },
}

#[derive(Clone, Debug, PartialEq)]
pub struct MemoryResidualPredictionV1 {
    pub value: MemoryResidualValueV1,
    pub logits: Vec<f32>,
    pub parameter_digest: Digest32,
    pub encoder_digest: Digest32,
}

/// Immutable, bounded float32 parameters. The base encoder and feature cache are
/// supplied separately and are not included in this object's tensor-byte count.
pub struct MemoryResidualCellV1 {
    pub(super) profile: MemoryResidualOutputProfileV1,
    pub(super) dimension: usize,
    pub(super) rank: usize,
    pub(super) a: Vec<f32>,
    pub(super) b: Vec<f32>,
    pub(super) head_weight: Vec<f32>,
    pub(super) head_bias: Vec<f32>,
    pub(super) encoder_digest: Digest32,
    pub(super) parameter_digest: Digest32,
    pub(super) checkpoint_digest: Digest32,
    pub(super) training_digest: Digest32,
    pub(super) sources: Vec<String>,
    pub(super) artifact_digest: Digest32,
    pub(super) serialized_bytes: usize,
}

impl MemoryResidualCellV1 {
    pub fn from_bytes(bytes: &[u8], expected: Digest32) -> Result<Self, AssociativeMemoryError> {
        ResidualWire::decode(bytes, expected)
    }

    pub fn artifact_digest(&self) -> Digest32 {
        self.artifact_digest
    }

    pub fn output_profile(&self) -> MemoryResidualOutputProfileV1 {
        self.profile
    }

    pub fn parameters_digest(&self) -> Digest32 {
        self.parameter_digest
    }

    pub fn encoder_digest(&self) -> Digest32 {
        self.encoder_digest
    }

    pub fn checkpoint_manifest_digest(&self) -> Digest32 {
        self.checkpoint_digest
    }

    pub fn training_history_digest(&self) -> Digest32 {
        self.training_digest
    }

    pub fn lineage_sources(&self) -> &[String] {
        &self.sources
    }

    pub fn serialized_bytes(&self) -> usize {
        self.serialized_bytes
    }

    pub fn parameter_bytes(&self) -> usize {
        (self.a.len() + self.b.len() + self.head_weight.len() + self.head_bias.len()) * 4
    }

    /// Evaluate H(x + B A x) + bias without folding the learned matrices or
    /// replacing the supplied encoder features with hashes or stored answers.
    pub fn predict(
        &self,
        features: &[f32],
        encoder_digest: Digest32,
    ) -> Result<MemoryResidualPredictionV1, AssociativeMemoryError> {
        if encoder_digest != self.encoder_digest {
            return Err(AssociativeMemoryError::BindingMismatch);
        }
        if features.len() != self.dimension || features.iter().any(|value| !value.is_finite()) {
            return Err(AssociativeMemoryError::InvalidInput);
        }
        let mut low_rank = vec![0.0_f32; self.rank];
        for (row, value) in low_rank.iter_mut().enumerate() {
            for (column, feature) in features.iter().enumerate() {
                *value += feature * self.a[row * self.dimension + column];
            }
        }
        let mut residual = features.to_vec();
        for (row, value) in residual.iter_mut().enumerate() {
            let mut delta = 0.0_f32;
            for (column, hidden) in low_rank.iter().enumerate() {
                delta += hidden * self.b[row * self.rank + column];
            }
            *value += delta;
        }
        let mut logits = self.head_bias.clone();
        for (row, value) in logits.iter_mut().enumerate() {
            let mut dot = 0.0_f32;
            for (column, feature) in residual.iter().enumerate() {
                dot += feature * self.head_weight[row * self.dimension + column];
            }
            *value += dot;
        }
        if low_rank.iter().chain(&residual).chain(&logits).any(|value| !value.is_finite()) {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        let value = match self.profile {
            MemoryResidualOutputProfileV1::InventorySemantic => {
                let values: [u8; 3] = std::array::from_fn(|field| {
                    (0..4).fold(0, |bits, bit| {
                        // Retain the original float32 sigmoid >= 0.5 rule,
                        // including rounding of logits very close to zero.
                        let probability = 1.0_f32 / (1.0 + (-logits[field * 4 + bit]).exp());
                        bits | (u8::from(probability >= 0.5) << bit)
                    })
                });
                MemoryResidualValueV1::Semantic {
                    reserve: values[0],
                    pack: values[1],
                    limit: values[2],
                }
            }
            MemoryResidualOutputProfileV1::InventorySkill => {
                let program = std::array::from_fn(|step| {
                    let scores = &logits[step * 7..(step + 1) * 7];
                    let maximum = scores.iter().copied().fold(f32::NEG_INFINITY, f32::max);
                    let mut probabilities: [f32; 7] = std::array::from_fn(|index| (scores[index] - maximum).exp());
                    let normalizer: f32 = probabilities.iter().sum();
                    for probability in &mut probabilities { *probability /= normalizer; }
                    let mut best = 0;
                    for index in 1..probabilities.len() {
                        // Retain softmax rounding before argmax: nearby logits
                        // can become a probability tie, whose first index wins.
                        if probabilities[index] > probabilities[best] {
                            best = index;
                        }
                    }
                    best as u8
                });
                MemoryResidualValueV1::Skill { program }
            }
        };
        Ok(MemoryResidualPredictionV1 {
            value,
            logits,
            parameter_digest: self.parameter_digest,
            encoder_digest: self.encoder_digest,
        })
    }
}

#[cfg(test)]
#[path = "memory_residual_cell_tests.rs"]
mod tests;
