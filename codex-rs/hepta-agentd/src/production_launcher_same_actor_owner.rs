//! Physical custody of the selected phase's actual Startup/Runtime driver.
//! Cancelling the public waiting future closes the original Gate, then joins
//! this retained thread while the original multi-thread runtime stays alive.
//! Notifications are not results and never certify completion.

use std::future::Future;
use std::io::Write;
use std::panic::AssertUnwindSafe;
use std::panic::catch_unwind;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::task::Context;
use std::task::Poll;
use std::thread::JoinHandle;

use codex_arg0::Arg0DispatchPaths;
use tokio::runtime::Handle;
use tokio::runtime::RuntimeFlavor;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::AgentdOriginalSameActorPhaseStartupV1;
use super::refused;
use crate::AgentdError;
use crate::circuit_task::OriginalCircuitJoinStatus;
use crate::circuit_task::OriginalCircuitOwnerCustody;
use crate::circuit_task::OriginalCircuitResultDelivery;
use crate::root_authority_session::OriginalRootSessionCustodySlot;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_phase::OriginalSameActorBusinessInputsV1;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

#[path = "production_launcher_same_actor_consumer_custody.rs"]
mod bootstrap_consumers;
pub(crate) use bootstrap_consumers::OriginalBootstrapConsumerAdmission;
pub(crate) use bootstrap_consumers::OriginalBootstrapConsumerJob;
pub(crate) use bootstrap_consumers::OriginalBootstrapConsumerKind;
use bootstrap_consumers::OriginalBootstrapConsumers;

#[path = "production_launcher_same_actor_completion_custody.rs"]
mod completion_custody;

pub(super) enum OriginalPhaseSelectedBusiness {
    Embedded(Box<OriginalSameActorBusinessInputsV1>),
    Deployment(crate::same_actor_q24_deployment::OriginalDeploymentDescriptor),
}

struct OriginalPhaseOwnerState {
    identity: Option<crate::AgentdIdentity>,
    gate: Option<Arc<SameActorPhaseGate>>,
    context: Option<Weak<OriginalSameActorRootContext>>,
    circuit: Option<Arc<OriginalCircuitOwnerCustody>>,
}

/// Empty before the receiver creates its real Gate. This object creates no
/// authority, Session, writer or business input. One outer owner retains it.
pub(crate) struct OriginalPhaseRunControl {
    stopped: AtomicBool,
    cancellation: CancellationToken,
    state: Mutex<OriginalPhaseOwnerState>,
    session: OriginalRootSessionCustodySlot,
    consumers: OriginalBootstrapConsumers,
    mcp: Arc<codex_app_server::OriginalMcpRuntimeShutdown>,
    app_server: Arc<codex_app_server::OriginalAppServerOwnerCustody>,
}

