//! The phase route admits before building and transfers to the real queue under
//! one mutex. A ticket survives the driver, source publication and learning
//! observation; closing A never turns an old request into a later C request.

use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::Weak;
use std::time::Duration;

use codex_hepta_neuron::FileAnchorWitnessStore;
use tokio::sync::watch;

use super::*;
use crate::AgentdCircuitTaskInvocationProviderV1;
use crate::circuit_q24_successor::OriginalSameActorSuccessorTaskParts;
use crate::circuit_q24_successor::SuccessorSlot;
use crate::circuit_q24_task_profile::OriginalSameActorATaskParts;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

#[path = "circuit_task_same_actor_admission.rs"]
mod admission;
#[path = "circuit_task_same_actor_learning.rs"]
mod learning;

type Invocation = Arc<dyn AgentdCircuitTaskInvocationProviderV1>;

struct OriginalTask {
    handle: Arc<DirectTaskHandle>,
    invocation: Invocation,
}

enum Phase {
    PendingA,
    A {
        original: Arc<OriginalTask>,
    },
    ClosingA {
        original: Arc<OriginalTask>,
    },
    AwaitingC,
    C {
        slot: Arc<SuccessorSlot>,
        invocation: Invocation,
    },
}

struct RouteState {
    phase: Phase,
    tickets: usize,
    closed: bool,
}

/// This route supplies no task, completed receipt or publication permission.
/// Only the two sealed owner-parts constructors can populate its phases.
pub(crate) struct SameActorTaskRoute {
    identity: AgentdIdentity,
    gate: Arc<SameActorPhaseGate>,
    state: Mutex<RouteState>,
    invocation: OnceLock<Weak<dyn AgentdCircuitTaskInvocationProviderV1>>,
    changed: watch::Sender<()>,
    learning_work:
        OnceLock<Arc<crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork>>,
}

struct PhaseInvocation {
    route: Arc<SameActorTaskRoute>,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum TaskPhase {
    A,
    C,
}

struct AdmittedOriginalTask {
    route: Arc<SameActorTaskRoute>,
    phase: TaskPhase,
    original: Arc<OriginalTask>,
    record: RunStartRecordV1,
}

/// Not Clone: one exact admission may submit computation at most once.
/// The private shared inner is also retained by queued/running work.
pub(crate) struct SameActorTaskAdmission {
    original: Arc<AdmittedOriginalTask>,
    built: Option<CircuitTaskRequestV1>,
    submitted: bool,
    completed: bool,
}

/// A cancelled caller cannot hide queued or executing work from phase drain.
pub(super) struct SameActorQueuedTask {
    original: Arc<AdmittedOriginalTask>,
}

impl SameActorTaskRoute {
    pub(crate) fn pending_original(
        identity: &AgentdIdentity,
        gate: Arc<SameActorPhaseGate>,
    ) -> Result<(Arc<Self>, Invocation), AgentdError> {
        gate.require_open().map_err(phase_error)?;
        if identity.spawn_generation == 0 || identity.spawn_generation.checked_add(1).is_none() {
            gate.close();
            return Err(AgentdError::GenerationFenced(
                "same-actor task route requires the original process identity".into(),
            ));
        }
        let (changed, _) = watch::channel(());
        let route = Arc::new(Self {
            identity: identity.clone(),
            gate,
            state: Mutex::new(RouteState {
                phase: Phase::PendingA,
                tickets: 0,
                closed: false,
            }),
            invocation: OnceLock::new(),
            changed,
            learning_work: OnceLock::new(),
        });
        let invocation: Invocation = Arc::new(PhaseInvocation {
            route: Arc::clone(&route),
        });
        if route.invocation.set(Arc::downgrade(&invocation)).is_err() {
            route.close();
            return Err(AgentdError::Protocol(
                "same-actor task invocation was already bound".into(),
            ));
        }
        route.require_identity(identity)?;
        Ok((route, invocation))
    }

