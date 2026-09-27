//! Atomic product composition for canonical Agentd execution.
//!
//! The bootstrap is intentionally all-or-nothing. A production caller cannot
//! install the intelligence runner, owner-input provider, Neuron authority or
//! runtime.codex process owner independently and still start Agentd.

use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::time::Duration;

use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::AgentdIntelligenceProductRunnerV1;
use crate::PreparedAgentdIntelligenceRunV1;
use crate::ProcessRuntimeCodexExecutorV1;
use crate::RunReceipt;
use crate::RuntimeCodexExecutionInputV1;

const MAX_CANONICAL_QUEUE_CAPACITY: usize = 256;
const MAX_STARTUP_TIMEOUT: Duration = Duration::from_secs(120);
const MAX_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(60);

/// Host-owned builder for the exact physical runtime.codex input.
///
/// Request bytes never implement this port. The implementation derives prompt,
/// model and optional context query from the current owners and the sealed run.
pub trait RuntimeCodexInputProviderV1: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
        receipt: &RunReceipt,
    ) -> Result<RuntimeCodexExecutionInputV1, AgentdError>;
}

impl<F> RuntimeCodexInputProviderV1 for F
where
    F: Fn(
            &AgentdIdentity,
            &RunStartRecordV1,
            &PreparedAgentdIntelligenceRunV1,
            &RunReceipt,
        ) -> Result<RuntimeCodexExecutionInputV1, AgentdError>
        + Send
        + Sync,
{
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
        receipt: &RunReceipt,
    ) -> Result<RuntimeCodexExecutionInputV1, AgentdError> {
        self(identity, record, prepared, receipt)
    }
}

/// Current durable owner witness for one Neuron invocation source.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdNeuronInvocationWitnessV1 {
    pub agent_id: String,
    pub generation: u64,
    pub owner_revision: u64,
    pub owner_digest: Digest32,
}

impl AgentdNeuronInvocationWitnessV1 {
    pub fn new(
        agent_id: String,
        generation: u64,
        owner_revision: u64,
        owner_digest: Digest32,
    ) -> Result<Self, AgentdError> {
        if agent_id.is_empty()
            || generation == 0
            || owner_revision == 0
            || owner_digest.is_zero()
        {
            return Err(AgentdError::Invalid(
                "invalid durable Neuron invocation witness".to_string(),
            ));
        }
        Ok(Self {
            agent_id,
            generation,
            owner_revision,
            owner_digest,
        })
    }

    fn require_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if self.agent_id != identity.agent_id.as_str()
            || self.generation != identity.spawn_generation
        {
            return Err(AgentdError::GenerationFenced(
                "durable Neuron owner does not match the Agentd identity".to_string(),
            ));
        }
        Ok(())
    }
}

/// Opaque product owner for canonical Neuron inputs.
///
/// The legacy seven-owner provider may internally materialize sparse values,
/// but a production bootstrap cannot use them until this durable owner verifies
/// the exact invocation against its current selected artifact and witness state.
pub trait AgentdDurableNeuronInvocationOwnerV1: Send + Sync {
    fn current_witness(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<AgentdNeuronInvocationWitnessV1, AgentdError>;

    fn verify_invocation(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        invocation: &AgentdIntelligenceInvocationV1,
    ) -> Result<Digest32, AgentdError>;
}

struct NeuronVerifiedInvocationProviderV1 {
    inner: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    neuron_owner: Arc<dyn AgentdDurableNeuronInvocationOwnerV1>,
}

impl AgentdIntelligenceInvocationProviderV1 for NeuronVerifiedInvocationProviderV1 {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        let before = self.neuron_owner.current_witness(identity)?;
        before.require_identity(identity)?;
        let invocation = self.inner.build(identity, record)?;
        let invocation_digest = self
            .neuron_owner
            .verify_invocation(identity, record, &invocation)?;
        if invocation_digest.is_zero() {
            return Err(AgentdError::Invalid(
                "durable Neuron owner returned a zero invocation digest".to_string(),
            ));
        }
        let after = self.neuron_owner.current_witness(identity)?;
        after.require_identity(identity)?;
        if before != after {
            return Err(AgentdError::GenerationFenced(
                "durable Neuron owner changed while canonical inputs were prepared".to_string(),
            ));
        }
        Ok(invocation)
    }
}

/// The only supported production composition for canonical intelligence.
pub struct AgentdCanonicalRuntimeBootstrapV1 {
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    invocation_provider: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    neuron_owner: Arc<dyn AgentdDurableNeuronInvocationOwnerV1>,
    executor: Arc<ProcessRuntimeCodexExecutorV1>,
    input_provider: Arc<dyn RuntimeCodexInputProviderV1>,
    queue_capacity: usize,
    startup_timeout: Duration,
    shutdown_timeout: Duration,
}

impl fmt::Debug for AgentdCanonicalRuntimeBootstrapV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentdCanonicalRuntimeBootstrapV1")
            .field("worker_artifact_digest", &self.executor.worker_artifact_digest())
            .field(
                "final_use_authority_digest",
                &self.executor.final_use_authority_digest(),
            )
            .field("queue_capacity", &self.queue_capacity)
            .field("startup_timeout", &self.startup_timeout)
            .field("shutdown_timeout", &self.shutdown_timeout)
            .finish_non_exhaustive()
    }
}

