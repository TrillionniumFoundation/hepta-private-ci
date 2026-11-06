//! Supervised generation service using the existing versioned task host. The
//! sole journal owner settles state, output and cost; projections only block
//! drain until that owner has observed the closed admission boundary.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdNeuronGenerationOwnerV2;
use crate::AgentdState;
use crate::NeuronGenerationRuntimeBootstrapV2;
use crate::RuntimeTasks;
use crate::neuron_generation::GenerationOwnerBoundary;
use crate::neuron_generation_runtime::GenerationCommand;
use crate::neuron_generation_runtime::OutputAcknowledgement;
use crate::neuron_generation_runtime::Response;
use crate::state::neuron_generation::NeuronGenerationProjection;

pub(crate) const NEURON_GENERATION_SERVICE: &str = "neuron-generation";

/// Private type erasure keeps AgentdConfig concrete while accepting only an
/// exclusive native journal plus the typed inference-control adapter.
pub(crate) trait GenerationRuntimeOwner: Send {
    fn process(
        &mut self,
        command: GenerationCommand,
        state: &AgentdState,
    ) -> Result<(), AgentdError>;
    fn observation(&self) -> Result<(bool, bool), AgentdError>;
    fn drain(&mut self, state: &AgentdState) -> Result<bool, AgentdError>;
}

pub(crate) struct BoundGenerationOwner<W: AnchorWitnessStore, P: CellGenerationControlPortV2, C> {
    pub(crate) owner: AgentdNeuronGenerationOwnerV2<W, P>,
    pub(crate) clock: C,
}

impl<W, P, C> GenerationRuntimeOwner for BoundGenerationOwner<W, P, C>
where
    W: AnchorWitnessStore + Send,
    P: CellGenerationControlPortV2 + Send,
    C: FnMut() -> u64 + Send,
{
    fn process(
        &mut self,
        command: GenerationCommand,
        state: &AgentdState,
    ) -> Result<(), AgentdError> {
        state.require_neuron_generation_recovery()?;
        match command {
            GenerationCommand::Step { request, response } => {
                let result =
                    self.owner
                        .step_checked(*request, &mut self.clock, |boundary| match boundary {
                            GenerationOwnerBoundary::Admission
                            | GenerationOwnerBoundary::Dispatch => require_admission(state),
                            GenerationOwnerBoundary::Settlement => require_recovery(state),
                        });
                respond(state, response, result)
            }
            GenerationCommand::Reconcile { expected, response } => {
                let result = require_pending(&self.owner, expected).and_then(|()| {
                    self.owner
                        .reconcile_checked(&mut self.clock, || require_recovery(state))
                });
                respond(state, response, result)
            }
            GenerationCommand::Cancel { expected, response } => {
                let result = require_pending(&self.owner, expected).and_then(|()| {
                    self.owner
                        .cancel_pending_checked(|| require_recovery(state))
                });
                respond(state, response, result)
            }
            GenerationCommand::Snapshot(response) => {
                respond(state, response, self.owner.journal().snapshot().cloned())
            }
            GenerationCommand::PendingRequest(response) => respond(
                state,
                response,
                self.owner
                    .journal()
                    .pending_request()
                    .map(|request| request.cloned()),
            ),
            GenerationCommand::PendingOutput(response) => respond(
                state,
                response,
                self.owner
                    .journal()
                    .pending_output()
                    .map(|chunk| chunk.cloned()),
            ),
            GenerationCommand::TaskCost(response) => {
                respond(state, response, self.owner.journal().task_cost().cloned())
            }
            GenerationCommand::Acknowledge { delivery, response } => {
                let OutputAcknowledgement {
                    chunk,
                    acknowledgement,
                    cost,
                } = *delivery;
                let result = require_recovery(state).and_then(|()| {
                    self.owner
                        .journal_mut()
                        .acknowledge(chunk, acknowledgement, cost)
                });
                respond(state, response, result)
            }
            GenerationCommand::Drain(response) => {
                let result = require_recovery(state).and_then(|()| self.owner.drain());
                respond(state, response, result)
            }
            GenerationCommand::Resume(response) => {
                let result =
                    require_admission(state).and_then(|()| self.owner.journal_mut().resume());
                respond(state, response, result)
            }
        }
    }

    fn observation(&self) -> Result<(bool, bool), AgentdError> {
        let journal = self.owner.journal();
        let clear = journal.pending_request().map_err(owner_error)?.is_none()
            && journal.pending_output().map_err(owner_error)?.is_none();
        Ok((clear, journal.is_drained().map_err(owner_error)?))
    }

    fn drain(&mut self, state: &AgentdState) -> Result<bool, AgentdError> {
        state.require_neuron_generation_recovery()?;
        self.owner.drain().map_err(owner_error)
    }
}