    pub(crate) fn require_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        self.gate.require_open().map_err(phase_error)?;
        if &self.identity != identity {
            self.close();
            return Err(AgentdError::GenerationFenced(
                "same-actor task route differs from the original identity".into(),
            ));
        }
        Ok(())
    }

    /// The returned owners are the actual A worker and its original source,
    /// Cell and ledger. Queue installation is not an A completion assertion.
    pub(crate) fn install_original_a(
        &self,
        parts: OriginalSameActorATaskParts,
    ) -> Result<
        (
            CircuitTaskRuntimeBootstrapV1,
            Arc<crate::CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
            crate::PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
            Arc<crate::OriginalCellQ24TaskLedgerProducerV1>,
        ),
        AgentdError,
    > {
        let mut close = CloseSameActorPhaseOnDrop::new(&self.gate);
        let (bootstrap, invocation, source, cell, ledger) =
            parts.into_task_parts(&self.identity, &self.gate)?;
        bootstrap.require_identity(&self.identity)?;
        let handle = bootstrap.handle();
        handle
            .require_direct_original_handle()
            .map_err(task_error)?;
        let original = Arc::new(OriginalTask {
            handle: handle.original_direct_handle().map_err(task_error)?,
            invocation,
        });
        {
            let mut state = self.state.lock().map_err(|_| poisoned_route())?;
            self.gate.require_open().map_err(phase_error)?;
            if state.closed || state.tickets != 0 || !matches!(state.phase, Phase::PendingA) {
                return Err(AgentdError::Protocol(
                    "same-actor A task can only be installed once while pending".into(),
                ));
            }
            state.phase = Phase::A { original };
        }
        self.changed.send_replace(());
        self.gate.require_open().map_err(phase_error)?;
        close.disarm();
        Ok((bootstrap, source, cell, ledger))
    }

    /// Existing exact-A tickets may finish their one submission. A caller
    /// arriving after this cut cannot obtain a ticket or build a request.
    pub(crate) fn begin_closing_original_a(&self) -> Result<(), AgentdError> {
        let mut close = CloseSameActorPhaseOnDrop::new(&self.gate);
        {
            let mut state = self.state.lock().map_err(|_| poisoned_route())?;
            self.gate.require_open().map_err(phase_error)?;
            let Phase::A { original } = &state.phase else {
                return Err(AgentdError::Protocol(
                    "same-actor A admission is not open".into(),
                ));
            };
            if state.closed {
                return Err(AgentdError::Protocol(
                    "same-actor task route is closed".into(),
                ));
            }
            state.phase = Phase::ClosingA {
                original: Arc::clone(original),
            };
        }
        self.changed.send_replace(());
        self.gate.require_open().map_err(phase_error)?;
        close.disarm();
        Ok(())
    }

    pub(crate) async fn wait_original_a_quiescent(&self) -> Result<(), AgentdError> {
        let mut close = CloseSameActorPhaseOnDrop::new(&self.gate);
        // Subscribe before checking the state; a final drop between the check
        // and changed().await is retained by watch rather than lost.
        let mut changed = self.changed.subscribe();
        loop {
            let remaining = self.gate.require_open().map_err(phase_error)?;
            let empty = {
                let state = self.state.lock().map_err(|_| poisoned_route())?;
                let Phase::ClosingA { original } = &state.phase else {
                    return Err(AgentdError::Protocol(
                        "same-actor A queue is not closing".into(),
                    ));
                };
                if state.closed {
                    return Err(AgentdError::Protocol(
                        "same-actor task route is closed".into(),
                    ));
                }
                state.tickets == 0 && original.handle.pending.load(Ordering::Acquire) == 0
            };
            if empty {
                self.gate.require_open().map_err(phase_error)?;
                close.disarm();
                return Ok(());
            }
            tokio::select! {
                _ = self.gate.cancelled() => {
                    return Err(AgentdError::Protocol("same-actor task route is closed".into()));
                }
                result = changed.changed() => {
                    result.map_err(|_| poisoned_route())?;
                }
                // A wait budget only. The original two absolute ends above
                // are rechecked, including BOOTTIME after system suspend.
                _ = tokio::time::sleep(remaining.min(Duration::from_millis(5))) => {}
            }
        }
    }

