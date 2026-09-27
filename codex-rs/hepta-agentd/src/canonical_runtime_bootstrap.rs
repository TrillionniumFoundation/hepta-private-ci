//! All-or-none canonical product composition for Agentd.
//!
//! A product host cannot install a runner, owner provider, Neuron frontier,
//! runtime.codex process owner, or final-use authority independently through
//! this surface. The raw compatibility setters remain available for legacy and
//! qualification callers, but this typed profile is the only source-level
//! product composition claim.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseTick;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_types::Digest32;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::AgentdIntelligenceProductRunnerV1;
use crate::AgentdNeuronOwner;
use crate::PreparedAgentdIntelligenceRunV1;
use crate::ProcessRuntimeCodexExecutorV1;
use crate::RunReceipt;
use crate::RuntimeCodexExecutionInputV1;
use crate::runtime_codex_executor::RuntimeCodexInputProviderV1;

/// Non-serializable proof that one exact sparse invocation was checked against
/// the current durable Neuron owner frontier. Its fields are private and there
/// is no public constructor; request bytes and external trait implementations
/// cannot manufacture a successful seal.
pub struct AgentdNeuronInvocationSealV1 {
    owner_binding_digest: Digest32,
    invocation_digest: Digest32,
}

impl std::fmt::Debug for AgentdNeuronInvocationSealV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("AgentdNeuronInvocationSealV1")
            .field("owner_binding_digest", &self.owner_binding_digest)
            .field("invocation_digest", &self.invocation_digest)
            .finish_non_exhaustive()
    }
}

impl AgentdNeuronInvocationSealV1 {
    pub fn owner_binding_digest(&self) -> Digest32 {
        self.owner_binding_digest
    }

    pub fn invocation_digest(&self) -> Digest32 {
        self.invocation_digest
    }
}

/// Current durable Neuron owner required by the canonical Agentd profile.
/// Implementations outside this crate cannot create a successful seal because
/// `AgentdNeuronInvocationSealV1` has no public constructor.
pub trait AgentdCanonicalNeuronOwnerV1: Send + Sync {
    fn binding_digest(&self) -> Digest32;

    fn validate_agentd_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError>;

    fn seal(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        config: &SparseConfig,
        tick: &SparseTick,
        previous: Option<&SparseCheckpoint>,
    ) -> Result<AgentdNeuronInvocationSealV1, AgentdError>;
}

/// Named single owner for one recovered `NeuronRuntime` plus its exact
/// inference.control port. The owner is mutex-protected because its durable
/// runtime and model port are intentionally not cloneable.
pub struct BoundAgentdNeuronOwnerV1<W, P>
where
    W: AnchorWitnessStore + Send,
    P: NeuronInferenceControlPort + Send,
{
    agent_id: AgentId,
    agentd_generation: u64,
    binding_digest: Digest32,
    owner: Mutex<AgentdNeuronOwner<W, P>>,
}

impl<W, P> BoundAgentdNeuronOwnerV1<W, P>
where
    W: AnchorWitnessStore + Send,
    P: NeuronInferenceControlPort + Send,
{
    pub fn new(
        agent_id: AgentId,
        agentd_generation: u64,
        owner: AgentdNeuronOwner<W, P>,
    ) -> Result<Self, AgentdError> {
        if agentd_generation == 0 {
            return Err(AgentdError::Invalid(
                "bound Neuron owner requires a non-zero Agentd generation".to_string(),
            ));
        }
        let runtime_digest = owner.runtime().configuration_digest().map_err(|error| {
            AgentdError::Protocol(format!("Neuron runtime configuration is unavailable: {error}"))
        })?;
        let binding_digest = Digest32::of_parts(&[
            b"hepta.runtime-agentd.bound-neuron-owner.v1\0",
            agent_id.as_str().as_bytes(),
            &agentd_generation.to_be_bytes(),
            runtime_digest.as_array(),
        ]);
        Ok(Self {
            agent_id,
            agentd_generation,
            binding_digest,
            owner: Mutex::new(owner),
        })
    }

    pub fn owner(&self) -> &Mutex<AgentdNeuronOwner<W, P>> {
        &self.owner
    }
}