impl OriginalPhaseRunControl {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            stopped: AtomicBool::new(false),
            cancellation: CancellationToken::new(),
            state: Mutex::new(OriginalPhaseOwnerState {
                identity: None,
                gate: None,
                context: None,
                circuit: None,
            }),
            session: OriginalRootSessionCustodySlot::new(),
            consumers: OriginalBootstrapConsumers::new(),
            mcp: codex_app_server::OriginalMcpRuntimeShutdown::new(),
            app_server: codex_app_server::OriginalAppServerOwnerCustody::new(),
        })
    }

    pub(crate) fn session_slot(&self) -> &OriginalRootSessionCustodySlot {
        &self.session
    }

    /// Called once by the real receiver immediately after constructing its
    /// Gate from the already captured original clocks and sealed Root bound.
    pub(crate) fn retain_original_receive_gate(
        &self,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        let mut state = self.state.lock().map_err(|_| {
            gate.close();
            refused("original Startup custody is poisoned")
        })?;
        if state.gate.is_some() {
            gate.close();
            return Err(refused("original receive Gate cannot be replaced"));
        }
        state.gate = Some(Arc::clone(gate));
        if self.stopped.load(Ordering::Acquire) {
            gate.close();
            return Err(refused("original Startup was cancelled before receive"));
        }
        gate.require_open()?;
        Ok(())
    }

    pub(crate) fn reserve_original_consumer(
        &self,
        kind: OriginalBootstrapConsumerKind,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<OriginalBootstrapConsumerAdmission<'_>, AgentdError> {
        {
            let state = self.state.lock().map_err(|_| {
                gate.close();
                refused("original Startup custody is poisoned")
            })?;
            if self.stopped.load(Ordering::Acquire)
                || !state
                    .gate
                    .as_ref()
                    .is_some_and(|original| Arc::ptr_eq(original, gate))
            {
                gate.close();
                return Err(refused(
                    "bootstrap consumer differs from the actual receive Gate",
                ));
            }
        }
        self.consumers.reserve(kind, gate)
    }

    pub(super) fn retain_original_context(
        &self,
        context: &Arc<OriginalSameActorRootContext>,
    ) -> Result<(), AgentdError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| refused("original Startup custody is poisoned"))?;
        if state.identity.is_some()
            || state.context.is_some()
            || !state
                .gate
                .as_ref()
                .is_some_and(|gate| Arc::ptr_eq(gate, context.gate()))
            || self.stopped.load(Ordering::Acquire)
        {
            SameActorPhaseGate::close(context.gate());
            return Err(refused(
                "original Startup context cannot be replaced or revived",
            ));
        }
        OriginalSameActorRootContext::require_current(context)?;
        state.identity = Some(context.identity().clone());
        state.context = Some(Arc::downgrade(context));
        Ok(())
    }

    pub(super) fn retain_original_circuit(
        &self,
        context: &Arc<OriginalSameActorRootContext>,
        custody: Arc<OriginalCircuitOwnerCustody>,
    ) -> Result<(), AgentdError> {
        custody.require_original_origin(context.identity(), context.gate())?;
        let mut state = self
            .state
            .lock()
            .map_err(|_| refused("original Startup custody is poisoned"))?;
        if state.circuit.is_some()
            || !state
                .context
                .as_ref()
                .and_then(Weak::upgrade)
                .is_some_and(|original| Arc::ptr_eq(&original, context))
            || self.stopped.load(Ordering::Acquire)
        {
            custody.request_stop();
            return Err(refused(
                "original Circuit custody cannot be replaced or restarted",
            ));
        }
        state.circuit = Some(custody);
        Ok(())
    }

    pub(super) fn request_stop(&self) {
        self.stopped.store(true, Ordering::Release);
        self.cancellation.cancel();
        let (gate, circuit) = {
            // Poison permits only terminal cleanup, never construction.
            let state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            (state.gate.clone(), state.circuit.clone())
        };
        if let Some(gate) = gate {
            SameActorPhaseGate::close(&gate);
        }
        self.consumers.close();
        codex_app_server::OriginalMcpRuntimeShutdown::request_stop(&self.mcp);
        codex_app_server::OriginalAppServerOwnerCustody::request_stop(&self.app_server);
        if let Some(circuit) = circuit {
            OriginalCircuitOwnerCustody::request_stop(&circuit);
        }
    }

    pub(crate) async fn wait_original_shutdown(&self) -> Result<(), AgentdError> {
        let (gate, circuit) = {
            let state = self
                .state
                .lock()
                .map_err(|_| refused("original Startup custody is poisoned"))?;
            (
                state
                    .gate
                    .clone()
                    .ok_or_else(|| refused("actual receive Gate was not installed"))?,
                state
                    .circuit
                    .clone()
                    .ok_or_else(|| refused("actual Circuit custody was not installed"))?,
            )
        };
        let normal = OriginalCircuitOwnerCustody::wait_original_normal_shutdown(&circuit);
        tokio::pin!(normal);
        tokio::select! {
            _ = self.cancellation.cancelled() => {
                Err(refused("original phase requested fault shutdown"))
            }
            _ = gate.cancelled() => {
                Err(refused("original phase was closed during Runtime shutdown"))
            }
            result = normal.as_mut() => {
                result?;
                if self.stopped.load(Ordering::Acquire) {
                    return Err(refused("original phase was stopped during normal handoff"));
                }
                gate.require_open()?;
                Ok(())
            }
        }
    }

    async fn close_and_join_original_resources(&self) -> Result<(), AgentdError> {
        self.request_stop();
        let circuit = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .circuit
            .clone();
        let mut failure = None;
        if let Some(circuit) = circuit {
            match circuit.stop_and_join_original_owner().await {
                Ok(observed) => {
                    let _ = writeln!(
                        std::io::stderr().lock(),
                        "hepta-agentd level=info observation={observed:?}: actual original Circuit cleanup observed",
                    );
                    if observed.admission_poisoned {
                        save_original_failure(
                            &mut failure,
                            refused("original Circuit admission was poisoned"),
                        );
                    }
                    if matches!(
                        observed.status,
                        OriginalCircuitJoinStatus::Joined {
                            delivery: OriginalCircuitResultDelivery::Abandoned,
                            ..
                        }
                    ) {
                        match circuit.take_abandoned_original_result().await {
                            Ok(Some(Err(error))) | Err(error) => {
                                save_original_failure(&mut failure, error)
                            }
                            Ok(Some(Ok(())) | None) => {}
                        }
                    }
                }
                Err(error) => save_original_failure(&mut failure, error),
            }
        }
        if let Err(error) = self.app_server.join_original_app_server().await {
            save_original_failure(
                &mut failure,
                AgentdError::Protocol(format!("original App Server owner cleanup: {error}")),
            );
        }
        if let Err(error) = self.consumers.join_and_release().await {
            save_original_failure(&mut failure, error);
        }
        // run_owned has returned and dropped its receive/Launch/attachment
        // and coordinator owners. Circuit is joined above; no actual Session
        // is intentionally kept alive merely to make this observation succeed.
        match self.session.stop_and_join_retired_session_tasks().await {
            Ok(observed) => {
                let _ = writeln!(
                    std::io::stderr().lock(),
                    "hepta-agentd level=info observation={observed:?}: actual original Session cleanup observed",
                );
            }
            Err(error) => save_original_failure(&mut failure, error),
        }
        // The initializer and actual Runtime future have ended before this
        // cleanup. The same external cap still owns startup, service driver,
        // stdio I/O and Child handles even if their original waiter vanished.
        if let Err(error) = self.mcp.stop_and_join_original_runtime().await {
            save_original_failure(
                &mut failure,
                AgentdError::Protocol(format!("original MCP owner cleanup: {error}")),
            );
        }
        failure.map_or(Ok(()), Err)
    }
}