    /// Drop this route's A capabilities only after ticket and queue drain.
    /// The controller separately proves durable A completion and joins/drops
    /// the actual A worker before constructing the original C publication.
    pub(crate) fn release_original_a(&self) -> Result<(), AgentdError> {
        let mut close = CloseSameActorPhaseOnDrop::new(&self.gate);
        let previous = {
            let mut state = self.state.lock().map_err(|_| poisoned_route())?;
            self.gate.require_open().map_err(phase_error)?;
            let Phase::ClosingA { original } = &state.phase else {
                return Err(AgentdError::Protocol(
                    "same-actor A release requires its closing queue".into(),
                ));
            };
            if state.closed
                || state.tickets != 0
                || original.handle.pending.load(Ordering::Acquire) != 0
            {
                return Err(AgentdError::Protocol(
                    "same-actor A still has admitted or queued work".into(),
                ));
            }
            std::mem::replace(&mut state.phase, Phase::AwaitingC)
        };
        drop(previous);
        self.changed.send_replace(());
        self.gate.require_open().map_err(phase_error)?;
        close.disarm();
        Ok(())
    }

    pub(crate) fn install_original_c(
        &self,
        parts: OriginalSameActorSuccessorTaskParts,
    ) -> Result<(), AgentdError> {
        let mut close = CloseSameActorPhaseOnDrop::new(&self.gate);
        let (slot, invocation) = parts.into_task_parts(&self.identity, &self.gate)?;
        {
            let mut state = self.state.lock().map_err(|_| poisoned_route())?;
            self.gate.require_open().map_err(phase_error)?;
            if state.closed || state.tickets != 0 || !matches!(state.phase, Phase::AwaitingC) {
                return Err(AgentdError::Protocol(
                    "same-actor C task requires the single released A phase".into(),
                ));
            }
            state.phase = Phase::C { slot, invocation };
        }
        self.changed.send_replace(());
        self.gate.require_open().map_err(phase_error)?;
        close.disarm();
        Ok(())
    }

