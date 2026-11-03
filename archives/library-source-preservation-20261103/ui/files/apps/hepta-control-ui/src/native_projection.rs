//! Presentation-only bridge for the existing authenticated native gateway view.
//! This deliberately does not manufacture a ui.control session or module health.
use crate::canonical::{assert_sha256, assert_stable_identifier};
use crate::{ControlError, ErrorCode, Result};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NativeObservation {
    pub endpoint_id: String,
    pub session_id: String,
    pub session_generation: u64,
    pub generation: u64,
    pub revision: u64,
    pub digest: String,
    pub modules: Vec<String>,
}

/// Validated labels over native owner observations, without admission authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeReadOnlyProjection {
    pub observation: NativeObservation,
    pub read_only: bool,
    pub mutation_available: bool,
}

pub fn project_native_view(mut observation: NativeObservation) -> Result<NativeReadOnlyProjection> {
    assert_stable_identifier(&observation.endpoint_id)?;
    assert_stable_identifier(&observation.session_id)?;
    assert_sha256(&observation.digest)?;
    if observation.session_generation == 0
        || observation.generation == 0
        || observation.revision == 0
        || observation.modules.len() > 1000
    {
        return Err(ControlError::new(ErrorCode::InvalidInput));
    }
    for module in &observation.modules {
        assert_stable_identifier(module)?;
    }
    observation.modules.sort();
    if observation
        .modules
        .windows(2)
        .any(|pair| pair[0] == pair[1])
    {
        return Err(ControlError::new(ErrorCode::InvalidInput));
    }
    Ok(NativeReadOnlyProjection {
        observation,
        read_only: true,
        mutation_available: false,
    })
}

#[cfg(test)]
#[path = "native_projection_tests.rs"]
mod tests;
