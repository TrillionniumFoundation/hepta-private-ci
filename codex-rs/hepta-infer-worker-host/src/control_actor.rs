//! Explicit actor boundary for the unique durable inference-control writer.
//!
//! The journal actor is the only component which owns
//! `DurableInferenceControl`. Effect executors receive one-shot capabilities and
//! never borrow the writer across provider awaits. Recovery actors may submit
//! only evidence which was independently verified by `recovery_contracts`.

use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use async_trait::async_trait;
use codex_hepta_infer_core::control_contracts::ProtectedOutput;
use codex_hepta_infer_core::control_contracts::VerifiedExecutionPlan;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeControlMetrics;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
use codex_hepta_infer_core::durable_control::native::NativeMaintenanceReceipt;
use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_infer_core::recovery_contracts::RecoveryExecutionPlan;
use codex_hepta_infer_core::recovery_contracts::VerifiedRecoveryReconciliationReceipt;
use codex_hepta_infer_core::recovery_contracts::VerifiedRecoveryRetirement;
use tokio::sync::oneshot;

use crate::actor_mailbox;
pub use crate::actor_mailbox::NativeWriterQueueMetrics;
use crate::control_port::NativeControlPort;
use crate::control_port::NativeControlPortError;
use crate::control_port::NativeControlPortResult;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeControlActorError {
    Closed,
    Overloaded,
    LegacyDisabled,
    ShutdownDeadlineExceeded,
    Startup(String),
    Control(String),
    Join(String),
}

impl fmt::Display for NativeControlActorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NativeControlActorError {}

type ActorResult<T> = Result<T, NativeControlActorError>;

/// Owner object for the unique journal-writer thread.
pub struct NativeJournalWriterActor {
    handle: NativeJournalWriterHandle,
    join: Option<thread::JoinHandle<()>>,
}

/// Cloneable command port. Cloning this port does not clone or reopen the
/// journal owner.
#[derive(Clone)]
pub struct NativeJournalWriterHandle {
    sender: actor_mailbox::Sender<Command>,
}

impl NativeJournalWriterActor {
    pub fn spawn(journal: PathBuf, capacity: usize) -> ActorResult<Self> {
        Self::spawn_with_queue_capacity(journal, capacity, actor_mailbox::DEFAULT_QUEUE_CAPACITY)
    }

    pub fn spawn_with_queue_capacity(
        journal: PathBuf,
        capacity: usize,
        queue_capacity: usize,
    ) -> ActorResult<Self> {
        let (sender, mut receiver) = actor_mailbox::channel::<Command>(queue_capacity)
            .ok_or_else(|| NativeControlActorError::Startup("invalid mailbox capacity".to_string()))?;
        let (startup_sender, startup_receiver) = std::sync::mpsc::sync_channel(1);
        let join = thread::Builder::new()
            .name("hepta-inference-journal-writer".to_string())
            .spawn(move || {
                let mut control = match DurableInferenceControl::open(journal, capacity) {
                    Ok(control) => {
                        let _ = startup_sender.send(Ok(()));
                        control
                    }
                    Err(error) => {
                        let _ = startup_sender.send(Err(error.to_string()));
                        return;
                    }
                };
                while let Some(command) = receiver.blocking_recv() {
                    if command.apply(&mut control) {
                        break;
                    }
                }
            })
            .map_err(|error| NativeControlActorError::Startup(error.to_string()))?;
        match startup_receiver.recv() {
            Ok(Ok(())) => Ok(Self {
                handle: NativeJournalWriterHandle { sender },
                join: Some(join),
            }),
            Ok(Err(error)) => {
                let _ = join.join();
                Err(NativeControlActorError::Startup(error))
            }
            Err(error) => {
                let _ = join.join();
                Err(NativeControlActorError::Startup(error.to_string()))
            }
        }
    }

    pub fn handle(&self) -> NativeJournalWriterHandle {
        self.handle.clone()
    }