struct OriginalPhaseThreadStop(Arc<OriginalPhaseRunControl>);
impl Drop for OriginalPhaseThreadStop {
    fn drop(&mut self) {
        OriginalPhaseRunControl::request_stop(&self.0);
    }
}

/// Owns the one actual std thread. Dropping this waiting future cannot detach
/// Startup, either original consumer open, the coordinator or the real Runtime.
pub(super) struct OriginalPhaseRunOwner {
    control: Arc<OriginalPhaseRunControl>,
    completed: oneshot::Receiver<()>,
    thread: Option<JoinHandle<Result<(), AgentdError>>>,
}

impl OriginalPhaseRunOwner {
    pub(super) fn start_original(
        startup: AgentdOriginalSameActorPhaseStartupV1,
        business: OriginalPhaseSelectedBusiness,
        arg0_paths: Arg0DispatchPaths,
    ) -> Result<Self, AgentdError> {
        let runtime = Handle::try_current()
            .map_err(|_| refused("original phase requires its actual runtime"))?;
        if runtime.runtime_flavor() != RuntimeFlavor::MultiThread {
            return Err(refused(
                "original phase requires the actual multi-thread runtime",
            ));
        }
        let control = OriginalPhaseRunControl::new();
        // This guard exists before spawning, including failure to spawn or
        // an owned closure which is never started.
        let thread_stop = OriginalPhaseThreadStop(Arc::clone(&control));
        let worker_control = Arc::clone(&control);
        let (complete, completed) = oneshot::channel();
        let thread = std::thread::Builder::new().name("hepta-phase-owner".into())
            .spawn(move || {
                let _stop = thread_stop;
                let run = catch_unwind(AssertUnwindSafe(|| runtime.block_on(async {
                    let original = super::run::run_owned_original_phase(
                        startup, business, arg0_paths, Arc::clone(&worker_control),
                    );
                    tokio::pin!(original);
                    tokio::select! {
                        result = &mut original => result,
                        signal = crate::runtime::shutdown_signal() => {
                            worker_control.request_stop();
                            // Do not drop the actual receive/Runtime future
                            // when SIGINT/SIGTERM wins. Drive its same owners
                            // to termination before the registry joins below.
                            let result = original.await;
                            match (signal, result) {
                                (Err(signal), Err(original)) => {
                                    let _ = writeln!(
                                        std::io::stderr().lock(),
                                        "hepta-agentd level=error error={signal}: original signal listener also failed",
                                    );
                                    Err(original)
                                }
                                (Err(signal), Ok(_completed)) => Err(signal),
                                (Ok(()), result) => result,
                            }
                        }
                    }
                })));
                let result = match run {
                    Ok(Ok(completed)) => {
                        // This private object exists only after the actual
                        // Root exit, every retained owner cleanup and Session
                        // File release. A generic Runtime Ok cannot reach it.
                        super::run::OriginalPhaseCompletion::require_original_complete(
                            &completed, &worker_control,
                        )
                    }
                    failed => {
                        let original = match failed {
                            Ok(Err(error)) => error,
                            Err(_) => refused("original phase owner panicked"),
                            Ok(Ok(_)) => unreachable!("successful completion handled above"),
                        };
                        // The original future and all its local owners ended.
                        // Always join real registry handles on failure/panic;
                        // a cleanup error never replaces the original cause.
                        let cleanup = runtime.block_on(worker_control.close_and_join_original_resources());
                        if let Err(cleanup) = cleanup {
                            let _ = writeln!(
                                std::io::stderr().lock(),
                                "hepta-agentd level=error error={cleanup}: original phase also failed during physical cleanup",
                            );
                        }
                        Err(original)
                    }
                };
                let _ = complete.send(());
                result
            }).map_err(|error| AgentdError::Protocol(format!("original phase thread: {error}")))?;
        Ok(Self {
            control,
            completed,
            thread: Some(thread),
        })
    }
}

