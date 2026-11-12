//! Release the actual source writer after the original runtime has drained.
//! Both the invocation Arc and the shared journal owner must be exclusive.
//! No pathname reopen, inferred success or externally constructible token is
//! accepted as evidence that the original source files have been closed.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;

use super::DurableCircuitTaskSourceV1;
use super::agent_error;
use crate::AgentdError;
use crate::runtime::source_capture::OriginalRuntimeDrainedV1;

pub(crate) struct OriginalCircuitSourceCloseV1 {
    close: Box<dyn FnOnce() -> Result<(), AgentdError> + Send>,
}

pub(crate) struct OriginalCircuitSourceClosedV1 {
    _private: (),
}

impl OriginalCircuitSourceCloseV1 {
    pub(crate) fn retain_original_source_close<W>(
        source: Arc<DurableCircuitTaskSourceV1<W>>,
    ) -> Self
    where
        W: AnchorWitnessStore + Send + 'static,
    {
        Self {
            close: Box::new(move || {
                let source = Arc::try_unwrap(source).map_err(|_| {
                    AgentdError::Protocol("original source invocation is still retained".into())
                })?;
                let owner = Arc::try_unwrap(source.0).map_err(|_| {
                    AgentdError::Protocol("original source journal is still retained".into())
                })?;
                let owner = owner.into_inner().map_err(|_| {
                    AgentdError::Protocol("original source journal mutex is poisoned".into())
                })?;
                owner.require_current().map_err(agent_error)?;
                drop(owner);
                Ok(())
            }),
        }
    }

    pub(crate) fn close_after_drain(
        self,
        drained: OriginalRuntimeDrainedV1,
    ) -> Result<OriginalCircuitSourceClosedV1, AgentdError> {
        drained.require_released_state()?;
        (self.close)()?;
        Ok(OriginalCircuitSourceClosedV1 { _private: () })
    }
}
