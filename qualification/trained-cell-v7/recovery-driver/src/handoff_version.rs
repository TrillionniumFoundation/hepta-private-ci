//! Explicit wire dispatch. V7 and V8 retain different decoders, identities and
//! compatibility digests; no source-controller labels are rewritten.
use codex_hepta_neuron::CellTrainingCheckpointV7;
use codex_hepta_neuron::TrainedCellBundleV5;
use codex_hepta_neuron::TrainingHandoffBundleV7;
use codex_hepta_neuron::TrainingHandoffBundleV8;
use codex_hepta_neuron::TrainingHandoffErrorV7;
use codex_hepta_neuron::training_handoff_compatibility_digest_v7;
use codex_hepta_neuron::training_handoff_compatibility_digest_v8;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub enum Handoff {
    V7(TrainingHandoffBundleV7),
    V8(TrainingHandoffBundleV8),
}
impl Handoff {
    pub fn recognizes(bytes: &[u8]) -> bool {
        bytes.starts_with(b"HPTHOF07") || bytes.starts_with(b"HPTHOF08")
    }
    pub fn decode(bytes: &[u8], expected: Digest32) -> Result<Self, TrainingHandoffErrorV7> {
        match bytes.get(..8) {
            Some(b"HPTHOF07") => Ok(Self::V7(TrainingHandoffBundleV7::decode(bytes, expected)?)),
            Some(b"HPTHOF08") => Ok(Self::V8(TrainingHandoffBundleV8::decode(bytes, expected)?)),
            _ => Err(TrainingHandoffErrorV7::Encoding),
        }
    }
    pub fn compatibility_digest(&self) -> Digest32 {
        match self {
            Self::V7(_) => training_handoff_compatibility_digest_v7(),
            Self::V8(_) => training_handoff_compatibility_digest_v8(),
        }
    }
    pub fn version(&self) -> u8 {
        match self {
            Self::V7(_) => 7,
            Self::V8(_) => 8,
        }
    }
    pub fn encode(&self) -> Vec<u8> {
        match self {
            Self::V7(v) => v.encode(),
            Self::V8(v) => v.encode(),
        }
    }
    pub fn artifact_id(&self) -> &StableId {
        match self {
            Self::V7(v) => v.artifact_id(),
            Self::V8(v) => v.artifact_id(),
        }
    }
    pub fn generation(&self) -> Generation {
        match self {
            Self::V7(v) => v.generation(),
            Self::V8(v) => v.generation(),
        }
    }
    pub fn content_digest(&self) -> Digest32 {
        match self {
            Self::V7(v) => v.content_digest(),
            Self::V8(v) => v.content_digest(),
        }
    }
    pub fn protocol_digest(&self) -> Digest32 {
        match self {
            Self::V7(v) => v.protocol_digest(),
            Self::V8(v) => v.protocol_digest(),
        }
    }
    pub fn predecessor_digest(&self) -> Option<Digest32> {
        match self {
            Self::V7(v) => v.predecessor_digest(),
            Self::V8(v) => v.predecessor_digest(),
        }
    }
    pub fn serving(&self) -> &TrainedCellBundleV5 {
        match self {
            Self::V7(v) => v.serving(),
            Self::V8(v) => v.serving(),
        }
    }
    pub fn checkpoints(&self) -> &[CellTrainingCheckpointV7] {
        match self {
            Self::V7(v) => v.checkpoints(),
            Self::V8(v) => v.checkpoints(),
        }
    }
}