    pub async fn shutdown(mut self) -> ActorResult<()> {
        let (reply, response) = oneshot::channel();
        self.handle
            .sender
            .seal_and_send(Command::Shutdown { reply })
            .map_err(|_| NativeControlActorError::Closed)?;
        tokio::time::timeout(Duration::from_secs(30), response)
            .await
            .map_err(|_| NativeControlActorError::ShutdownDeadlineExceeded)?
            .map_err(|_| NativeControlActorError::Closed)?;
        if let Some(join) = self.join.take() {
            tokio::task::spawn_blocking(move || join.join())
                .await
                .map_err(|error| NativeControlActorError::Join(error.to_string()))?
                .map_err(|_| {
                    NativeControlActorError::Join("journal writer panicked".to_string())
                })?;
        }
        Ok(())
    }
}

impl Drop for NativeJournalWriterActor {
    fn drop(&mut self) {
        // Never leave a writable detached owner behind on an early return.
        // A blocked filesystem call is not forcibly interrupted or reported as
        // stopped: the lock stays held until the actual writer thread exits.
        let (reply, _response) = oneshot::channel();
        let _ = self.handle.sender.seal_and_send(Command::Shutdown { reply });
    }
}

impl NativeJournalWriterHandle {
    pub fn queue_metrics(&self) -> ActorResult<NativeWriterQueueMetrics> {
        self.sender.metrics().map_err(|_| NativeControlActorError::Closed)
    }

    pub async fn reserve(
        &self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.send(Command::Reserve {
            request,
            maximum_in_flight,
            reply,
        })?;
        receive(response).await
    }

