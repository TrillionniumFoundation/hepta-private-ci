//! Adapter for the existing Cell -> inference.control path. The full raw
//! observation remains in CellStepInputV1 and its existing operation digest;
//! the host retains that evidence for exact downstream lookup.

use crate::CellEncodedInputV1;
use crate::CellEncodingRequestV1;
use crate::CellExecutionError;
use crate::CellInputEncoderV1;
use crate::perception::PerceptionEncoderBindingV1;
use crate::perception::PerceptionObservationV1;
use crate::perception_source::PerceptionActorSourceV1;
use crate::perception_source::PerceptionErrorV1;

/// Consumes pinned, externally computed latents without pooling or truncation.
/// It neither trains an encoder nor dispatches an observation or model call.
pub struct PerceptionCellEncoderV1<'a> {
    binding: PerceptionEncoderBindingV1,
    actor_sources: &'a [PerceptionActorSourceV1<'a>],
}

impl<'a> PerceptionCellEncoderV1<'a> {
    pub fn new(
        binding: PerceptionEncoderBindingV1,
        actor_sources: &'a [PerceptionActorSourceV1<'a>],
    ) -> Result<Self, PerceptionErrorV1> {
        binding.validate()?;
        Ok(Self {
            binding,
            actor_sources,
        })
    }
}

impl CellInputEncoderV1 for PerceptionCellEncoderV1<'_> {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        let observation =
            PerceptionObservationV1::decode(request.observation).map_err(cell_error)?;
        if observation.scope_digest != request.scope.digest().into_array() {
            return Err(CellExecutionError::ScopeMismatch);
        }
        if observation.source_frontier != request.source_frontier.into_array() {
            return Err(CellExecutionError::StaleSource);
        }
        if request.encoder_digest != self.binding.encoder_digest {
            return Err(CellExecutionError::EncodingMismatch);
        }
        observation
            .validate(&self.binding, self.actor_sources)
            .map_err(cell_error)?;
        Ok(CellEncodedInputV1 {
            encoder_digest: self.binding.encoder_digest,
            feature_vector_q24: observation
                .latents
                .into_iter()
                .flat_map(|latent| latent.values_q24)
                .collect(),
            consumed_bytes: request.observation.len(),
            truncated_bytes: 0,
        })
    }
}

fn cell_error(error: PerceptionErrorV1) -> CellExecutionError {
    match error {
        PerceptionErrorV1::Capacity => CellExecutionError::CapacityExceeded,
        PerceptionErrorV1::BindingMismatch => CellExecutionError::EncodingMismatch,
        PerceptionErrorV1::SourceMismatch => CellExecutionError::StaleSource,
        PerceptionErrorV1::InvalidWire
        | PerceptionErrorV1::InvalidSource
        | PerceptionErrorV1::InvalidCoordinates
        | PerceptionErrorV1::InvalidEvidence
        | PerceptionErrorV1::InvalidLatent => CellExecutionError::InvalidInput,
    }
}

#[cfg(test)]
#[path = "perception_encoder_tests.rs"]
mod tests;