fn require_pending<W: AnchorWitnessStore, P: CellGenerationControlPortV2>(
    owner: &AgentdNeuronGenerationOwnerV2<W, P>,
    expected: [u8; 32],
) -> Result<(), CellGenerationErrorV2> {
    let pending = owner
        .journal()
        .pending_request()?
        .ok_or(CellGenerationErrorV2::Conflict)?;
    if pending.digest()? != expected {
        return Err(CellGenerationErrorV2::Conflict);
    }
    Ok(())
}

fn require_admission(state: &AgentdState) -> Result<(), CellGenerationErrorV2> {
    if state
        .neuron_generation_admission_ready()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?
    {
        Ok(())
    } else {
        Err(CellGenerationErrorV2::Draining)
    }
}

fn require_recovery(state: &AgentdState) -> Result<(), CellGenerationErrorV2> {
    state
        .require_neuron_generation_recovery()
        .map_err(|_| CellGenerationErrorV2::Unavailable)
}

fn respond<T>(
    state: &AgentdState,
    response: Response<T>,
    result: Result<T, CellGenerationErrorV2>,
) -> Result<(), AgentdError> {
    if let Err(error) = state.require_neuron_generation_recovery() {
        let _ = response.send(Err(CellGenerationErrorV2::Unavailable));
        return Err(error);
    }
    let _ = response.send(result);
    Ok(())
}

fn owner_error(error: CellGenerationErrorV2) -> AgentdError {
    AgentdError::Protocol(format!("generation journal owner unavailable: {error}"))
}

struct ServiceLifetime {
    projection: Arc<NeuronGenerationProjection>,
    retirement_ready: bool,
}

impl Drop for ServiceLifetime {
    fn drop(&mut self) {
        if !self.retirement_ready {
            self.projection.quarantine();
        }
    }
}

pub(crate) fn spawn_neuron_generation_service(
    tasks: &mut RuntimeTasks,
    bootstrap: NeuronGenerationRuntimeBootstrapV2,
    state: Arc<AgentdState>,
    host_cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    bootstrap.attach(&state)?;
    let quarantine = Arc::clone(&bootstrap.projection);
    let retire = Arc::clone(&bootstrap.projection);
    let retire_state = Arc::clone(&state);
    tasks.spawn_optional_service_generation(
        NEURON_GENERATION_SERVICE,
        bootstrap.projection.generation,
        bootstrap.projection.predecessor,
        move |service_cancellation| run(bootstrap, state, host_cancellation, service_cancellation),
        move || {
            quarantine.quarantine();
            Ok(())
        },
        move || {
            retire_state.require_neuron_generation_recovery()?;
            retire.retire()
        },
    )
}

async fn run(
    mut bootstrap: NeuronGenerationRuntimeBootstrapV2,
    state: Arc<AgentdState>,
    host_cancellation: CancellationToken,
    service_cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    let mut lifetime = ServiceLifetime {
        projection: Arc::clone(&bootstrap.projection),
        retirement_ready: false,
    };
    bootstrap.require_identity(state.identity())?;
    state.require_neuron_generation_recovery()?;
    bootstrap
        .projection
        .activate(service_cancellation.clone())?;
    let mut retiring = false;
    loop {
        // Parent shutdown preserves journal admission semantics for supervised
        // reopening; only explicit service retirement writes durable Drain.
        if host_cancellation.is_cancelled() {
            return Ok(());
        }
        state.require_neuron_generation_recovery()?;
        if retiring {
            bootstrap.owner.drain(&state)?;
        }
        let (clear, drained) = bootstrap.owner.observation()?;
        state.require_neuron_generation_recovery()?;
        bootstrap.projection.observe_owner(clear)?;
        if retiring && drained {
            bootstrap.projection.prepare_retirement()?;
            lifetime.retirement_ready = true;
            return Ok(());
        }
        tokio::select! {
            biased;
            () = host_cancellation.cancelled() => return Ok(()),
            () = service_cancellation.cancelled(), if !retiring => {
                bootstrap.projection.close_for_retirement()?;
                retiring = true;
            }
            () = bootstrap.projection.changed() => {}
            command = bootstrap.receiver.recv() => {
                let command = command.ok_or_else(|| AgentdError::Protocol("generation command channel closed".into()))?;
                bootstrap.projection.begin_command()?;
                // Once enqueued, dropping a response never clears admission or
                // pending work. The same request remains recoverable by ID.
                bootstrap.owner.process(command, &state)?;
            }
        }
    }
}