    pub async fn bind_execution(
        &self,
        request_id: String,
        plan: Arc<VerifiedExecutionPlan>,
        now_unix_ms: u64,
    ) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.send(Command::BindExecution {
            request_id,
            plan,
            now_unix_ms,
            reply,
        })?;
        receive(response).await
    }

    pub async fn prepare_dispatch_raw(
        &self,
        request_id: String,
        dispatch: NativeDispatch,
    ) -> ActorResult<(NativeRunRecord, NativePreEffectAbortToken)> {
        if !cfg!(test) {
            return Err(NativeControlActorError::LegacyDisabled);
        }
        let (reply, response) = oneshot::channel();
        self.send(Command::PrepareDispatch {
            request_id,
            dispatch,
            reply,
        })?;
        receive(response).await
    }

    pub async fn prepare_authorized_dispatch_raw(
        &self,
        request_id: String,
        dispatch: NativeDispatch,
        plan: Arc<VerifiedExecutionPlan>,
        now_unix_ms: u64,
    ) -> ActorResult<(NativeRunRecord, NativePreEffectAbortToken)> {
        let (reply, response) = oneshot::channel();
        self.send(Command::PrepareAuthorizedDispatch {
            request_id,
            dispatch,
            plan,
            now_unix_ms,
            reply,
        })?;
        receive(response).await
    }

    pub async fn prepare_dispatch(
        &self,
        request_id: String,
        dispatch: NativeDispatch,
    ) -> ActorResult<PreparedNativeEffect> {
        if !cfg!(test) {
            return Err(NativeControlActorError::LegacyDisabled);
        }
        let (reply, response) = oneshot::channel();
        self.send(Command::PrepareDispatch {
            request_id: request_id.clone(),
            dispatch,
            reply,
        })?;
        let (record, abort_token) = receive(response).await?;
        Ok(PreparedNativeEffect {
            writer: self.clone(),
            request_id,
            record,
            abort_token: Some(abort_token),
        })
    }

    pub async fn prepare_authorized_dispatch(
        &self,
        request_id: String,
        dispatch: NativeDispatch,
        plan: Arc<VerifiedExecutionPlan>,
        now_unix_ms: u64,
    ) -> ActorResult<PreparedNativeEffect> {
        let (reply, response) = oneshot::channel();
        self.send(Command::PrepareAuthorizedDispatch {
            request_id: request_id.clone(),
            dispatch,
            plan,
            now_unix_ms,
            reply,
        })?;
        let (record, abort_token) = receive(response).await?;
        Ok(PreparedNativeEffect {
            writer: self.clone(),
            request_id,
            record,
            abort_token: Some(abort_token),
        })
    }

    pub async fn abort_raw(
        &self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.send(Command::AbortBeforeEffect {
            token,
            reason,
            reply,
        })?;
        receive(response).await
    }

    pub async fn started(
        &self,
        request_id: String,
        turn_id: String,
    ) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.send(Command::Started {
            request_id,
            turn_id,
            reply,
        })?;
        receive(response).await
    }

    pub async fn reject_before_start(
        &self,
        request_id: String,
        rejection: NativeDispatchRejection,
    ) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.send(Command::RejectBeforeStart {
            request_id,
            rejection,
            reply,
        })?;
        receive(response).await
    }

    pub async fn cancel(&self, request_id: String) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.send(Command::Cancel { request_id, reply })?;
        receive(response).await
    }

    pub async fn stop_before_dispatch(
        &self,
        request_id: String,
        reason: String,
    ) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.send(Command::StopBeforeDispatch {
            request_id,
            reason,
            reply,
        })?;
        receive(response).await
    }

    pub async fn settle_legacy(
        &self,
        request_id: String,
        output: NativeRunOutput,
    ) -> ActorResult<NativeRunRecord> {
        if !cfg!(test) {
            return Err(NativeControlActorError::LegacyDisabled);
        }
        let (reply, response) = oneshot::channel();
        self.send(Command::SettleLegacy {
            request_id,
            output,
            reply,
        })?;
        receive(response).await
    }

    pub async fn settle_authorized(
        &self,
        request_id: String,
        plan: Arc<VerifiedExecutionPlan>,
        now_unix_ms: u64,
        output: NativeRunOutput,
        protected_output: Option<ProtectedOutput>,
    ) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.send(Command::SettleAuthorized {
            request_id,
            plan,
            now_unix_ms,
            output,
            protected_output,
            reply,
        })?;
        receive(response).await
    }

    pub async fn record(&self, request_id: String) -> ActorResult<Option<NativeRunRecord>> {
        let (reply, response) = oneshot::channel();
        self.send(Command::Record { request_id, reply })?;
        response.await.map_err(|_| NativeControlActorError::Closed)
    }

    pub async fn metrics(&self, now_unix_ms: u64) -> ActorResult<NativeControlMetrics> {
        let (reply, response) = oneshot::channel();
        self.send(Command::Metrics { now_unix_ms, reply })?;
        response.await.map_err(|_| NativeControlActorError::Closed)
    }

    pub async fn compact(&self) -> ActorResult<NativeMaintenanceReceipt> {
        let (reply, response) = oneshot::channel();
        self.send(Command::Compact { reply })?;
        receive(response).await
    }

    fn send(&self, command: Command) -> ActorResult<()> {
        self.sender.send(command).map_err(|error| match error {
            actor_mailbox::SendError::Full => NativeControlActorError::Overloaded,
            actor_mailbox::SendError::Closed => NativeControlActorError::Closed,
        })
    }
}

#[async_trait]
impl NativeControlPort for NativeJournalWriterHandle {
    async fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> NativeControlPortResult<NativeRunRecord> {
        self.reserve(request, maximum_in_flight)
            .await
            .map_err(NativeControlPortError::Actor)
    }

