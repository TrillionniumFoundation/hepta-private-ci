//! One immutable serving and complete research-training checkpoint payload.
//!
//! Decoding proves byte identity and finite-state bindings. It neither grants
//! scientific admission nor executes Adam, the Encoder, or a controller. A host
//! must use the existing current-owner admission boundary before exposing these
//! checkpoints and the pinned research loader before resuming training.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::TrainedCellBundleV5;
use crate::TrainedCellErrorV5;

#[path = "training_handoff_codec_v7.rs"]
mod codec;
#[path = "training_handoff_state_v7.rs"]
mod state;

pub const MAX_TRAINING_HANDOFF_BYTES_V7: usize = 8 * 1024 * 1024;
pub(super) const MAX_CHECKPOINT_METADATA: usize = 64 * 1024;

/// Exact metadata bytes, theta/m/v, and a fully frozen controller plan.
/// `planned_actions` stores the whole resolved plan; the cursor selects its
/// remaining suffix. In-progress nonlinear solver internals are unsupported.
#[derive(Clone, Debug, PartialEq)]
pub struct CellTrainingCheckpointV7 {
    cell_id: StableId,
    state_metadata_json: Vec<u8>,
    state_vector: Vec<f64>,
    controller_metadata_json: Vec<u8>,
    planned_actions: Vec<Vec<f64>>,
    action_cursor: usize,
}

impl CellTrainingCheckpointV7 {
    pub fn new(
        cell_id: StableId,
        state_metadata_json: Vec<u8>,
        state_vector: Vec<f64>,
        controller_metadata_json: Vec<u8>,
        planned_actions: Vec<Vec<f64>>,
    ) -> Result<Self, TrainingHandoffErrorV7> {
        if state_metadata_json.len() > MAX_CHECKPOINT_METADATA
            || controller_metadata_json.len() > MAX_CHECKPOINT_METADATA
            || !matches!(state_vector.len(), 108 | 156)
            || state_vector.iter().any(|value| !value.is_finite())
            || planned_actions.len() > 8
            || planned_actions.iter().any(|row| {
                row.len() != state_vector.len() / 3
                    || row
                        .iter()
                        .any(|value| !value.is_finite() || value.abs() > 64.0)
            })
        {
            return Err(TrainingHandoffErrorV7::Shape);
        }
        let controller: serde_json::Value = serde_json::from_slice(&controller_metadata_json)
            .map_err(|_| TrainingHandoffErrorV7::Controller)?;
        let action_cursor = controller["action_cursor"]
            .as_u64()
            .filter(|value| *value <= planned_actions.len() as u64)
            .ok_or(TrainingHandoffErrorV7::Controller)? as usize;
        Ok(Self {
            cell_id,
            state_metadata_json,
            state_vector,
            controller_metadata_json,
            planned_actions,
            action_cursor,
        })
    }

    #[must_use]
    pub fn cell_id(&self) -> &StableId {
        &self.cell_id
    }
    #[must_use]
    pub fn state_metadata_json(&self) -> &[u8] {
        &self.state_metadata_json
    }
    #[must_use]
    pub fn state_vector(&self) -> &[f64] {
        &self.state_vector
    }
    #[must_use]
    pub fn controller_metadata_json(&self) -> &[u8] {
        &self.controller_metadata_json
    }
    #[must_use]
    pub fn planned_actions(&self) -> &[Vec<f64>] {
        &self.planned_actions
    }
    #[must_use]
    pub fn pending_actions(&self) -> &[Vec<f64>] {
        &self.planned_actions[self.action_cursor..]
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct TrainingHandoffBundleV7 {
    serving: TrainedCellBundleV5,
    protocol_digest: Digest32,
    predecessor_digest: Option<Digest32>,
    checkpoints: Vec<CellTrainingCheckpointV7>,
    content_digest: Digest32,
}

impl TrainingHandoffBundleV7 {
    pub fn new(
        serving: TrainedCellBundleV5,
        protocol_digest: Digest32,
        predecessor_digest: Option<Digest32>,
        checkpoints: Vec<CellTrainingCheckpointV7>,
    ) -> Result<Self, TrainingHandoffErrorV7> {
        if protocol_digest.is_zero()
            || predecessor_digest.is_some_and(codex_hepta_types::Digest32::is_zero)
            || checkpoints.len() != serving.heads().len()
        {
            return Err(TrainingHandoffErrorV7::Binding);
        }
        state::validate(&serving, protocol_digest, &checkpoints)?;
        let mut bundle = Self {
            serving,
            protocol_digest,
            predecessor_digest,
            checkpoints,
            content_digest: Digest32::ZERO,
        };
        let bytes = bundle.encode();
        if bytes.len() > MAX_TRAINING_HANDOFF_BYTES_V7 {
            return Err(TrainingHandoffErrorV7::Shape);
        }
        bundle.content_digest = Digest32::of_bytes(&bytes);
        Ok(bundle)
    }

    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        self.serving.artifact_id()
    }
    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.serving.generation()
    }
    #[must_use]
    pub const fn content_digest(&self) -> Digest32 {
        self.content_digest
    }
    #[must_use]
    pub const fn protocol_digest(&self) -> Digest32 {
        self.protocol_digest
    }
    #[must_use]
    pub const fn predecessor_digest(&self) -> Option<Digest32> {
        self.predecessor_digest
    }
    #[must_use]
    pub fn serving(&self) -> &TrainedCellBundleV5 {
        &self.serving
    }
    #[must_use]
    pub fn checkpoints(&self) -> &[CellTrainingCheckpointV7] {
        &self.checkpoints
    }
}

#[must_use]
pub fn training_handoff_compatibility_digest_v7() -> Digest32 {
    Digest32::of_bytes(
        b"hepta.neuron.training-handoff.v7.serving-v5.full-adam-pcg64.frozen-plan-h8",
    )
}

#[derive(Debug, PartialEq, Eq)]
pub enum TrainingHandoffErrorV7 {
    Binding,
    Controller,
    Digest,
    Encoding,
    Shape,
    State,
    Serving(TrainedCellErrorV5),
}
impl fmt::Display for TrainingHandoffErrorV7 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for TrainingHandoffErrorV7 {}
impl From<TrainedCellErrorV5> for TrainingHandoffErrorV7 {
    fn from(value: TrainedCellErrorV5) -> Self {
        Self::Serving(value)
    }
}

#[cfg(test)]
#[path = "training_handoff_v7_tests.rs"]
mod tests;
