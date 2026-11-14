//! Explicit preparation modes for a task-boundary owner replacement.
//! Both retain the exact old cut and require durable drain with no pending
//! work or output. Retirement never changes that old state into a model STOP.

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::StableId;

use super::NeuronGenerationCurrentOwnerV1;
use super::types::NeuronGenerationPredecessorCompletionV1;
use super::types::PreparedNeuronGenerationUpdateV1;
use super::types::UpdateIntent;
use super::types::invalid;
use super::types::scope_digest;
use crate::AgentdError;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

impl NeuronGenerationCurrentOwnerV1 {
    /// Retire a drained task and retain its complete model manifest for the
    /// next task. The independent FinalUse purpose differs from model update.
    pub fn prepare_same_model_task<W: AnchorWitnessStore>(
        &self,
        old: &CellGenerationJournalV2<W>,
        operation_id: String,
        target: CellGenerationOwnerBindingV1,
        selected: &AgentdSelectedGenerationV1,
    ) -> Result<PreparedNeuronGenerationUpdateV1, AgentdError> {
        self.prepare_with_completion(
            old,
            operation_id,
            target,
            selected,
            NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel,
        )
    }

    /// Retire an already drained owner using a distinct signed destination.
    /// The caller must retain its exclusive old journal lock through publish.
    pub fn prepare_drained_retirement<W: AnchorWitnessStore>(
        &self,
        old: &CellGenerationJournalV2<W>,
        operation_id: String,
        target: CellGenerationOwnerBindingV1,
        selected: &AgentdSelectedGenerationV1,
    ) -> Result<PreparedNeuronGenerationUpdateV1, AgentdError> {
        self.prepare_with_completion(
            old,
            operation_id,
            target,
            selected,
            NeuronGenerationPredecessorCompletionV1::OwnerDrained,
        )
    }

    pub(super) fn prepare_with_completion<W: AnchorWitnessStore>(
        &self,
        old: &CellGenerationJournalV2<W>,
        operation_id: String,
        target: CellGenerationOwnerBindingV1,
        selected: &AgentdSelectedGenerationV1,
        completion: NeuronGenerationPredecessorCompletionV1,
    ) -> Result<PreparedNeuronGenerationUpdateV1, AgentdError> {
        StableId::new(&operation_id).map_err(invalid)?;
        let previous = old
            .owner_binding()
            .ok_or_else(|| invalid("unguarded generation update"))?
            .clone();
        let observation = old.observe_generation().map_err(invalid)?;
        if !old.is_drained().map_err(invalid)?
            || (completion.is_model_stopped() && !observation.is_terminal())
        {
            return Err(invalid(match completion {
                NeuronGenerationPredecessorCompletionV1::ModelStopped => {
                    "generation update requires STOP, ACK and drain"
                }
                NeuronGenerationPredecessorCompletionV1::OwnerDrained
                | NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel => {
                    "generation retirement requires exact output ACK and durable drain"
                }
            }));
        }
        target.digest().map_err(invalid)?;
        if scope_digest(previous.scope())? != scope_digest(target.scope())?
            || previous.scope().run_id == target.scope().run_id
            || previous.task_digest() == target.task_digest()
            || match completion {
                NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel => {
                    previous.manifest_digest() != target.manifest_digest()
                }
                NeuronGenerationPredecessorCompletionV1::ModelStopped
                | NeuronGenerationPredecessorCompletionV1::OwnerDrained => {
                    previous.manifest_digest() == target.manifest_digest()
                }
            }
            || previous.generation().checked_add(1) != Some(target.generation())
            || previous.writer_epoch().checked_add(1) != Some(target.writer_epoch())
            || selected.manifest().digest().map_err(invalid)? != target.manifest_digest()
        {
            return Err(invalid("generation replacement binding differs"));
        }
        let intent = UpdateIntent {
            operation_id,
            supersedes: None,
            previous,
            previous_checkpoint: observation.owner_checkpoint().into_array(),
            previous_observation: observation.digest().map_err(invalid)?,
            genesis_checkpoint: target.genesis_checkpoint().into_array(),
            target,
            selection: selected.observation().digest().into_array(),
            completion,
        };
        let mut head = self.store.load()?;
        if head.current != intent.previous {
            return Err(invalid("generation predecessor is not current"));
        }
        match &head.prepared {
            Some(existing) if existing == &intent => {}
            Some(_) => return Err(invalid("another generation update remains pending")),
            None => {
                let expected = head.clone();
                head.prepared = Some(intent.clone());
                self.store.replace(&expected, &head)?;
            }
        }
        if self.store.load()? != head {
            return Err(invalid("generation preparation readback differs"));
        }
        Ok(PreparedNeuronGenerationUpdateV1 {
            binding: intent.binding()?,
            digest: intent.digest()?,
            head: Some(head),
            intent,
        })
    }
}
