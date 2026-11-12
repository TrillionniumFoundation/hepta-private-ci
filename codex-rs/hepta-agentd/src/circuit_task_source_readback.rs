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
    /// Check the original configured input without admitting a request or
    /// requiring a completed task. Selection can precede ordinary C execution.
    /// Both physical CURRENT reads retain the original lock and witness.
    pub(crate) fn require_original_input(
        &self,
        identity: &AgentdIdentity,
        input: &super::CircuitTaskSourceInputV1,
    ) -> Result<(), Error> {
        let mut owner = self.original.0.try_lock().map_err(|_| Error::Unavailable)?;
        owner.require_current()?;
        if identity != &owner.identity
            || owner.sources.get(input.scope.run_id.as_str()) != Some(input)
        {
            return Err(Error::InvalidBinding);
        }
        owner.require_active(input.scope.run_id.as_str())?;
        owner.require_current()
    }

    /// Read-only exact protocol check for the separately frozen on-policy
    /// evaluator. The original journal/witness is read on both sides; matching
    /// declarations never replace the actual Source capability or admit work.
    pub(crate) fn require_original_evaluation_protocol(
        &self,
        identity: &AgentdIdentity,
        input: &super::CircuitTaskSourceInputV1,
        definition: &codex_hepta_automation::BoundedCircuitDefinitionV2,
    ) -> Result<(), Error> {
        let mut owner = self.original.0.try_lock().map_err(|_| Error::Unavailable)?;
        owner.require_current()?;
        if identity != &owner.identity
            || owner.sources.get(input.scope.run_id.as_str()) != Some(input)
            || &owner.definition != definition
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