impl Future for OriginalPhaseRunOwner {
    type Output = Result<(), AgentdError>;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        if Pin::new(&mut this.completed).poll(cx).is_pending() {
            return Poll::Pending;
        }
        let Some(thread) = this.thread.take() else {
            return Poll::Ready(Err(refused("original phase result was already consumed")));
        };
        Poll::Ready(join_original_owner(thread))
    }
}

impl Drop for OriginalPhaseRunOwner {
    fn drop(&mut self) {
        OriginalPhaseRunControl::request_stop(&self.control);
        if let Some(thread) = self.thread.take()
            && let Err(error) = join_original_owner(thread)
        {
            let _ = writeln!(
                std::io::stderr().lock(),
                "hepta-agentd level=error error={error}: cancelled original phase owner finished with failure",
            );
        }
    }
}

fn join_original_owner(thread: JoinHandle<Result<(), AgentdError>>) -> Result<(), AgentdError> {
    let joined = match Handle::try_current() {
        Ok(runtime) if runtime.runtime_flavor() == RuntimeFlavor::MultiThread => {
            tokio::task::block_in_place(|| thread.join())
        }
        _ => thread.join(),
    };
    joined.map_err(|_| refused("actual original phase owner thread panicked"))?
}

fn save_original_failure(first: &mut Option<AgentdError>, error: AgentdError) {
    if first.is_none() {
        *first = Some(error);
    } else {
        let _ = writeln!(
            std::io::stderr().lock(),
            "hepta-agentd level=error error={error}: additional original cleanup failure",
        );
    }
}