impl<W, P> AgentdCanonicalNeuronOwnerV1 for BoundAgentdNeuronOwnerV1<W, P>
where
    W: AnchorWitnessStore + Send,
    P: NeuronInferenceControlPort + Send,
{
    fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    fn validate_agentd_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if identity.agent_id != self.agent_id
            || identity.spawn_generation != self.agentd_generation
        {
            return Err(AgentdError::GenerationFenced(
                "canonical Neuron owner does not match the Agentd identity/generation"
                    .to_string(),
            ));
        }
        Ok(())
    }

    fn seal(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        config: &SparseConfig,
        tick: &SparseTick,
        previous: Option<&SparseCheckpoint>,
    ) -> Result<AgentdNeuronInvocationSealV1, AgentdError> {
        self.validate_agentd_identity(identity)?;
        if record.snapshot.generation != identity.spawn_generation
            || tick.objective_digest != record.snapshot.objective_digest
            || tick.body_digest != record.runtime_body_digest
        {
            return Err(AgentdError::GenerationFenced(
                "canonical Neuron invocation does not match the durable RunStart".to_string(),
            ));
        }
        let config_digest = config.digest().map_err(|error| {
            AgentdError::Invalid(format!("canonical Neuron config is invalid: {error}"))
        })?;
        let owner = self.owner.lock().map_err(|_| {
            AgentdError::Protocol("canonical Neuron owner mutex is poisoned".to_string())
        })?;
        let runtime_config = owner.runtime().configuration();
        if runtime_config.native_config_digest != config_digest
            || runtime_config.generation != config.generation
        {
            return Err(AgentdError::GenerationFenced(
                "canonical sparse invocation is not the selected durable Neuron runtime"
                    .to_string(),
            ));
        }
        let current = owner.runtime().current_anchor().map_err(|error| {
            AgentdError::Protocol(format!("canonical Neuron frontier is unavailable: {error}"))
        })?;
        match (current, previous) {
            (None, None) => {}
            (Some(anchor), Some(checkpoint)) if anchor.checkpoint_digest == checkpoint.digest() => {}
            _ => {
                return Err(AgentdError::GenerationFenced(
                    "canonical sparse invocation does not start from the current Neuron frontier"
                        .to_string(),
                ));
            }
        }
        let (next, receipt) = sparse_tick(config, tick, previous).map_err(|error| {
            AgentdError::Invalid(format!("canonical Neuron invocation was rejected: {error}"))
        })?;
        if receipt.authority.grants_any() || next.digest() != receipt.checkpoint_after {
            return Err(AgentdError::Protocol(
                "canonical Neuron invocation returned an invalid authority/checkpoint receipt"
                    .to_string(),
            ));
        }
        let previous_digest = previous.map_or(Digest32::ZERO, SparseCheckpoint::digest);
        let invocation_digest = Digest32::of_parts(&[
            b"hepta.runtime-agentd.neuron-invocation-seal.v1\0",
            self.binding_digest.as_array(),
            record.snapshot.run_id.as_str().as_bytes(),
            record.snapshot.objective_digest.as_array(),
            record.runtime_body_digest.as_array(),
            config_digest.as_array(),
            previous_digest.as_array(),
            receipt.input_digest.as_array(),
            receipt.checkpoint_before.as_array(),
            receipt.checkpoint_after.as_array(),
        ]);
        Ok(AgentdNeuronInvocationSealV1 {
            owner_binding_digest: self.binding_digest,
            invocation_digest,
        })
    }
}

struct NeuronSealedInvocationProviderV1 {
    inner: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    neuron: Arc<dyn AgentdCanonicalNeuronOwnerV1>,
}