    fn admit_original_task(
        self: &Arc<Self>,
        expected: &Invocation,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<SameActorTaskAdmission, Error> {
        self.gate.require_open().map_err(|_| Error::Unavailable)?;
        if &self.identity != identity
            || identity.spawn_generation.checked_add(1) != Some(record.snapshot.generation)
            || !self
                .invocation
                .get()
                .and_then(Weak::upgrade)
                .is_some_and(|invocation| Arc::ptr_eq(&invocation, expected))
        {
            self.close();
            return Err(Error::InvalidBinding);
        }
        let original = {
            let mut state = self.state.lock().map_err(|_| {
                self.gate.close();
                Error::Unavailable
            })?;
            self.gate.require_open().map_err(|_| Error::Unavailable)?;
            if state.closed {
                return Err(Error::Unavailable);
            }
            let (phase, original) = match &state.phase {
                Phase::A { original } => (TaskPhase::A, Arc::clone(original)),
                Phase::C { slot, invocation } => {
                    // Pending C cannot obtain a ticket. Neither its build nor
                    // its request is retained for execution after installation.
                    let installed = slot.actual_handle()?;
                    installed.require_direct_original_handle()?;
                    let handle = installed.original_direct_handle()?;
                    (
                        TaskPhase::C,
                        Arc::new(OriginalTask {
                            handle,
                            invocation: Arc::clone(invocation),
                        }),
                    )
                }
                Phase::PendingA | Phase::ClosingA { .. } | Phase::AwaitingC => {
                    return Err(Error::Unavailable);
                }
            };
            state.tickets = state.tickets.checked_add(1).ok_or_else(|| {
                self.gate.close();
                Error::Unavailable
            })?;
            Arc::new(AdmittedOriginalTask {
                route: Arc::clone(self),
                phase,
                original,
                record: record.clone(),
            })
        };
        Ok(SameActorTaskAdmission {
            original,
            built: None,
            submitted: false,
            completed: false,
        })
    }

    fn require_ticket_locked(
        &self,
        state: &RouteState,
        ticket: &AdmittedOriginalTask,
    ) -> Result<(), Error> {
        self.gate.require_open().map_err(|_| Error::Unavailable)?;
        if state.closed || state.tickets == 0 {
            return Err(Error::Unavailable);
        }
        let matches = match (&state.phase, ticket.phase) {
            (Phase::A { original } | Phase::ClosingA { original }, TaskPhase::A) => {
                Arc::ptr_eq(original, &ticket.original)
            }
            (Phase::C { slot, invocation }, TaskPhase::C) => {
                if !Arc::ptr_eq(invocation, &ticket.original.invocation) {
                    false
                } else {
                    let installed = slot.actual_handle()?;
                    let current = installed.original_direct_handle()?;
                    Arc::ptr_eq(&current, &ticket.original.handle)
                }
            }
            _ => false,
        };
        if !matches {
            return Err(Error::InvalidBinding);
        }
        Ok(())
    }

    pub(super) fn pending_count(&self) -> usize {
        let state = match self.state.lock() {
            Ok(state) => state,
            Err(_) => return 1,
        };
        let work = match &state.phase {
            Phase::A { original } | Phase::ClosingA { original } => {
                original.handle.pending.load(Ordering::Acquire)
            }
            Phase::C { slot, .. } => slot.pending_count(),
            Phase::PendingA | Phase::AwaitingC => 0,
        };
        state
            .tickets
            .saturating_add(work)
            .saturating_add(self.learning_work.get().map_or(0, |original| {
                crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork::pending_count(
                    original,
                )
            }))
    }

    pub(crate) fn close(&self) {
        self.gate.close();
        let slot = {
            let mut state = match self.state.lock() {
                Ok(state) => state,
                Err(poisoned) => poisoned.into_inner(),
            };
            state.closed = true;
            match &state.phase {
                Phase::C { slot, .. } => Some(Arc::clone(slot)),
                _ => None,
            }
        };
        if let Some(slot) = slot {
            slot.close();
        }
        // Keep original handles so actual work remains visible to drain.
        self.changed.send_replace(());
    }
}

impl SameActorQueuedTask {
    pub(super) fn require_original_queue_admission(&self) -> Result<(), Error> {
        self.original.require_original_admission()
    }
}

impl CircuitTaskHandleV1 {
    pub(crate) fn admit_original_same_actor_task(
        &self,
        invocation: &Invocation,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<Option<SameActorTaskAdmission>, Error> {
        match &self.route {
            TaskHandleRoute::SameActor { original } => original
                .admit_original_task(invocation, identity, record)
                .map(Some),
            TaskHandleRoute::Direct { .. } | TaskHandleRoute::OriginalQ24 { .. } => Ok(None),
        }
    }
}

impl CircuitTaskRuntimeBootstrapV1 {
    pub(crate) fn from_original_same_actor_worker(
        identity: &AgentdIdentity,
        route: Arc<SameActorTaskRoute>,
        worker: crate::same_actor_q24_phase::OriginalSameActorTaskWorker,
    ) -> Result<Self, AgentdError> {
        route.require_identity(identity)?;
        Ok(Self {
            identity: identity.clone(),
            handle: CircuitTaskHandleV1 {
                route: TaskHandleRoute::SameActor { original: route },
            },
            owner: Box::new(move |store, state, cancellation| {
                Box::pin(worker.run(store, state, cancellation))
            }),
        })
    }
}

fn task_error(error: Error) -> AgentdError {
    AgentdError::Protocol(format!("Circuit task execution failed: {error}"))
}

fn phase_error(error: std::io::Error) -> AgentdError {
    AgentdError::Protocol(format!("original same-actor phase unavailable: {error}"))
}

fn poisoned_route() -> AgentdError {
    AgentdError::Protocol("original same-actor task route is poisoned or unavailable".into())
}

#[cfg(test)]
#[path = "circuit_task_same_actor_phase_tests.rs"]
mod tests;
