//! Explicit V8 wire and controller semantics. No V7 bytes or controller labels
//! are rewritten. The V7 public decoder remains fixed to its original mode.
use crate::CellTrainingCheckpointV7;
use crate::TrainedCellBundleV5;
use crate::TrainingHandoffErrorV7;
use crate::training_handoff_v7::ControllerVersion;
use crate::training_handoff_v7::TrainingHandoffBundleV7;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

/// The bounded numeric carrier is shared; the enclosing V8 constructor validates
/// the complete V8 forecast, committed prefix, contract and cumulative counters.
pub type CellTrainingCheckpointV8 = CellTrainingCheckpointV7;
pub type TrainingHandoffErrorV8 = TrainingHandoffErrorV7;

#[derive(Clone, Debug, PartialEq)]
pub struct TrainingHandoffBundleV8(TrainingHandoffBundleV7);
impl TrainingHandoffBundleV8 {
    pub fn new(
        serving: TrainedCellBundleV5,
        protocol: Digest32,
        predecessor: Option<Digest32>,
        checkpoints: Vec<CellTrainingCheckpointV8>,
    ) -> Result<Self, TrainingHandoffErrorV8> {
        Ok(Self(TrainingHandoffBundleV7::new_versioned(
            serving,
            protocol,
            predecessor,
            checkpoints,
            ControllerVersion::V8,
        )?))
    }
    pub fn decode(bytes: &[u8], expected: Digest32) -> Result<Self, TrainingHandoffErrorV8> {
        Ok(Self(TrainingHandoffBundleV7::decode_versioned(
            bytes,
            expected,
            ControllerVersion::V8,
        )?))
    }
    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        self.0.encode()
    }
    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        self.0.artifact_id()
    }
    #[must_use]
    pub fn generation(&self) -> Generation {
        self.0.generation()
    }
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        self.0.content_digest()
    }
    #[must_use]
    pub fn protocol_digest(&self) -> Digest32 {
        self.0.protocol_digest()
    }
    #[must_use]
    pub fn predecessor_digest(&self) -> Option<Digest32> {
        self.0.predecessor_digest()
    }
    #[must_use]
    pub fn serving(&self) -> &TrainedCellBundleV5 {
        self.0.serving()
    }
    #[must_use]
    pub fn checkpoints(&self) -> &[CellTrainingCheckpointV8] {
        self.0.checkpoints()
    }
}

#[must_use]
pub fn training_handoff_compatibility_digest_v8() -> Digest32 {
    Digest32::of_bytes(b"hepta.neuron.training-handoff.v8.serving-v5.full-adam-pcg64.forecast-h8.certified-prefix-stride1248")
}

#[cfg(test)]
#[path = "training_handoff_v8_tests.rs"]
mod tests;
