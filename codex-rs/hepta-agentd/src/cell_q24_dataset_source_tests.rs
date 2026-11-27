//! Tests hold the original writer only to exercise real source withdrawal.
//! This capability is absent from every product build.
use super::*;

impl<W: AnchorWitnessStore> CircuitTaskSourceReadbackV1<W> {
    pub(crate) fn withdraw_for_dataset_test(&self, run_id: &StableId) -> Result<(), Error> {
        self.original.withdraw_source(run_id)
    }
}