    async fn bind_native_execution(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> NativeControlPortResult<NativeRunRecord> {
        self.bind_execution(request_id.to_string(), Arc::new(plan.clone()), now_unix_ms)
            .await
            .map_err(NativeControlPortError::Actor)
    }

    async fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> NativeControlPortResult<(NativeRunRecord, NativePreEffectAbortToken)> {
        // The App Server compatibility spelling is bound-only in production.
        // The actor validates its durable plan binding and real wall clock at
        // application time; an unbound caller cannot use this as a raw port.
        let (reply, response) = oneshot::channel();
        self.send(Command::PrepareDispatch {
            request_id: request_id.to_string(),
            dispatch,
            reply,
        })
        .map_err(NativeControlPortError::Actor)?;
        receive(response).await.map_err(NativeControlPortError::Actor)
    }

    async fn dispatch_native_authorized_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> NativeControlPortResult<(NativeRunRecord, NativePreEffectAbortToken)> {
        self.prepare_authorized_dispatch_raw(
            request_id.to_string(),
            dispatch,
            Arc::new(plan.clone()),
            now_unix_ms,
        )
        .await
        .map_err(NativeControlPortError::Actor)
    }

    async fn abort_native_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> NativeControlPortResult<NativeRunRecord> {
        self.abort_raw(token, reason)
            .await
            .map_err(NativeControlPortError::Actor)
    }

    async fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> NativeControlPortResult<NativeRunRecord> {
        self.started(request_id.to_string(), turn_id)
            .await
            .map_err(NativeControlPortError::Actor)
    }

    async fn reject_native_before_start(
        &mut self,
        request_id: &str,
        rejection: NativeDispatchRejection,
    ) -> NativeControlPortResult<NativeRunRecord> {
        self.reject_before_start(request_id.to_string(), rejection)
            .await
            .map_err(NativeControlPortError::Actor)
    }

    async fn cancel_native(
        &mut self,
        request_id: &str,
    ) -> NativeControlPortResult<NativeRunRecord> {
        self.cancel(request_id.to_string())
            .await
            .map_err(NativeControlPortError::Actor)
    }

    async fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> NativeControlPortResult<NativeRunRecord> {
        self.stop_before_dispatch(request_id.to_string(), reason)
            .await
            .map_err(NativeControlPortError::Actor)
    }

    async fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> NativeControlPortResult<NativeRunRecord> {
        self.settle_legacy(request_id.to_string(), output)
            .await
            .map_err(NativeControlPortError::Actor)
    }

    async fn settle_native_authorized(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
        output: NativeRunOutput,
        protected_output: Option<ProtectedOutput>,
    ) -> NativeControlPortResult<NativeRunRecord> {
        self.settle_authorized(
            request_id.to_string(),
            Arc::new(plan.clone()),
            now_unix_ms,
            output,
            protected_output,
        )
        .await
        .map_err(NativeControlPortError::Actor)
    }

    async fn native_record(
        &self,
        request_id: &str,
    ) -> NativeControlPortResult<Option<NativeRunRecord>> {
        self.record(request_id.to_string())
            .await
            .map_err(NativeControlPortError::Actor)
    }
}

/// Capability returned after the write-ahead dispatch is durable but before the
/// provider effect is sent. It can either be aborted with proof or consumed by
/// crossing the effect boundary; it cannot be cloned.
pub struct PreparedNativeEffect {
    writer: NativeJournalWriterHandle,
    request_id: String,
    record: NativeRunRecord,
    abort_token: Option<NativePreEffectAbortToken>,
}

impl PreparedNativeEffect {
    pub fn record(&self) -> &NativeRunRecord {
        &self.record
    }

    pub async fn abort_before_effect(mut self, reason: String) -> ActorResult<NativeRunRecord> {
        let token = self
            .abort_token
            .take()
            .ok_or(NativeControlActorError::Closed)?;
        let (reply, response) = oneshot::channel();
        self.writer.send(Command::AbortBeforeEffect {
            token,
            reason,
            reply,
        })?;
        receive(response).await
    }

    /// Consume the local no-effect proof immediately before sending the
    /// provider request. Any subsequent uncertainty must reconcile; it may not
    /// be converted back into a safe abort.
    pub fn cross_effect_boundary(mut self) -> DispatchedNativeEffect {
        let _ = self.abort_token.take();
        DispatchedNativeEffect {
            writer: self.writer,
            request_id: self.request_id,
        }
    }
}

/// Effect executor capability after the external-effect boundary was crossed.
#[derive(Clone)]
pub struct DispatchedNativeEffect {
    writer: NativeJournalWriterHandle,
    request_id: String,
}

impl DispatchedNativeEffect {
    pub fn request_id(&self) -> &str {
        &self.request_id
    }