impl AgentdIntelligenceInvocationProviderV1 for NeuronSealedInvocationProviderV1 {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        let invocation = self.inner.build(identity, record)?;
        let seal = self.neuron.seal(
            identity,
            record,
            &invocation.inputs.neural_config,
            &invocation.inputs.neural_tick,
            invocation.inputs.neural_previous.as_ref(),
        )?;
        if seal.owner_binding_digest() != self.neuron.binding_digest()
            || seal.invocation_digest().is_zero()
        {
            return Err(AgentdError::Protocol(
                "canonical Neuron owner returned a mismatched invocation seal".to_string(),
            ));
        }
        Ok(invocation)
    }
}

/// Complete canonical product profile. Construction is inert; `install`
/// performs one all-or-none attachment and consumes the value.
pub struct AgentdCanonicalRuntimeBootstrapV1 {
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    invocation: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    neuron: Arc<dyn AgentdCanonicalNeuronOwnerV1>,
    executor: Arc<ProcessRuntimeCodexExecutorV1>,
    input_provider: Arc<dyn RuntimeCodexInputProviderV1>,
    final_use_authority_digest: Digest32,
    queue_capacity: usize,
    maximum_concurrent_jobs: usize,
    recovery_interval: Duration,
}

impl AgentdCanonicalRuntimeBootstrapV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new<N, F>(
        runner: Arc<AgentdIntelligenceProductRunnerV1>,
        invocation: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
        neuron: Arc<N>,
        executor: Arc<ProcessRuntimeCodexExecutorV1>,
        input_provider: F,
        final_use_authority_digest: Digest32,
        queue_capacity: usize,
        maximum_concurrent_jobs: usize,
        recovery_interval: Duration,
    ) -> Result<Self, AgentdError>
    where
        N: AgentdCanonicalNeuronOwnerV1 + 'static,
        F: Fn(
                &AgentdIdentity,
                &RunStartRecordV1,
                &PreparedAgentdIntelligenceRunV1,
                &RunReceipt,
            ) -> Result<RuntimeCodexExecutionInputV1, AgentdError>
            + Send
            + Sync
            + 'static,
    {
        if final_use_authority_digest.is_zero()
            || final_use_authority_digest != executor.final_use_authority_digest()
            || neuron.binding_digest().is_zero()
        {
            return Err(AgentdError::Invalid(
                "canonical bootstrap final-use or Neuron owner binding is invalid".to_string(),
            ));
        }
        Ok(Self {
            runner,
            invocation,
            neuron,
            executor,
            input_provider: Arc::new(input_provider),
            final_use_authority_digest,
            queue_capacity,
            maximum_concurrent_jobs,
            recovery_interval,
        })
    }

    pub fn final_use_authority_digest(&self) -> Digest32 {
        self.final_use_authority_digest
    }

    pub fn neuron_owner_binding_digest(&self) -> Digest32 {
        self.neuron.binding_digest()
    }

    /// Consume the complete profile. The runner/provider pair is first applied
    /// to the still-local `AgentdConfig`; only after every config precondition
    /// succeeds is the process-global executor installed. No fallible step
    /// follows that installation.
    pub fn install(self, config: AgentdConfig) -> Result<AgentdConfig, AgentdError> {
        self.neuron.validate_agentd_identity(config.identity())?;
        if self.final_use_authority_digest != self.executor.final_use_authority_digest() {
            return Err(AgentdError::GenerationFenced(
                "canonical bootstrap final-use authority changed before installation".to_string(),
            ));
        }
        let provider: Arc<dyn AgentdIntelligenceInvocationProviderV1> =
            Arc::new(NeuronSealedInvocationProviderV1 {
                inner: self.invocation,
                neuron: self.neuron,
            });
        let configured = config
            .with_intelligence_product_runner(self.runner)?
            .with_intelligence_invocation_provider(provider)?;
        self.executor.install_agentd_supervisor_with_limits(
            self.queue_capacity,
            self.maximum_concurrent_jobs,
            self.recovery_interval,
            self.input_provider,
        )?;
        Ok(configured)
    }
}