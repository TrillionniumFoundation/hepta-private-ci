//! Explicit typed generation bootstrap. The queue carries bounded owner
//! commands, never provider selection, model downloads or publication grants.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationReceiptV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellGenerationScopeV2;
use codex_hepta_neuron::CellOutputChunkV2;
use codex_hepta_neuron::CellRuntimeSnapshotV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdNeuronGenerationOwnerV2;
use crate::AgentdState;
use crate::neuron_generation_service::BoundGenerationOwner;
use crate::neuron_generation_service::GenerationRuntimeOwner;
use crate::state::neuron_generation::NeuronGenerationProjection;

pub(crate) type Response<T> = oneshot::Sender<Result<T, CellGenerationErrorV2>>;

pub(crate) struct OutputAcknowledgement {
    pub(crate) chunk: CellOutputChunkV2,
    pub(crate) acknowledgement: [u8; 32],
    pub(crate) cost: CellTaskCostV2,
}

pub(crate) enum GenerationCommand {
    Step {
        request: Box<CellGenerationRequestV2>,
        response: Response<CellGenerationReceiptV2>,
    },
    Reconcile {
        expected: [u8; 32],
        response: Response<CellGenerationReceiptV2>,
    },
    Cancel {
        expected: [u8; 32],
        response: Response<()>,
    },
    Snapshot(Response<CellRuntimeSnapshotV2>),
    PendingRequest(Response<Option<CellGenerationRequestV2>>),
    PendingOutput(Response<Option<CellOutputChunkV2>>),
    TaskCost(Response<CellTaskCostV2>),
    Acknowledge {
        delivery: Box<OutputAcknowledgement>,
        response: Response<()>,
    },
    Drain(Response<bool>),
    Resume(Response<()>),
}

#[derive(Clone)]
pub struct NeuronGenerationRuntimeHandleV2 {
    sender: mpsc::Sender<GenerationCommand>,
    scope: CellGenerationScopeV2,
    manifest_digest: [u8; 32],
    max_input_bytes: usize,
    max_state_bytes: usize,
    max_prefix_bytes: usize,
    max_delta_bytes: usize,
    max_ack_cost_entries: usize,
}

impl NeuronGenerationRuntimeHandleV2 {
    pub async fn step(
        &self,
        request: CellGenerationRequestV2,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        request.digest()?;
        if request.predecessor.scope != self.scope
            || request.predecessor.manifest_digest != self.manifest_digest
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        if request.input.len() > self.max_input_bytes
            || request.predecessor.state.len() > self.max_state_bytes
            || request.predecessor.prefix.len() > self.max_prefix_bytes
        {
            return Err(CellGenerationErrorV2::Capacity);
        }
        self.call(|response| GenerationCommand::Step {
            request: Box::new(request),
            response,
        })
        .await
    }

    /// Inspect only the named durable pending request. A stale queued request
    /// cannot inspect or cancel a successor admitted under another identity.
    pub async fn reconcile(
        &self,
        expected: [u8; 32],
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        self.call(|response| GenerationCommand::Reconcile { expected, response })
            .await
    }

    pub async fn cancel(&self, expected: [u8; 32]) -> Result<(), CellGenerationErrorV2> {
        self.call(|response| GenerationCommand::Cancel { expected, response })
            .await
    }

    pub async fn snapshot(&self) -> Result<CellRuntimeSnapshotV2, CellGenerationErrorV2> {
        self.call(GenerationCommand::Snapshot).await
    }

    pub async fn pending_request(
        &self,
    ) -> Result<Option<CellGenerationRequestV2>, CellGenerationErrorV2> {
        self.call(GenerationCommand::PendingRequest).await
    }

    pub async fn pending_output(&self) -> Result<Option<CellOutputChunkV2>, CellGenerationErrorV2> {
        self.call(GenerationCommand::PendingOutput).await
    }

    pub async fn task_cost(&self) -> Result<CellTaskCostV2, CellGenerationErrorV2> {
        self.call(GenerationCommand::TaskCost).await
    }

    /// Record the transport's exact acknowledgement for already committed
    /// bytes. Calling this method does not itself deliver or publish output.
    pub async fn acknowledge(
        &self,
        chunk: CellOutputChunkV2,
        acknowledgement: [u8; 32],
        cost: CellTaskCostV2,
    ) -> Result<(), CellGenerationErrorV2> {
        StableId::new(&chunk.operation_id).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        if chunk.bytes.len() > self.max_delta_bytes
            || cost.entries().len() > self.max_ack_cost_entries
        {
            return Err(CellGenerationErrorV2::Capacity);
        }
        cost.validate()
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        self.call(|response| GenerationCommand::Acknowledge {
            delivery: Box::new(OutputAcknowledgement {
                chunk,
                acknowledgement,
                cost,
            }),
            response,
        })
        .await
    }

    /// Close this journal's admission durably. Pending computation and output
    /// remain available through their original readback and acknowledgement.
    pub async fn drain(&self) -> Result<bool, CellGenerationErrorV2> {
        self.call(GenerationCommand::Drain).await
    }