impl AgentdCanonicalRuntimeBootstrapV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        runner: Arc<AgentdIntelligenceProductRunnerV1>,
        invocation_provider: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
        neuron_owner: Arc<dyn AgentdDurableNeuronInvocationOwnerV1>,
        executor: Arc<ProcessRuntimeCodexExecutorV1>,
        input_provider: Arc<dyn RuntimeCodexInputProviderV1>,
        queue_capacity: usize,
        startup_timeout: Duration,
        shutdown_timeout: Duration,
    ) -> Result<Self, AgentdError> {
        if !(1..=MAX_CANONICAL_QUEUE_CAPACITY).contains(&queue_capacity)
            || startup_timeout.is_zero()
            || startup_timeout > MAX_STARTUP_TIMEOUT
            || shutdown_timeout.is_zero()
            || shutdown_timeout > MAX_SHUTDOWN_TIMEOUT
            || executor.worker_artifact_digest().is_zero()
            || executor.final_use_authority_digest().is_zero()
        {
            return Err(AgentdError::Invalid(
                "invalid canonical runtime bootstrap limits or pinned identities".to_string(),
            ));
        }
        let verified_provider: Arc<dyn AgentdIntelligenceInvocationProviderV1> =
            Arc::new(NeuronVerifiedInvocationProviderV1 {
                inner: invocation_provider,
                neuron_owner: Arc::clone(&neuron_owner),
            });
        Ok(Self {
            runner,
            invocation_provider: verified_provider,
            neuron_owner,
            executor,
            input_provider,
            queue_capacity,
            startup_timeout,
            shutdown_timeout,
        })
    }

    fn validate_for(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        let witness = self.neuron_owner.current_witness(identity)?;
        witness.require_identity(identity)
    }

    pub(crate) fn install_executor(
        self,
        identity: &AgentdIdentity,
    ) -> Result<InstalledCanonicalRuntimeV1, AgentdError> {
        self.validate_for(identity)?;
        let input_provider = Arc::clone(&self.input_provider);
        Arc::clone(&self.executor).install_agentd_supervisor(
            self.queue_capacity,
            move |identity, record, prepared, receipt| {
                input_provider.build(identity, record, prepared, receipt)
            },
        )?;
        Ok(InstalledCanonicalRuntimeV1 {
            runner: self.runner,
            invocation_provider: self.invocation_provider,
            startup_timeout: self.startup_timeout,
            shutdown_timeout: self.shutdown_timeout,
        })
    }
}

pub(crate) struct InstalledCanonicalRuntimeV1 {
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    invocation_provider: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    pub(crate) startup_timeout: Duration,
    pub(crate) shutdown_timeout: Duration,
}

impl InstalledCanonicalRuntimeV1 {
    pub(crate) fn attach(self, config: AgentdConfig) -> Result<AgentdConfig, AgentdError> {
        config
            .with_intelligence_product_runner(self.runner)?
            .with_intelligence_invocation_provider(self.invocation_provider)
    }
}

fn pending_bootstrap_slot() -> &'static Mutex<Option<AgentdCanonicalRuntimeBootstrapV1>> {
    static SLOT: OnceLock<Mutex<Option<AgentdCanonicalRuntimeBootstrapV1>>> = OnceLock::new();
    SLOT.get_or_init(|| Mutex::new(None))
}

pub(crate) fn take_pending_canonical_runtime_bootstrap(
) -> Result<Option<AgentdCanonicalRuntimeBootstrapV1>, AgentdError> {
    pending_bootstrap_slot()
        .lock()
        .map_err(|_| AgentdError::Protocol("canonical bootstrap slot is poisoned".to_string()))
        .map(|mut slot| slot.take())
}

impl AgentdConfig {
    /// Attach the complete canonical product composition atomically.
    ///
    /// The bootstrap is consumed by `run`; installing only a runner/provider is
    /// rejected there, so no partial canonical profile can open daemon services.
    pub fn with_canonical_runtime_bootstrap(
        self,
        bootstrap: AgentdCanonicalRuntimeBootstrapV1,
    ) -> Result<Self, AgentdError> {
        bootstrap.validate_for(self.identity())?;
        let mut slot = pending_bootstrap_slot()
            .lock()
            .map_err(|_| AgentdError::Protocol("canonical bootstrap slot is poisoned".to_string()))?;
        if slot.is_some() {
            return Err(AgentdError::Invalid(
                "a canonical runtime bootstrap is already pending in this process".to_string(),
            ));
        }
        *slot = Some(bootstrap);
        Ok(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn neuron_witness_rejects_zero_identity_fields() {
        assert!(
            AgentdNeuronInvocationWitnessV1::new(
                "agent".to_string(),
                1,
                1,
                Digest32::from_array([0_u8; 32]),
            )
            .is_err()
        );
    }
}
