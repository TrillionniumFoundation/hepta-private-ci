//! Agentd-owned Neuron runtime composition.
//!
//! This is the named product-host ownership boundary for neuron.runtime source
//! composition. It owns the long-lived runtime and the inference.control port
//! together so callers cannot bypass the exact feature-receipt adapter by
//! supplying drive/prediction vectors directly.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationV1;

pub struct AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    runtime: NeuronRuntime<W>,
    inference_control: P,
}

impl<W, P> AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    pub fn new(runtime: NeuronRuntime<W>, inference_control: P) -> Self {
        Self {
            runtime,
            inference_control,
        }
    }

    pub fn tick(
        &mut self,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let mut model = InferenceControlModelPort::new(&mut self.inference_control);
        self.runtime.tick(&mut model, input)
    }

    pub fn runtime(&self) -> &NeuronRuntime<W> {
        &self.runtime
    }

    pub fn runtime_mut(&mut self) -> &mut NeuronRuntime<W> {
        &mut self.runtime
    }

    pub fn inference_control_mut(&mut self) -> &mut P {
        &mut self.inference_control
    }
}

/// Read-only witness published by the concrete Agentd-owned Neuron runtime.
///
/// Fields are deliberately private and there is no public constructor. Product
/// callers can inspect a witness returned by Agentd, but cannot manufacture one
/// or implement an alternate owner that simply asserts verification success.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdNeuronInvocationWitnessV1 {
    agent_id: String,
    generation: u64,
    owner_revision: u64,
    owner_digest: Digest32,
}

impl AgentdNeuronInvocationWitnessV1 {
    pub fn agent_id(&self) -> &str {
        &self.agent_id
    }

    pub const fn generation(&self) -> u64 {
        self.generation
    }

    pub const fn owner_revision(&self) -> u64 {
        self.owner_revision
    }

    pub const fn owner_digest(&self) -> Digest32 {
        self.owner_digest
    }
}

/// Opaque handle for the one durable Neuron owner selected by the Agentd host.
///
/// The inner trait is crate-private. Construction therefore requires the real
/// `AgentdNeuronOwner`; a downstream crate cannot implement a permissive fake
/// owner while still satisfying the production bootstrap type.
#[derive(Clone)]
pub struct AgentdDurableNeuronInvocationHandleV1 {
    agent_id: AgentId,
    generation: u64,
    owner: Arc<dyn DurableNeuronInvocationOwnerPortV1>,
}

impl std::fmt::Debug for AgentdDurableNeuronInvocationHandleV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("AgentdDurableNeuronInvocationHandleV1")
            .field("agent_id", &self.agent_id)
            .field("generation", &self.generation)
            .finish_non_exhaustive()
    }
}

impl AgentdDurableNeuronInvocationHandleV1 {
    /// Bind one concrete, recovered `AgentdNeuronOwner` to one Agentd process
    /// generation. The shared mutex remains the single owner lifetime used by
    /// both canonical invocation verification and actual Neuron ticks.
    pub fn new<W, P>(
        agent_id: AgentId,
        generation: u64,
        owner: Arc<Mutex<AgentdNeuronOwner<W, P>>>,
    ) -> Result<Self, AgentdError>
    where
        W: AnchorWitnessStore + Send + 'static,
        P: NeuronInferenceControlPort + Send + 'static,
    {
        if generation == 0 {
            return Err(AgentdError::Invalid(
                "durable Neuron invocation owner requires a non-zero Agent generation"
                    .to_string(),
            ));
        }
        let owner: Arc<dyn DurableNeuronInvocationOwnerPortV1> =
            Arc::new(LockedDurableNeuronOwnerV1 { owner });
        let handle = Self {
            agent_id,
            generation,
            owner,
        };
        // Fail at composition rather than first traffic if the owner cannot
        // expose a coherent durable snapshot.
        let _ = handle.owner.snapshot()?;
        Ok(handle)
    }

