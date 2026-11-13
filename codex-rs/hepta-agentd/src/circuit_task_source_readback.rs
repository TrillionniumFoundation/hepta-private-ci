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

#[cfg(target_os = "linux")]
#[path = "circuit_task_source_material.rs"]
pub(crate) mod material;

#[cfg(target_os = "linux")]
#[path = "circuit_task_source_prefreeze.rs"]
pub(crate) mod prefreeze;

enum OriginalReadback<W: AnchorWitnessStore> {
    Local(DurableCircuitTaskSourceV1<W>),
    #[cfg(target_os = "linux")]
    RootMaterial(std::sync::Arc<material::Client>),
    #[cfg(target_os = "linux")]
    RootPrefreeze(std::sync::Arc<prefreeze::Client>),
}

/// Only the original source owner constructs the local view. The sealed
/// Material branch consumes the real pair; the pre-freeze branch requires the
/// fixed supervisor disclosure and the actual Generator/ledger enrollment.
/// Every read reaches that same original locked journal, independent witness
/// and current withdrawal record, locally or through the sealed Material loan.
pub struct CircuitTaskSourceReadbackV1<W: AnchorWitnessStore> {
    original: OriginalReadback<W>,
}

impl<W: AnchorWitnessStore> Clone for CircuitTaskSourceReadbackV1<W> {
    fn clone(&self) -> Self {
        Self {
            original: match &self.original {
                OriginalReadback::Local(original) => OriginalReadback::Local(original.clone()),
                #[cfg(target_os = "linux")]
                OriginalReadback::RootMaterial(original) => OriginalReadback::RootMaterial(std::sync::Arc::clone(original)),
                #[cfg(target_os = "linux")]
                OriginalReadback::RootPrefreeze(original) => OriginalReadback::RootPrefreeze(std::sync::Arc::clone(original)),
            },
        }
    }
}

impl<W: AnchorWitnessStore> DurableCircuitTaskSourceV1<W> {
    /// Give an observer read access without either task-source writer trait.
    pub fn readback(&self) -> CircuitTaskSourceReadbackV1<W> {
        CircuitTaskSourceReadbackV1 {
            original: OriginalReadback::Local(self.clone()),
        }
    }
}

impl<W: AnchorWitnessStore> CircuitTaskSourceReadbackV1<W> {
    /// Check the original configured input without admitting a request or
    /// requiring a completed task. Selection can precede ordinary C execution.
    /// Both physical CURRENT reads retain the original lock and witness.
    pub(crate) fn require_original_input(
        &self,
        identity: &AgentdIdentity,
        input: &super::CircuitTaskSourceInputV1,
    ) -> Result<(), Error> {
        let original = match &self.original {
            OriginalReadback::Local(original) => original,
            #[cfg(target_os = "linux")]
            OriginalReadback::RootMaterial(_) => return Err(Error::InvalidBinding),
            #[cfg(target_os = "linux")]
            OriginalReadback::RootPrefreeze(_) => return Err(Error::InvalidBinding),
        };
        let mut owner = original.0.try_lock().map_err(|_| Error::Unavailable)?;
        owner.require_current()?;
        if identity != &owner.identity
            || owner.sources.get(input.scope.run_id.as_str()) != Some(input)
        {
            return Err(Error::InvalidBinding);
        }
        owner.require_active(input.scope.run_id.as_str())?;
        owner.require_current()
    }

    pub fn read_publication(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<CircuitTaskSourcePublicationV1, Error> {
        match &self.original {
            OriginalReadback::Local(original) => original.read_publication(identity, record),
            #[cfg(target_os = "linux")]
            OriginalReadback::RootMaterial(original) => {
                let observed = original.read(identity, &record.snapshot.run_id)?;
                if observed.original_record() != record { return Err(Error::InvalidBinding); }
                Ok(observed)
            }
            #[cfg(target_os = "linux")]
            OriginalReadback::RootPrefreeze(original) => {
                let observed = prefreeze::Client::read_prefreeze(original, identity, &record.snapshot.run_id)?;
                if observed.original_record() != record { return Err(Error::InvalidBinding); }
                Ok(observed)
            }
        }
    }

    pub fn read_run_publication(
        &self,
        identity: &AgentdIdentity,
        run_id: &StableId,
    ) -> Result<CircuitTaskSourcePublicationV1, Error> {
        match &self.original {
            OriginalReadback::Local(original) => original.read_run_publication(identity, run_id),
            #[cfg(target_os = "linux")]
            OriginalReadback::RootMaterial(original) => original.read(identity, run_id),
            #[cfg(target_os = "linux")]
            OriginalReadback::RootPrefreeze(original) => prefreeze::Client::read_prefreeze(original, identity, run_id),
        }
    }
}