    pub async fn started(&self, turn_id: String) -> ActorResult<NativeRunRecord> {
        self.writer.started(self.request_id.clone(), turn_id).await
    }

    pub async fn cancel(&self) -> ActorResult<NativeRunRecord> {
        self.writer.cancel(self.request_id.clone()).await
    }

    pub async fn settle_authorized(
        &self,
        plan: Arc<VerifiedExecutionPlan>,
        now_unix_ms: u64,
        output: NativeRunOutput,
        protected_output: Option<ProtectedOutput>,
    ) -> ActorResult<NativeRunRecord> {
        self.writer
            .settle_authorized(
                self.request_id.clone(),
                plan,
                now_unix_ms,
                output,
                protected_output,
            )
            .await
    }
}

/// Separate recovery actor. It has no effect-execution API and can submit only
/// already verified recovery capabilities to the unique writer.
#[derive(Clone)]
pub struct NativeReconcilerActor {
    writer: NativeJournalWriterHandle,
}

impl NativeReconcilerActor {
    pub fn new(writer: NativeJournalWriterHandle) -> Self {
        Self { writer }
    }

    pub async fn reconcile(
        &self,
        request_id: String,
        plan: Arc<RecoveryExecutionPlan>,
        verified: Arc<VerifiedRecoveryReconciliationReceipt>,
    ) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.writer.send(Command::ReconcileRecovery {
            request_id,
            plan,
            verified,
            reply,
        })?;
        receive(response).await
    }

    pub async fn retire(
        &self,
        request_id: String,
        plan: Arc<RecoveryExecutionPlan>,
        verified: Arc<VerifiedRecoveryRetirement>,
    ) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.writer.send(Command::RetireRecovery {
            request_id,
            plan,
            verified,
            reply,
        })?;
        receive(response).await
    }
}