    pub(crate) fn current_witness(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<AgentdNeuronInvocationWitnessV1, AgentdError> {
        self.require_identity(identity)?;
        let snapshot = self.owner.snapshot()?;
        let owner_revision = match snapshot.anchor {
            Some(anchor) => anchor.sequence.checked_add(1).ok_or_else(|| {
                AgentdError::Protocol("durable Neuron owner revision overflow".to_string())
            })?,
            None => 1,
        };
        let owner_digest = owner_snapshot_digest(&self.agent_id, self.generation, &snapshot)?;
        Ok(AgentdNeuronInvocationWitnessV1 {
            agent_id: self.agent_id.to_string(),
            generation: self.generation,
            owner_revision,
            owner_digest,
        })
    }

    pub(crate) fn verify_invocation(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        invocation: &AgentdIntelligenceInvocationV1,
    ) -> Result<Digest32, AgentdError> {
        self.require_identity(identity)?;
        let witness = self.current_witness(identity)?;
        let snapshot = self.owner.snapshot()?;
        let neural_config = &invocation.inputs.neural_config;
        let config_digest = neural_config.digest().map_err(|error| {
            AgentdError::Invalid(format!(
                "canonical Neuron sparse configuration is invalid: {error}"
            ))
        })?;
        if config_digest != snapshot.native_config_digest
            || neural_config.generation.get() != snapshot.neuron_generation
            || neural_config.model_digest != snapshot.model_digest
            || neural_config.normalization_digest != snapshot.normalization_digest
            || neural_config.width != snapshot.state_width
            || record.snapshot.generation != self.generation
            || record.snapshot.run_id != invocation.request.run_id
            || record.snapshot.objective_digest
                != invocation.inputs.neural_tick.objective_digest
            || record.runtime_body_digest != invocation.inputs.neural_tick.body_digest
        {
            return Err(AgentdError::GenerationFenced(
                "canonical Neuron invocation does not match the current durable owner"
                    .to_string(),
            ));
        }
        invocation_digest(
            record,
            invocation,
            witness.owner_digest,
            snapshot.configuration_digest,
            config_digest,
        )
    }

    fn require_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if self.agent_id != identity.agent_id || self.generation != identity.spawn_generation {
            return Err(AgentdError::GenerationFenced(
                "durable Neuron owner does not match the Agentd identity".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy)]
struct DurableNeuronOwnerSnapshotV1 {
    configuration_digest: Digest32,
    native_config_digest: Digest32,
    model_digest: Digest32,
    normalization_digest: Digest32,
    neuron_generation: u64,
    state_width: usize,
    anchor: Option<JournalAnchor>,
}

trait DurableNeuronInvocationOwnerPortV1: Send + Sync {
    fn snapshot(&self) -> Result<DurableNeuronOwnerSnapshotV1, AgentdError>;
}

struct LockedDurableNeuronOwnerV1<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    owner: Arc<Mutex<AgentdNeuronOwner<W, P>>>,
}

impl<W, P> DurableNeuronInvocationOwnerPortV1 for LockedDurableNeuronOwnerV1<W, P>
where
    W: AnchorWitnessStore + Send + 'static,
    P: NeuronInferenceControlPort + Send + 'static,
{
    fn snapshot(&self) -> Result<DurableNeuronOwnerSnapshotV1, AgentdError> {
        let owner = self.owner.lock().map_err(|_| {
            AgentdError::Protocol("durable Neuron owner mutex is poisoned".to_string())
        })?;
        let runtime = owner.runtime();
        let configuration = runtime.configuration();
        let configuration_digest = runtime.configuration_digest().map_err(|error| {
            AgentdError::Protocol(format!(
                "durable Neuron configuration could not be verified: {error}"
            ))
        })?;
        let anchor = runtime.current_anchor().map_err(|error| {
            AgentdError::Protocol(format!(
                "durable Neuron anchor could not be observed: {error}"
            ))
        })?;
        Ok(DurableNeuronOwnerSnapshotV1 {
            configuration_digest,
            native_config_digest: configuration.native_config_digest,
            model_digest: configuration.head_digest,
            normalization_digest: configuration.normalization_digest,
            neuron_generation: configuration.generation.get(),
            state_width: configuration.state_width,
            anchor,
        })
    }
}

fn owner_snapshot_digest(
    agent_id: &AgentId,
    generation: u64,
    snapshot: &DurableNeuronOwnerSnapshotV1,
) -> Result<Digest32, AgentdError> {
    let mut bytes = b"hepta.runtime-agentd.neuron-owner-witness.v1\0".to_vec();
    push_bytes(&mut bytes, agent_id.as_str().as_bytes())?;
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(snapshot.configuration_digest.as_array());
    bytes.extend_from_slice(snapshot.native_config_digest.as_array());
    bytes.extend_from_slice(snapshot.model_digest.as_array());
    bytes.extend_from_slice(snapshot.normalization_digest.as_array());
    bytes.extend_from_slice(&snapshot.neuron_generation.to_be_bytes());
    bytes.extend_from_slice(&usize_u64(snapshot.state_width)?.to_be_bytes());
    match snapshot.anchor {
        Some(anchor) => {
            bytes.push(1);
            bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
            bytes.extend_from_slice(anchor.checkpoint_digest.as_array());
        }
        None => bytes.push(0),
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn invocation_digest(
    record: &RunStartRecordV1,
    invocation: &AgentdIntelligenceInvocationV1,
    owner_digest: Digest32,
    configuration_digest: Digest32,
    sparse_config_digest: Digest32,
) -> Result<Digest32, AgentdError> {
    let tick = &invocation.inputs.neural_tick;
    let mut bytes = b"hepta.runtime-agentd.neuron-invocation.v1\0".to_vec();
    push_bytes(&mut bytes, record.snapshot.run_id.as_str().as_bytes())?;
    bytes.extend_from_slice(record.snapshot.objective_digest.as_array());
    bytes.extend_from_slice(record.runtime_body_digest.as_array());
    bytes.extend_from_slice(record.snapshot.artifact_set_digest.as_array());
    bytes.extend_from_slice(record.snapshot.model_tuple_digest.as_array());
    bytes.extend_from_slice(record.authentication.signed_body_digest.as_array());
    bytes.extend_from_slice(owner_digest.as_array());
    bytes.extend_from_slice(configuration_digest.as_array());
    bytes.extend_from_slice(sparse_config_digest.as_array());
    for digest in [
        tick.scope_digest,
        tick.objective_digest,
        tick.ndu_digest,
        tick.body_digest,
        tick.input_digest,
    ] {
        if digest.is_zero() {
            return Err(AgentdError::Invalid(
                "canonical Neuron invocation contains an empty digest".to_string(),
            ));
        }
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&tick.sequence.to_be_bytes());
    bytes.extend_from_slice(&tick.monotonic_micros.to_be_bytes());
    bytes.extend_from_slice(&usize_u64(tick.drive_q24.len())?.to_be_bytes());
    for value in &tick.drive_q24 {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&usize_u64(tick.prediction_q24.len())?.to_be_bytes());
    for value in &tick.prediction_q24 {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    match invocation.inputs.neural_previous.as_ref() {
        Some(previous) => {
            bytes.push(1);
            bytes.extend_from_slice(previous.digest().as_array());
            bytes.extend_from_slice(&previous.sequence().to_be_bytes());
            bytes.extend_from_slice(previous.predecessor_digest().as_array());
        }
        None => bytes.push(0),
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_bytes(output: &mut Vec<u8>, value: &[u8]) -> Result<(), AgentdError> {
    output.extend_from_slice(&usize_u64(value.len())?.to_be_bytes());
    output.extend_from_slice(value);
    Ok(())
}

fn usize_u64(value: usize) -> Result<u64, AgentdError> {
    u64::try_from(value)
        .map_err(|_| AgentdError::Protocol("Neuron identity length exceeds u64".to_string()))
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
