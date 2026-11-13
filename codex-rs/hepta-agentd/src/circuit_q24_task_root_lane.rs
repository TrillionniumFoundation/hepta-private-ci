//! Only the original Q24 factory runtime can consume this Root lane. The
//! original Cell writer stays in its one-shot bootstrap slot, and the same
//! invocation/readback Arcs accompany it without exposing a writer getter.

use super::*;

impl<SW, CW> CircuitQ24TaskRuntimeV1<SW, CW>
where SW: AnchorWitnessStore + Send + 'static, CW: AnchorWitnessStore + Send + 'static,
{
    pub(crate) fn original_root_handoff_data(&self)
        -> Result<(codex_hepta_types::Digest32, Vec<u8>, Vec<u8>, usize), AgentdError>
    {
        let (registry, capacity) = crate::CircuitTaskRuntimeBootstrapV1::original_root_handoff_registry(&self.bootstrap)
            .map_err(|error| AgentdError::Protocol(format!("original Root registry: {error}")))?;
        let (binding, source) = crate::DurableCircuitTaskSourceV1::original_root_handoff_source(&self.invocation)
            .map_err(|error| AgentdError::Protocol(format!("original Root Source: {error}")))?;
        Ok((binding, registry, source, capacity))
    }

    pub(crate) fn take_original_root_lane(&mut self)
        -> Result<crate::circuit_task::OriginalRootTaskLane<SW>, AgentdError>
    {
        let pump = crate::CircuitTaskRuntimeBootstrapV1::take_original_root_lane(&mut self.bootstrap)
            .map_err(|error| AgentdError::Protocol(format!("original Root Cell lane: {error}")))?;
        Ok(crate::circuit_task::OriginalRootTaskLane::from_original_factory(
            pump, Arc::clone(&self.invocation), Arc::clone(&self.source),
        ))
    }
}
