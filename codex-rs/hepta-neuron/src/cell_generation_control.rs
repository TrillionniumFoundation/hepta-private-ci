//! Bounded control RPCs backed by the existing durable inference owner.
//! Computation owns no Cell journal, prefix, outbox or publication authority.

use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
#[cfg(test)]
use codex_hepta_infer_core::durable_control::Error as ControlError;
use codex_hepta_infer_core::durable_control::generation::GenerationBindingV1;
#[cfg(test)]
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::cell_generation_types::*;
#[cfg(test)]
use crate::cell_task_cost::*;

#[path = "cell_generation_control_codec.rs"]
mod codec;

use codec::add_cost;
use codec::control_error;
use codec::encode;
use codec::micros;
use codec::no_compute;
use codec::prepare;
use codec::validate;

type Clock = Arc<dyn Fn() -> u64 + Send + Sync>;
type Reply = Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2>;
type WorkerResult = Result<CellGenerationProposalV2, CellGenerationErrorV2>;

/// A concrete, independently cancellable computation. Return a terminal
/// proposal only for an observed result; an error remains an unknown operation.
/// Leave two cost-entry slots for measured control/queue overhead. Implementors
/// must check cancellation and the live deadline at their actual native entry.
pub trait CellGenerationWorkerV2: Send + Sync + 'static {
    fn execute(
        &self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
        cancellation: &AtomicBool,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2>;
}

#[derive(Clone, Debug)]
pub struct ControlledCellGenerationConfigV2 {
    pub scope: CellGenerationScopeV2,
    pub manifest: CellBackendManifestV2,
    pub worker_generation: u64,
    pub queue_capacity: usize,
    pub rpc_timeout: Duration,
}

/// One control actor and at most one independently running computation. A
/// timed-out RPC does not revoke its durable admission. Reopen uses the same
/// binding and clock epoch, and never recreates a dispatch token.
pub struct ControlledCellGenerationPortV2 {
    config: Arc<ControlledCellGenerationConfigV2>,
    commands: Option<mpsc::SyncSender<Command>>,
    stopping: Arc<AtomicBool>,
    closed: Arc<AtomicBool>,
    completion: mpsc::Receiver<Result<(), CellGenerationErrorV2>>,
    terminal: Option<Result<(), CellGenerationErrorV2>>,
}