enum Command {
    Reserve {
        request: NativeRequest,
        maximum_in_flight: usize,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    BindExecution {
        request_id: String,
        plan: Arc<VerifiedExecutionPlan>,
        now_unix_ms: u64,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    PrepareDispatch {
        request_id: String,
        dispatch: NativeDispatch,
        reply: oneshot::Sender<ActorResult<(NativeRunRecord, NativePreEffectAbortToken)>>,
    },
    PrepareAuthorizedDispatch {
        request_id: String,
        dispatch: NativeDispatch,
        plan: Arc<VerifiedExecutionPlan>,
        now_unix_ms: u64,
        reply: oneshot::Sender<ActorResult<(NativeRunRecord, NativePreEffectAbortToken)>>,
    },
    AbortBeforeEffect {
        token: NativePreEffectAbortToken,
        reason: String,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    Started {
        request_id: String,
        turn_id: String,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    Cancel {
        request_id: String,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    StopBeforeDispatch {
        request_id: String,
        reason: String,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    RejectBeforeStart {
        request_id: String,
        rejection: NativeDispatchRejection,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    SettleLegacy {
        request_id: String,
        output: NativeRunOutput,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    SettleAuthorized {
        request_id: String,
        plan: Arc<VerifiedExecutionPlan>,
        now_unix_ms: u64,
        output: NativeRunOutput,
        protected_output: Option<ProtectedOutput>,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    ReconcileRecovery {
        request_id: String,
        plan: Arc<RecoveryExecutionPlan>,
        verified: Arc<VerifiedRecoveryReconciliationReceipt>,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    RetireRecovery {
        request_id: String,
        plan: Arc<RecoveryExecutionPlan>,
        verified: Arc<VerifiedRecoveryRetirement>,
        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,
    },
    Record {
        request_id: String,
        reply: oneshot::Sender<Option<NativeRunRecord>>,
    },
    Metrics {
        now_unix_ms: u64,
        reply: oneshot::Sender<NativeControlMetrics>,
    },
    Compact {
        reply: oneshot::Sender<ActorResult<NativeMaintenanceReceipt>>,
    },
    Shutdown {
        reply: oneshot::Sender<()>,
    },
}

impl Command {
    /// Returns true when the actor must terminate.
    fn apply(self, control: &mut DurableInferenceControl) -> bool {
        match self {
            Self::Reserve {
                request,
                maximum_in_flight,
                reply,
            } => send_result(reply, control.reserve_native(request, maximum_in_flight)),
            Self::BindExecution {
                request_id,
                plan,
                now_unix_ms,
                reply,
            } => send_result(
                reply,
                control.bind_native_execution(&request_id, &plan, now_unix_ms),
            ),
            Self::PrepareDispatch {
                request_id,
                dispatch,
                reply,
            } => {
                if !cfg!(test)
                    && control
                        .native_record(&request_id)
                        .and_then(|record| record.execution_binding.as_ref())
                        .is_none()
                {
                    let _ = reply.send(Err(NativeControlActorError::LegacyDisabled));
                } else {
                    send_result(
                        reply,
                        control.dispatch_native_with_pre_effect_abort(&request_id, dispatch),
                    );
                }
            }
            Self::PrepareAuthorizedDispatch {
                request_id,
                dispatch,
                plan,
                now_unix_ms,
                reply,
            } => send_result(
                reply,
                control.dispatch_native_authorized_with_pre_effect_abort(
                    &request_id,
                    dispatch,
                    &plan,
                    now_unix_ms,
                ),
            ),
            Self::AbortBeforeEffect {
                token,
                reason,
                reply,
            } => send_result(reply, control.abort_native_before_effect(token, reason)),
            Self::Started {
                request_id,
                turn_id,
                reply,
            } => send_result(reply, control.native_started(&request_id, turn_id)),
            Self::Cancel { request_id, reply } => {
                send_result(reply, control.cancel_native(&request_id))
            }
            Self::StopBeforeDispatch {
                request_id,
                reason,
                reply,
            } => send_result(
                reply,
                control.stop_native_before_dispatch(&request_id, reason),
            ),
            Self::RejectBeforeStart {
                request_id,
                rejection,
                reply,
            } => send_result(
                reply,
                control.reject_native_before_start(&request_id, rejection),
            ),
            Self::SettleLegacy {
                request_id,
                output,
                reply,
            } => send_result(reply, control.settle_native(&request_id, output)),
            Self::SettleAuthorized {
                request_id,
                plan,
                now_unix_ms,
                output,
                protected_output,
                reply,
            } => send_result(
                reply,
                control.settle_native_authorized(
                    &request_id,
                    &plan,
                    now_unix_ms,
                    output,
                    protected_output,
                ),
            ),
            Self::ReconcileRecovery {
                request_id,
                plan,
                verified,
                reply,
            } => send_result(
                reply,
                control.reconcile_native_recovery(&request_id, &plan, &verified),
            ),
            Self::RetireRecovery {
                request_id,
                plan,
                verified,
                reply,
            } => send_result(
                reply,
                control.retire_native_indeterminate_recovery(&request_id, &plan, &verified),
            ),
            Self::Record { request_id, reply } => {
                let _ = reply.send(control.native_record(&request_id).cloned());
            }
            Self::Metrics { now_unix_ms, reply } => {
                let _ = reply.send(control.native_metrics(now_unix_ms));
            }
            Self::Compact { reply } => send_result(reply, control.compact_native_journal()),
            Self::Shutdown { reply } => {
                let _ = reply.send(());
                return true;
            }
        }
        false
    }
}

fn send_result<T>(
    reply: oneshot::Sender<ActorResult<T>>,
    result: Result<T, codex_hepta_infer_core::durable_control::Error>,
) {
    let _ = reply.send(result.map_err(|error| NativeControlActorError::Control(error.to_string())));
}

async fn receive<T>(response: oneshot::Receiver<ActorResult<T>>) -> ActorResult<T> {
    response
        .await
        .map_err(|_| NativeControlActorError::Closed)?
}

#[cfg(test)]
#[path = "control_actor_compat_tests.rs"]
mod compatibility_tests;
