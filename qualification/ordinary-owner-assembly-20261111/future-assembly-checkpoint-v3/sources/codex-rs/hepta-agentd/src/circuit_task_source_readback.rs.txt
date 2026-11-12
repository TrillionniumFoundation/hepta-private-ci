//! A narrow observer view of the original ordinary-task source. The original
//! writer remains inside its task driver/bootstrap; this handle cannot admit,
//! publish or withdraw a source and never caches a historical publication.

use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::StableId;

use super::CircuitTaskSourcePublicationV1;
use super::DurableCircuitTaskSourceV1;
use super::Error;
use crate::AgentdIdentity;

/// Only the original source owner constructs this view. Every read reaches the
/// same locked journal, independent witness and current withdrawal record.
pub struct CircuitTaskSourceReadbackV1<W: AnchorWitnessStore> {
    original: DurableCircuitTaskSourceV1<W>,
}

impl<W: AnchorWitnessStore> Clone for CircuitTaskSourceReadbackV1<W> {
    fn clone(&self) -> Self {
        Self {
            original: self.original.clone(),
        }
    }
}

impl<W: AnchorWitnessStore> DurableCircuitTaskSourceV1<W> {
    /// Give an observer read access without either task-source writer trait.
    pub fn readback(&self) -> CircuitTaskSourceReadbackV1<W> {
        CircuitTaskSourceReadbackV1 {
            original: self.clone(),
        }
    }
}

impl<W: AnchorWitnessStore> CircuitTaskSourceReadbackV1<W> {
    /// Identity of the held original owner, without opening, reading or
    /// replacing a journal. Data equality cannot substitute for this custody.
    pub(crate) fn require_original_source_custody(
        &self,
        original: &DurableCircuitTaskSourceV1<W>,
    ) -> Result<(), Error> {
        if !std::sync::Arc::ptr_eq(&self.original.0, &original.0) {
            return Err(Error::InvalidBinding);
        }
        Ok(())
    }

    pub fn read_publication(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<CircuitTaskSourcePublicationV1, Error> {
        self.original.read_publication(identity, record)
    }

    pub fn read_run_publication(
        &self,
        identity: &AgentdIdentity,
        run_id: &StableId,
    ) -> Result<CircuitTaskSourcePublicationV1, Error> {
        self.original.read_run_publication(identity, run_id)
    }
}

#[cfg(test)]
#[path = "cell_q24_dataset_source_tests.rs"]
mod dataset_test_access;
