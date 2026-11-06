//! Ordinary Agentd assembly for an already published task-boundary reset.
//!
//! This consumes the same guarded journal and bounded control port used by the
//! ordinary generation service. It does not expose State readiness, change the
//! service-retirement continuity rule, or choose a physical model.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::NeuronGenerationRuntimeHandleV2;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_current::PublishedNeuronGenerationUpdateV1;
use crate::neuron_generation_update_live::LiveGenerationCurrent;

pub struct AgentdGenerationUpdateRuntimeOptionsV1 {
    pub queue_capacity: usize,
    pub control_endpoint: bool,
}

impl Default for AgentdGenerationUpdateRuntimeOptionsV1 {
    fn default() -> Self {
        Self {
            queue_capacity: 16,
            control_endpoint: false,
        }
    }
}

/// A real Control publication plus its still exclusively held successor.
/// Neither this value nor its DENY_ALL receipt is a new authority issuer.
pub struct ReadyAgentdGenerationUpdateV1<W: AnchorWitnessStore> {
    journal: CellGenerationJournalV2<W>,
    publication: PublishedNeuronGenerationUpdateV1,
}

impl<W: AnchorWitnessStore> ReadyAgentdGenerationUpdateV1<W> {
    pub(crate) fn new(
        journal: CellGenerationJournalV2<W>,
        publication: PublishedNeuronGenerationUpdateV1,
        guard: Arc<LiveGenerationCurrent>,
    ) -> Result<Self, AgentdError> {
        if journal.owner_binding() != Some(publication.target()) {
            return Err(AgentdError::GenerationFenced(
                "published generation differs from its actual owner".into(),
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
}

/// The returned config goes through the ordinary run/run_with_shutdown body,
/// including Fleet admission, AppServer startup, service drain and shutdown.
pub struct AgentdGenerationUpdateRuntimeV1 {
    pub config: AgentdConfig,
    pub handle: NeuronGenerationRuntimeHandleV2,
    pub publication: PublishedNeuronGenerationUpdateV1,
}

impl<W: AnchorWitnessStore + Send + 'static> ReadyAgentdGenerationUpdateV1<W> {
    pub fn into_runtime<P, C>(
        self,
        config: AgentdConfig,
        control: P,
        clock: C,
        options: AgentdGenerationUpdateRuntimeOptionsV1,
    ) -> Result<AgentdGenerationUpdateRuntimeV1, AgentdError>
    where
        P: CellGenerationControlPortV2 + Send + 'static,
        C: FnMut() -> u64 + Send + 'static,
    {
        config.require_neuron_generation_profile()?;
        if self.journal.owner_binding() != Some(self.publication.target()) {
            return Err(AgentdError::GenerationFenced(
                "published generation differs from its guarded journal".into(),
            ));
        }
        // snapshot/channel consult the live Control floor. A deferred bootstrap
        // cannot revive this owner after another admitted generation replaces it.
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
        Ok(AgentdGenerationUpdateRuntimeV1 {
            config: config.with_neuron_generation_bootstrap(bootstrap)?,
            handle,
            publication: self.publication,
        })
    }
}
