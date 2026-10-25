//! Bounded native serving for the study's actual linear and sigmoid-gated heads.
//! Float64 classifier outputs are observations, with no calibrated signal or
//! dispatch authority. Optimizer state belongs to the separate training archive.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[path = "trained_cell_codec_v5.rs"]
mod codec;

pub const TRAINED_CELL_ENCODER_WIDTH_V5: usize = 384;
pub const TRAINED_CELL_WIDTH_V5: usize = 8;
pub const TRAINED_CELL_CLASSES_V5: usize = 4;
pub const MAX_TRAINED_CELLS_V5: usize = 64;
pub const MAX_TRAINED_CELL_BYTES_V5: usize = 65_536;

#[derive(Clone, Debug, PartialEq)]
pub enum TrainedCellModeV5 {
    Linear,
    Gated { a: [f64; 8], g: [f64; 8] },
}

#[derive(Clone, Debug, PartialEq)]
pub struct TrainedCellHeadV5 {
    cell_id: StableId,
    training_state_digest: Digest32,
    feature_identity_digest: Digest32,
    weights: [[f64; 4]; 8],
    bias: [f64; 4],
    mode: TrainedCellModeV5,
}

impl TrainedCellHeadV5 {
    pub fn new(
        cell_id: StableId,
        training_state_digest: Digest32,
        feature_identity_digest: Digest32,
        weights: [[f64; 4]; 8],
        bias: [f64; 4],
        mode: TrainedCellModeV5,
    ) -> Result<Self, TrainedCellErrorV5> {
        let gate = match &mode {
            TrainedCellModeV5::Linear => &[][..],
            TrainedCellModeV5::Gated { a, g: _ } => a.as_slice(),
        };
        let offset = match &mode {
            TrainedCellModeV5::Linear => &[][..],
            TrainedCellModeV5::Gated { a: _, g } => g.as_slice(),
        };
        if training_state_digest.is_zero()
            || feature_identity_digest.is_zero()
            || weights
                .iter()
                .flatten()
                .chain(bias.iter())
                .chain(gate)
                .chain(offset)
                .any(|value| !value.is_finite() || value.abs() > 64.0)
        {
            return Err(TrainedCellErrorV5::Parameters);
        }
        Ok(Self {
            cell_id,
            training_state_digest,
            feature_identity_digest,
            weights,
            bias,
            mode,
        })
    }

