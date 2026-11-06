//! Ordinary runtime assembly for the original signed initial publication.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::NeuronGenerationRuntimeHandleV2;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_current::PublishedNeuronGenerationInitialV1;
use crate::neuron_generation_update_bootstrap::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::neuron_generation_update_live::LiveGenerationCurrent;

/// A published initial journal retained with its original authority evidence.
/// This value cannot expose a journal or turn an unsigned Preparing owner live.
pub struct ReadyAgentdGenerationInitialV1<W: AnchorWitnessStore> {
    journal: CellGenerationJournalV2<W>,
    publication: PublishedNeuronGenerationInitialV1,
}

impl<W: AnchorWitnessStore> ReadyAgentdGenerationInitialV1<W> {
    pub(crate) fn new(
        journal: CellGenerationJournalV2<W>,
        publication: PublishedNeuronGenerationInitialV1,
        guard: Arc<LiveGenerationCurrent>,
    ) -> Result<Self, AgentdError> {
        if journal.owner_binding() != Some(publication.target()) {
            return Err(AgentdError::GenerationFenced(
                "initial publication differs from its actual journal".into(),
            ));
        }
        let guard: Arc<dyn CellGenerationCurrentV1> = guard;
        let journal = journal
            .rebind_current(guard)
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        Ok(Self {
            journal,
            publication,
        })
    }

    pub(crate) fn record_backend_preparation(
        &mut self,
        expected: &CellGenerationOwnerBindingV1,
        entry: CellCostEntryV2,
    ) -> Result<(), AgentdError> {
        if self.journal.owner_binding() != Some(expected)
            || self.publication.target() != expected
        {
            return Err(AgentdError::GenerationFenced(
                "prepared backend differs from its initial publication".into(),
            ));
        }
        self.journal
            .record_cost(entry)
            .map_err(|error| AgentdError::Invalid(error.to_string()))
    }
}

/// The unchanged normal Agentd configuration, typed endpoint and initial
/// publication receipt. The receipt itself has DENY_ALL authority posture.
pub struct AgentdGenerationInitialRuntimeV1 {
    pub config: AgentdConfig,
    pub handle: NeuronGenerationRuntimeHandleV2,
    pub publication: PublishedNeuronGenerationInitialV1,
}

impl<W: AnchorWitnessStore + Send + 'static> ReadyAgentdGenerationInitialV1<W> {
    pub fn into_runtime<P, C>(
        self,
        config: AgentdConfig,
        control: P,
        clock: C,
        options: AgentdGenerationUpdateRuntimeOptionsV1,
    ) -> Result<AgentdGenerationInitialRuntimeV1, AgentdError>
    where
        P: CellGenerationControlPortV2 + Send + 'static,
        C: FnMut() -> u64 + Send + 'static,
    {
        config.require_neuron_generation_profile()?;
        if self.journal.owner_binding() != Some(self.publication.target()) {
            return Err(AgentdError::GenerationFenced(
                "initial runtime differs from its published owner".into(),
            ));
        }
        let (handle, bootstrap) = neuron_generation_channel_v2(
            config.identity(),
            self.journal,
            control,
            clock,
            options.queue_capacity,
        )?;
        let bootstrap = if options.control_endpoint {
            bootstrap.with_control_endpoint()?
        } else {
            bootstrap
        };
        Ok(AgentdGenerationInitialRuntimeV1 {
            config: config.with_neuron_generation_bootstrap(bootstrap)?,
            handle,
            publication: self.publication,
        })
    }
}