impl ControlledCellGenerationPortV2 {
    pub fn spawn(
        control: DurableInferenceControl,
        config: ControlledCellGenerationConfigV2,
        worker: Arc<dyn CellGenerationWorkerV2>,
        clock: Clock,
    ) -> Result<Self, CellGenerationErrorV2> {
        config.manifest.digest()?;
        for id in [
            &config.scope.agent_id,
            &config.scope.cell_id,
            &config.scope.run_id,
        ] {
            StableId::new(id).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        }
        if config.scope.principal_digest == [0; 32] || config.worker_generation == 0 {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        if !(1..=64).contains(&config.queue_capacity)
            || config.rpc_timeout.is_zero()
            || config.rpc_timeout > Duration::from_secs(5)
            || config.manifest.max_step_cost_entries < 2
        {
            return Err(CellGenerationErrorV2::Capacity);
        }
        // Existing unknown work is allowed for readback, but a poisoned owner
        // cannot be presented as a successfully constructed control service.
        control.generation_has_unresolved().map_err(control_error)?;
        let config = Arc::new(config);
        let stopping = Arc::new(AtomicBool::new(false));
        let closed = Arc::new(AtomicBool::new(false));
        let (sender, commands) = mpsc::sync_channel(config.queue_capacity);
        let (finished, completion) = mpsc::sync_channel(1);
        let mut actor = Actor {
            control,
            config: Arc::clone(&config),
            worker,
            clock,
            commands,
            stopping: Arc::clone(&stopping),
            active: None,
        };
        let actor_closed = Arc::clone(&closed);
        drop(
            thread::Builder::new()
                .name("cell-generation-control".into())
                .spawn(move || {
                    let result = std::panic::catch_unwind(AssertUnwindSafe(|| actor.run()))
                        .map_err(|_| CellGenerationErrorV2::Unavailable);
                    // Drop the actual file owner before publishing the close observation.
                    drop(actor);
                    actor_closed.store(true, Ordering::Release);
                    let _ = finished.try_send(result);
                })
                .map_err(|_| CellGenerationErrorV2::Unavailable)?,
        );
        Ok(Self {
            config,
            commands: Some(sender),
            stopping,
            closed,
            completion,
            terminal: None,
        })
    }

    /// Stops admission and requests cancellation. Success observes the control
    /// actor's exit and file-lock release, not completion of pending Cell work.
    /// A timeout keeps the owner alive and its file locked until its worker exits.
    pub fn shutdown(&mut self) -> Result<(), CellGenerationErrorV2> {
        self.stopping.store(true, Ordering::Release);
        drop(self.commands.take());
        if let Some(result) = &self.terminal {
            return result.clone();
        }
        let result = match self.completion.recv_timeout(self.config.rpc_timeout) {
            Ok(result) => result,
            Err(mpsc::RecvTimeoutError::Timeout) => {
                return Err(CellGenerationErrorV2::CommitUncertain);
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => Err(CellGenerationErrorV2::Unavailable),
        };
        self.terminal = Some(result.clone());
        result
    }

    pub fn is_closed(&self) -> bool {
        self.closed.load(Ordering::Acquire)
    }

    fn rpc(&mut self, kind: CommandKind, request: &CellGenerationRequestV2) -> Reply {
        if self.stopping.load(Ordering::Acquire) {
            return Err(CellGenerationErrorV2::Unavailable);
        }
        let (binding, payload) = prepare(&self.config, request)?;
        let (reply, response) = mpsc::sync_channel(1);
        let command = Command {
            kind,
            request: Box::new(request.clone()),
            binding,
            payload,
            queued_at: Instant::now(),
            reply,
        };
        self.commands
            .as_ref()
            .ok_or(CellGenerationErrorV2::Unavailable)?
            .try_send(command)
            .map_err(|error| match error {
                mpsc::TrySendError::Full(_) => CellGenerationErrorV2::Capacity,
                mpsc::TrySendError::Disconnected(_) => CellGenerationErrorV2::Unavailable,
            })?;
        response
            .recv_timeout(self.config.rpc_timeout)
            .map_err(|error| match error {
                mpsc::RecvTimeoutError::Timeout => CellGenerationErrorV2::CommitUncertain,
                mpsc::RecvTimeoutError::Disconnected => CellGenerationErrorV2::Unavailable,
            })?
    }
}

impl CellGenerationControlPortV2 for ControlledCellGenerationPortV2 {
    fn execute_generation(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        if manifest != &self.config.manifest {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        self.rpc(CommandKind::Execute, request)?
            .ok_or(CellGenerationErrorV2::Pending)
    }

    fn read_generation(&mut self, request: &CellGenerationRequestV2) -> Reply {
        self.rpc(CommandKind::Read, request)
    }

    fn cancel_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        self.rpc(CommandKind::Cancel, request).map(|_| ())
    }
}

impl Drop for ControlledCellGenerationPortV2 {
    fn drop(&mut self) {
        let _ = self.shutdown();
    }
}

#[derive(Clone, Copy)]
enum CommandKind {
    Execute,
    Read,
    Cancel,
}

struct Command {
    kind: CommandKind,
    request: Box<CellGenerationRequestV2>,
    binding: GenerationBindingV1,
    payload: Vec<u8>,
    queued_at: Instant,
    reply: mpsc::SyncSender<Reply>,
}

struct Running {
    binding: GenerationBindingV1,
    request: Box<CellGenerationRequestV2>,
    cancellation: Arc<AtomicBool>,
    worker: Option<thread::JoinHandle<WorkerResult>>,
    queue_micros: u64,
    control_micros: u64,
    error: Option<CellGenerationErrorV2>,
}

struct Actor {
    control: DurableInferenceControl,
    config: Arc<ControlledCellGenerationConfigV2>,
    worker: Arc<dyn CellGenerationWorkerV2>,
    clock: Clock,
    commands: mpsc::Receiver<Command>,
    stopping: Arc<AtomicBool>,
    active: Option<Running>,
}

impl Actor {
    fn run(&mut self) {
        loop {
            self.collect();
            if self.stopping.load(Ordering::Acquire) {
                if let Some(active) = &self.active {
                    active.cancellation.store(true, Ordering::Release);
                    let _ = self.control.cancel_generation(&active.binding);
                }
                if self
                    .active
                    .as_ref()
                    .is_none_or(|active| active.worker.is_none())
                {
                    return;
                }
            }
            match self.commands.recv_timeout(Duration::from_millis(5)) {
                Ok(command) => {
                    let result = if self.stopping.load(Ordering::Acquire) {
                        Err(CellGenerationErrorV2::Unavailable)
                    } else {
                        match command.kind {
                            CommandKind::Execute => self.execute(&command),
                            CommandKind::Read => self.read(&command),
                            CommandKind::Cancel => self.cancel(&command),
                        }
                    };
                    let _ = command.reply.try_send(result);
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    self.stopping.store(true, Ordering::Release);
                    thread::sleep(Duration::from_millis(1));
                }
            }
        }
    }

    fn execute(&mut self, command: &Command) -> Reply {
        if self
            .control
            .generation_record(&command.binding)
            .map_err(control_error)?
            .is_some()
        {
            return self.read(command);
        }
        if self.active.is_some()
            || self
                .control
                .generation_has_unresolved()
                .map_err(control_error)?
        {
            return Err(CellGenerationErrorV2::Capacity);
        }
        let queue_micros = micros(command.queued_at.elapsed())?;
        let started = Instant::now();
        let admitted_at = (self.clock)();
        let (_, mut token) = self
            .control
            .admit_generation(admitted_at, command.binding.clone(), &command.payload)
            .map_err(control_error)?;
        // An exact existing admission, including after reopen, never gets a token.
        if token.is_none() {
            return self.read(command);
        }
        let now = (self.clock)();
        let abort = if self.stopping.load(Ordering::Acquire) {
            Some(CellGenerationDispositionV2::Cancelled)
        } else if now >= command.request.deadline_micros {
            Some(CellGenerationDispositionV2::DeadlineExceeded)
        } else if admitted_at < command.request.admitted_at_micros || now < admitted_at {
            Some(CellGenerationDispositionV2::Failed)
        } else {
            None
        };
        if let Some(disposition) = abort {
            let mut proposal = no_compute(&self.config.manifest, &command.request, disposition)?;
            add_cost(&mut proposal, queue_micros, micros(started.elapsed())?)?;
            let bytes = encode(&self.config.manifest, &command.request, &proposal)?;
            self.control
                .abort_generation(&mut token, bytes)
                .map_err(control_error)?;
            return Ok(Some(proposal));
        }
        self.control
            .dispatch_generation(now, &mut token)
            .map_err(control_error)?;
        let cancellation = Arc::new(AtomicBool::new(false));
        let worker_cancel = Arc::clone(&cancellation);
        let worker = Arc::clone(&self.worker);
        let config = Arc::clone(&self.config);
        let request = command.request.clone();
        let clock = Arc::clone(&self.clock);
        let stopping = Arc::clone(&self.stopping);
        let control_micros = micros(started.elapsed())?;
        let spawned = thread::Builder::new()
            .name("cell-generation-worker".into())
            .spawn(move || {
                if stopping.load(Ordering::Acquire) || worker_cancel.load(Ordering::Acquire) {
                    no_compute(
                        &config.manifest,
                        &request,
                        CellGenerationDispositionV2::Cancelled,
                    )
                } else {
                    let entry_time = clock();
                    if entry_time >= request.deadline_micros {
                        no_compute(
                            &config.manifest,
                            &request,
                            CellGenerationDispositionV2::DeadlineExceeded,
                        )
                    } else if entry_time < now {
                        no_compute(
                            &config.manifest,
                            &request,
                            CellGenerationDispositionV2::Failed,
                        )
                    } else {
                        worker.execute(&config.manifest, &request, &worker_cancel)
                    }
                }
            });
        let handle = match spawned {
            Ok(handle) => handle,
            Err(_) => {
                // std::thread reports that this thread was never created. This
                // local proof does not apply to an error from an actual worker.
                let mut proposal = no_compute(
                    &self.config.manifest,
                    &command.request,
                    CellGenerationDispositionV2::Failed,
                )?;
                add_cost(&mut proposal, queue_micros, micros(started.elapsed())?)?;
                let bytes = encode(&self.config.manifest, &command.request, &proposal)?;
                self.control
                    .settle_generation(&command.binding, bytes)
                    .map_err(control_error)?;
                return Ok(Some(proposal));
            }
        };
        self.active = Some(Running {
            binding: command.binding.clone(),
            request: command.request.clone(),
            cancellation,
            worker: Some(handle),
            queue_micros,
            control_micros,
            error: None,
        });
        Ok(None)
    }

    fn read(&self, command: &Command) -> Reply {
        let record = self
            .control
            .generation_record(&command.binding)
            .map_err(control_error)?;
        if let Some(record) = record
            && let Some(result) = &record.result
        {
            let proposal = serde_json::from_slice(&result.bytes)
                .map_err(|_| CellGenerationErrorV2::Corrupt)?;
            validate(&self.config.manifest, &command.request, &proposal)?;
            return Ok(Some(proposal));
        }
        if let Some(active) = &self.active
            && active.binding == command.binding
            && let Some(error) = &active.error
        {
            return Err(error.clone());
        }
        Ok(None)
    }

    fn cancel(&mut self, command: &Command) -> Reply {
        self.control
            .cancel_generation(&command.binding)
            .map_err(control_error)?;
        if let Some(active) = &self.active
            && active.binding == command.binding
        {
            active.cancellation.store(true, Ordering::Release);
        }
        Ok(None)
    }

    fn collect(&mut self) {
        let Some(active) = &mut self.active else {
            return;
        };
        if !active
            .worker
            .as_ref()
            .is_some_and(thread::JoinHandle::is_finished)
        {
            return;
        }
        let Some(handle) = active.worker.take() else {
            return;
        };
        let outcome = handle
            .join()
            .map_err(|_| CellGenerationErrorV2::Unavailable)
            .and_then(|result| result)
            .and_then(|mut proposal| {
                add_cost(&mut proposal, active.queue_micros, active.control_micros)?;
                let bytes = encode(&self.config.manifest, &active.request, &proposal)?;
                self.control
                    .settle_generation(&active.binding, bytes)
                    .map_err(control_error)?;
                Ok(())
            });
        match outcome {
            Ok(()) => self.active = None,
            Err(error) => active.error = Some(error),
        }
    }
}

impl Drop for Actor {
    fn drop(&mut self) {
        if let Some(active) = &self.active {
            active.cancellation.store(true, Ordering::Release);
        }
    }
}

#[cfg(test)]
#[path = "cell_generation_control_tests.rs"]
mod tests;