    #[must_use]
    pub fn cell_id(&self) -> &StableId {
        &self.cell_id
    }
    #[must_use]
    pub const fn training_state_digest(&self) -> Digest32 {
        self.training_state_digest
    }
    #[must_use]
    pub const fn feature_identity_digest(&self) -> Digest32 {
        self.feature_identity_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrainedCellInputBindingV5 {
    pub generation: Generation,
    pub encoder_digest: Digest32,
    pub projection_digest: Digest32,
    pub normalization_digest: Digest32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TrainedCellBundleV5 {
    artifact_id: StableId,
    generation: Generation,
    encoder_digest: Digest32,
    projection: Vec<f64>,
    projection_digest: Digest32,
    heads: Vec<TrainedCellHeadV5>,
    content_digest: Digest32,
}

impl TrainedCellBundleV5 {
    pub fn new(
        artifact_id: StableId,
        generation: Generation,
        encoder_digest: Digest32,
        projection: Vec<f64>,
        heads: Vec<TrainedCellHeadV5>,
    ) -> Result<Self, TrainedCellErrorV5> {
        let identities: BTreeSet<_> = heads.iter().map(|head| &head.cell_id).collect();
        if encoder_digest.is_zero()
            || projection.len() != 384 * 8
            || projection
                .iter()
                .any(|value| !value.is_finite() || value.abs() > 1.0)
            || heads.is_empty()
            || heads.len() > MAX_TRAINED_CELLS_V5
            || identities.len() != heads.len()
        {
            return Err(TrainedCellErrorV5::Shape);
        }
        let mut projected = b"hepta.neuron.float64-projection.v5".to_vec();
        for value in &projection {
            projected.extend_from_slice(&value.to_bits().to_be_bytes());
        }
        let mut result = Self {
            artifact_id,
            generation,
            encoder_digest,
            projection,
            projection_digest: Digest32::of_bytes(&projected),
            heads,
            content_digest: Digest32::ZERO,
        };
        let encoded = result.encode();
        if encoded.len() > MAX_TRAINED_CELL_BYTES_V5 {
            return Err(TrainedCellErrorV5::Shape);
        }
        result.content_digest = Digest32::of_bytes(&encoded);
        Ok(result)
    }

    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        &self.artifact_id
    }
    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }
    #[must_use]
    pub const fn content_digest(&self) -> Digest32 {
        self.content_digest
    }
    #[must_use]
    pub fn heads(&self) -> &[TrainedCellHeadV5] {
        &self.heads
    }
    #[must_use]
    pub fn input_binding(&self) -> TrainedCellInputBindingV5 {
        TrainedCellInputBindingV5 {
            generation: self.generation,
            encoder_digest: self.encoder_digest,
            projection_digest: self.projection_digest,
            normalization_digest: trained_cell_normalization_digest_v5(),
        }
    }

    /// Project one unlabelled frozen Encoder vector and evaluate one private
    /// head. This does not execute or authenticate the Encoder itself; the host
    /// owns that immutable model/feature boundary and supplies its exact binding.
    pub fn evaluate(
        &self,
        binding: &TrainedCellInputBindingV5,
        cell_id: &StableId,
        encoder_features: &[f64],
    ) -> Result<TrainedCellOutputV5, TrainedCellErrorV5> {
        if binding != &self.input_binding() {
            return Err(TrainedCellErrorV5::Binding);
        }
        if encoder_features.len() != 384
            || encoder_features
                .iter()
                .any(|x| !x.is_finite() || x.abs() > 1_000_000.0)
        {
            return Err(TrainedCellErrorV5::Input);
        }
        let head = self
            .heads
            .iter()
            .find(|head| &head.cell_id == cell_id)
            .ok_or(TrainedCellErrorV5::UnknownCell)?;
        let mut features = [0.0; 8];
        for (row, value) in encoder_features.iter().enumerate() {
            for (column, target) in features.iter_mut().enumerate() {
                *target += value * self.projection[row * 8 + column];
            }
        }
        let norm = features
            .iter()
            .map(|x| x * x)
            .sum::<f64>()
            .sqrt()
            .max(1e-12);
        for value in &mut features {
            *value = *value / norm * 8_f64.sqrt();
        }
        if let TrainedCellModeV5::Gated { a, g } = &head.mode {
            for i in 0..8 {
                features[i] *=
                    1.0 / (1.0 + (-(features[i] * a[i] + g[i]).clamp(-40.0, 40.0)).exp());
            }
        }
        let mut logits = [0.0; 4];
        for (row, value) in features.iter().enumerate() {
            for (column, logit) in logits.iter_mut().enumerate() {
                *logit += value * head.weights[row][column];
            }
        }
        for (logit, bias) in logits.iter_mut().zip(head.bias) {
            *logit += bias;
        }
        let maximum = logits.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let mut probabilities = logits.map(|value| (value - maximum).exp());
        let total = probabilities.iter().sum::<f64>();
        for probability in &mut probabilities {
            *probability /= total;
        }
        if logits
            .iter()
            .chain(probabilities.iter())
            .any(|value| !value.is_finite())
        {
            return Err(TrainedCellErrorV5::Arithmetic);
        }
        let mut input = b"hepta.neuron.float64-encoder-input.v5".to_vec();
        for value in encoder_features {
            input.extend_from_slice(&value.to_bits().to_be_bytes());
        }
        Ok(TrainedCellOutputV5 {
            cell_id: cell_id.clone(),
            generation: self.generation,
            parameter_digest: self.content_digest,
            input_digest: Digest32::of_bytes(&input),
            logits,
            probabilities,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[must_use]
pub fn trained_cell_normalization_digest_v5() -> Digest32 {
    Digest32::of_bytes(b"hepta.neuron.float64-l2-times-sqrt-width8.floor1e-12.v5")
}

#[must_use]
pub fn trained_cell_compatibility_digest_v5() -> Digest32 {
    Digest32::of_bytes(b"hepta.neuron.trained-cell-bundle.v5.encoder384.projection8.classes4.linear-or-gated.float64")
}

#[derive(Clone, Debug, PartialEq)]
pub struct TrainedCellOutputV5 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub parameter_digest: Digest32,
    pub input_digest: Digest32,
    pub logits: [f64; 4],
    pub probabilities: [f64; 4],
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TrainedCellErrorV5 {
    Parameters,
    Shape,
    Binding,
    Input,
    UnknownCell,
    Arithmetic,
    Encoding,
    Digest,
}
impl std::fmt::Display for TrainedCellErrorV5 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for TrainedCellErrorV5 {}

#[cfg(test)]
#[path = "trained_cell_v5_tests.rs"]
mod tests;