    pub async fn resume(&self) -> Result<(), CellGenerationErrorV2> {
        self.call(GenerationCommand::Resume).await
    }

    async fn call<T>(
        &self,
        command: impl FnOnce(Response<T>) -> GenerationCommand,
    ) -> Result<T, CellGenerationErrorV2> {
        let (response, receive) = oneshot::channel();
        self.sender
            .try_send(command(response))
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => CellGenerationErrorV2::Capacity,
                mpsc::error::TrySendError::Closed(_) => CellGenerationErrorV2::Unavailable,
            })?;
        receive
            .await
            .map_err(|_| CellGenerationErrorV2::CommitUncertain)?
    }
}

pub struct NeuronGenerationRuntimeBootstrapV2 {
    identity: AgentdIdentity,
    pub(crate) owner: Box<dyn GenerationRuntimeOwner>,
    pub(crate) receiver: mpsc::Receiver<GenerationCommand>,
    pub(crate) projection: Arc<NeuronGenerationProjection>,
}

/// Consume one exclusive journal and its already admitted control adapter.
///
/// The synchronous adapter must implement bounded control RPC, dispatch and
/// readback, with independently cancellable work behind that boundary. Running
/// an unbounded native model call here cannot provide responsive cancellation.
/// Its own native entry still validates its live deadline and reservation. The
/// clock retains one epoch across reopening; it is not caller-supplied per job.
/// This constructor confers no adoption or external-effect authority.
pub fn neuron_generation_channel_v2<W, P, C>(
    identity: &AgentdIdentity,
    journal: CellGenerationJournalV2<W>,
    inference_control: P,
    clock: C,
    capacity: usize,
) -> Result<
    (
        NeuronGenerationRuntimeHandleV2,
        NeuronGenerationRuntimeBootstrapV2,
    ),
    AgentdError,
>
where
    W: AnchorWitnessStore + Send + 'static,
    P: CellGenerationControlPortV2 + Send + 'static,
    C: FnMut() -> u64 + Send + 'static,
{
    if !(1..=64).contains(&capacity) {
        return Err(AgentdError::Invalid(
            "generation service requires a 1..64 command queue".into(),
        ));
    }
    let generation = Generation::new(identity.spawn_generation)
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    let snapshot = journal
        .snapshot()
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    if snapshot.scope.agent_id != identity.agent_id.as_str() {
        return Err(AgentdError::GenerationFenced(
            "generation journal belongs to another agent".into(),
        ));
    }
    let manifest = journal.manifest();
    let (sender, receiver) = mpsc::channel(capacity);
    let projection = Arc::new(NeuronGenerationProjection::new(
        generation,
        None,
        sender.downgrade(),
    ));
    let handle = NeuronGenerationRuntimeHandleV2 {
        sender,
        scope: snapshot.scope.clone(),
        manifest_digest: snapshot.manifest_digest,
        max_input_bytes: manifest.max_input_bytes as usize,
        max_state_bytes: manifest.max_state_bytes as usize,
        max_prefix_bytes: manifest.max_prefix_bytes as usize,
        max_delta_bytes: manifest.max_delta_bytes as usize,
        max_ack_cost_entries: manifest.max_ack_cost_entries as usize,
    };
    let owner = Box::new(BoundGenerationOwner {
        owner: AgentdNeuronGenerationOwnerV2::new(journal, inference_control),
        clock,
    });
    Ok((
        handle,
        NeuronGenerationRuntimeBootstrapV2 {
            identity: identity.clone(),
            owner,
            receiver,
            projection,
        },
    ))
}

impl NeuronGenerationRuntimeBootstrapV2 {
    /// An explicitly admitted host service replacement, after the same owner
    /// has drained and reopened. These execution generations are independent
    /// of the Cell's model/state generation and are not adoption evidence.
    pub fn with_service_generation(
        mut self,
        generation: Generation,
        expected_predecessor: Option<Generation>,
    ) -> Result<Self, AgentdError> {
        if expected_predecessor.is_some_and(|previous| generation <= previous) {
            return Err(AgentdError::Invalid(
                "generation service replacement must advance".into(),
            ));
        }
        self.projection = Arc::new(NeuronGenerationProjection::new(
            generation,
            expected_predecessor,
            self.projection.command_sender.clone(),
        ));
        Ok(self)
    }

    pub(crate) fn require_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if &self.identity != identity {
            return Err(AgentdError::GenerationFenced(
                "generation bootstrap differs from Agentd identity".into(),
            ));
        }
        Ok(())
    }

    pub(crate) fn attach(&self, state: &AgentdState) -> Result<(), AgentdError> {
        self.require_identity(state.identity())?;
        state.attach_neuron_generation(Arc::clone(&self.projection))
    }
}

#[cfg(test)]
#[path = "neuron_generation_runtime_tests.rs"]
mod tests;
