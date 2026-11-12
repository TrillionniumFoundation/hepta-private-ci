//! Pair the actual configured Source owner with the original launch's selector.
//! A missing or unrelated runtime cannot provide a post-exit capture receipt.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;

use super::AgentdConfig;
use crate::AgentdError;
use crate::DurableCircuitTaskSourceV1;
use crate::circuit_task::OriginalCircuitSourceCloseV1;
use crate::production_launcher::source_capture::OriginalSourceCaptureRequestV1;

pub(crate) type OriginalSourceCaptureCompositionV1 =
    (OriginalSourceCaptureRequestV1, OriginalCircuitSourceCloseV1);

impl AgentdConfig {
    pub(crate) fn with_original_source_close<W>(
        mut self,
        source: Arc<DurableCircuitTaskSourceV1<W>>,
    ) -> Result<Self, AgentdError>
    where
        W: AnchorWitnessStore + Send + 'static,
    {
        if self.original_source_close.is_some() {
            return Err(AgentdError::Invalid(
                "original Source close owner was already installed".into(),
            ));
        }
        self.original_source_close = Some(
            OriginalCircuitSourceCloseV1::retain_original_source_close(source),
        );
        Ok(self)
    }

    pub(crate) fn install_original_source_capture(
        &mut self,
        request: OriginalSourceCaptureRequestV1,
    ) -> Result<(), AgentdError> {
        if self.original_source_capture.is_some()
            || self.original_source_close.is_none()
            || self.circuit_task_bootstrap.is_none()
            || self.circuit_task_invocation.is_none()
            || request.identity != self.identity
        {
            return Err(AgentdError::Invalid(
                "original Source capture requires its exact configured runtime".into(),
            ));
        }
        self.original_source_capture = Some(request);
        Ok(())
    }

    pub(crate) fn take_original_source_capture(
        &mut self,
    ) -> Result<Option<OriginalSourceCaptureCompositionV1>, AgentdError> {
        match (
            self.original_source_capture.take(),
            self.original_source_close.take(),
        ) {
            (Some(request), Some(close)) => Ok(Some((request, close))),
            (None, close) => {
                drop(close);
                Ok(None)
            }
            (Some(_), None) => Err(AgentdError::Invalid(
                "original Source capture lost its actual close owner".into(),
            )),
        }
    }
}
