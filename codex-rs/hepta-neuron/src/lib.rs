//! Deterministic, bounded temporal signal runtime for qualification use.
//!
//! Pure mechanisms emit state and signal receipts. An optional host-authorized
//! journal persists owned checkpoints; it grants no model dispatch, physical
//! effect, selection, promotion or release authority.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

mod journal;
mod journal_lock;
mod sparse;

pub use journal::JournalAnchor;
pub use journal::JournalError;
pub use journal::JournalScope;
pub use journal::SparseJournal;
pub use sparse::InhibitoryEdge;
pub use sparse::SparseCheckpoint;
pub use sparse::SparseConfig;
pub use sparse::SparseError;
pub use sparse::SparseSignalReceipt;
pub use sparse::SparseTick;
pub use sparse::sparse_tick;

const MAX_FEATURES: usize = 4_096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronState {
    pub model_digest: Digest32,
    pub generation: Generation,
    pub values: Vec<FixedQ32>,
    pub state_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StepRequest {
    pub run_id: StableId,
    pub model_digest: Digest32,
    pub source_digest: Digest32,
    pub generation: Generation,
    pub decay: FixedQ32,
    pub features: Vec<FixedQ32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronSignalReceipt {
    pub run_id: StableId,
    pub model_digest: Digest32,
    pub source_digest: Digest32,
    pub state_digest: Digest32,
    pub signal_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyFeatures,
    FeatureLimitExceeded,
    EmptyDigest(&'static str),
    InvalidDecay,
    ModelDrift,
    WidthDrift,
    GenerationNotAdvanced,
    Arithmetic,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn step(
    request: StepRequest,
    previous: Option<&NeuronState>,
) -> Result<(NeuronState, NeuronSignalReceipt), Error> {
    validate_request(&request, previous)?;

    let complement = FixedQ32::ONE
        .checked_sub(request.decay)
        .map_err(|_| Error::Arithmetic)?;
    let mut values = Vec::with_capacity(request.features.len());
    for (index, feature) in request.features.iter().copied().enumerate() {
        let prior = previous.map_or(FixedQ32::ZERO, |state| state.values[index]);
        let retained = prior
            .checked_mul(request.decay)
            .map_err(|_| Error::Arithmetic)?;
        let injected = feature
            .checked_mul(complement)
            .map_err(|_| Error::Arithmetic)?;
        values.push(
            retained
                .checked_add(injected)
                .map_err(|_| Error::Arithmetic)?,
        );
    }

    let previous_digest = previous.map_or(Digest32::ZERO, |state| state.state_digest);
    let state_digest = digest_state(&request, previous_digest, &values);
    let signal_digest = digest_signal(&request, state_digest, &values);
    let state = NeuronState {
        model_digest: request.model_digest,
        generation: request.generation,
        values,
        state_digest,
    };
    let receipt = NeuronSignalReceipt {
        run_id: request.run_id,
        model_digest: request.model_digest,
        source_digest: request.source_digest,
        state_digest,
        signal_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((state, receipt))
}

fn validate_request(request: &StepRequest, previous: Option<&NeuronState>) -> Result<(), Error> {
    if request.features.is_empty() {
        return Err(Error::EmptyFeatures);
    }
    if request.features.len() > MAX_FEATURES {
        return Err(Error::FeatureLimitExceeded);
    }
    if request.model_digest.is_zero() {
        return Err(Error::EmptyDigest("model"));
    }
    if request.source_digest.is_zero() {
        return Err(Error::EmptyDigest("source"));
    }
    if request.decay < FixedQ32::ZERO || request.decay > FixedQ32::ONE {
        return Err(Error::InvalidDecay);
    }
    if let Some(state) = previous {
        if state.model_digest != request.model_digest {
            return Err(Error::ModelDrift);
        }
        if state.values.len() != request.features.len() {
            return Err(Error::WidthDrift);
        }
        if request.generation <= state.generation {
            return Err(Error::GenerationNotAdvanced);
        }
        if state.state_digest.is_zero() {
            return Err(Error::EmptyDigest("previous state"));
        }
    }
    Ok(())
}

fn digest_state(request: &StepRequest, previous_digest: Digest32, values: &[FixedQ32]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.neuron.state.v1");
    push_id(&mut bytes, &request.run_id);
    bytes.extend_from_slice(request.model_digest.as_array());
    bytes.extend_from_slice(request.source_digest.as_array());
    bytes.extend_from_slice(&request.generation.get().to_be_bytes());
    bytes.extend_from_slice(&request.decay.raw().to_be_bytes());
    bytes.extend_from_slice(previous_digest.as_array());
    for value in values {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_signal(request: &StepRequest, state_digest: Digest32, values: &[FixedQ32]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.neuron.signal.v1");
    push_id(&mut bytes, &request.run_id);
    bytes.extend_from_slice(state_digest.as_array());
    for value in values {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
