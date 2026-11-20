//! Tests hold the original writer only to exercise real source withdrawal.
//! This capability is absent from every product build.
use super::*;

impl<W: AnchorWitnessStore> CircuitTaskSourceReadbackV1<W> {
    pub(crate) fn withdraw_for_dataset_test(&self, run_id: &StableId) -> Result<(), Error> {
        self.original.withdraw_source(run_id)
    }
}

#[cfg(target_os = "linux")]
impl CircuitTaskSourceReadbackV1<codex_hepta_neuron::FileAnchorWitnessStore> {
    // The same private writer/lock, solely for installing the already-running
    // original Feature owner into a component slot. No product API gains it.
    pub(crate) fn original_successor_owner_for_test(
        &self,
    ) -> std::sync::Arc<DurableCircuitTaskSourceV1<codex_hepta_neuron::FileAnchorWitnessStore>>
    {
        std::sync::Arc::new(self.original.clone())
    }
}
