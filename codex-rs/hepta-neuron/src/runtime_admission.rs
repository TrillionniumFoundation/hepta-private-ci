//! Runtime admission and acknowledgement measurement invariants.

use super::*;

impl<W: AnchorWitnessStore> NeuronRuntime<W> {
    // Receipt latency covers the model call through durable witness acknowledgement,
    // including time waiting for a same-input reconciliation retry in this process.
    pub(super) fn finalize_acknowledged_latency(
        &self,
        output: &mut NeuronRuntimeOutputV1,
        started: Instant,
    ) {
        output.tick.resource_receipt.execution_micros =
            u64::try_from(started.elapsed().as_micros())
                .unwrap_or(u64::MAX)
                .max(output.model_runtime.latency_micros);
        if output.tick.resource_receipt.execution_micros
            > self.config.resource_envelope.p99_latency_micros
        {
            output.tick.abstain = true;
            output.signal.abstain = true;
        }
    }

    pub(super) fn require_witness_config(
        config: &NeuronRuntimeConfigV1,
        scope: JournalScope,
        witness: &W,
    ) -> Result<(), NeuronRuntimeError> {
        witness.verify_context(scope, config.generation)?;
        if witness.runtime_config_digest()? != config.semantic_digest()? {
            return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
        }
        Ok(())
    }

    pub(super) fn require_acknowledged_frontier(&self) -> Result<(), NeuronRuntimeError> {
        Self::require_witness_config(&self.config, self.scope, &self.witness)?;
        if self.pending.is_some() {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        if self.witness.current()? != self.journal.current_anchor()? {
            return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
        }
        Ok(())
    }
}
