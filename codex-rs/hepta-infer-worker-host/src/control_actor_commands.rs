//! Commands applied only by the unique durable writer.

use super::*;

pub(super) enum Command {
    // Fault injection pauses the real writer, never substitutes a second executor.
    #[cfg(test)]
    TestPause {
        entered: std::sync::mpsc::SyncSender<()>,
        release: std::sync::mpsc::Receiver<()>,
    },
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

pub(super) struct AppliedCommand {
    pub(super) shutdown: bool,
    pub(super) successful_reply_lost: bool,
}

impl Command {
    pub(super) fn is_terminal_transition(&self) -> bool {
        match self {
            #[cfg(test)]
            Self::TestPause { .. } => false,
            Self::AbortBeforeEffect { .. }
            | Self::Started { .. }
            | Self::Cancel { .. }
            | Self::StopBeforeDispatch { .. }
            | Self::RejectBeforeStart { .. }
            | Self::SettleLegacy { .. }
            | Self::SettleAuthorized { .. }
            | Self::ReconcileRecovery { .. }
            | Self::RetireRecovery { .. } => true,
            Self::Reserve { .. }
            | Self::BindExecution { .. }
            | Self::PrepareDispatch { .. }
            | Self::PrepareAuthorizedDispatch { .. }
            | Self::Record { .. }
            | Self::Metrics { .. }
            | Self::Compact { .. }
            | Self::Shutdown { .. } => false,
        }
    }

    pub(super) fn apply(
        self,
        control: &mut DurableInferenceControl,
        publisher: &watch::Sender<Option<Arc<NativePublishedMetrics>>>,
    ) -> AppliedCommand {
        let successful_reply_lost = match self {
            #[cfg(test)]
            Self::TestPause { entered, release } => {
                let _ = entered.send(());
                let _ = release.recv();
                false
            }
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
                    false
                } else {
                    send_result(
                        reply,
                        control.dispatch_native_with_pre_effect_abort(&request_id, dispatch),
                    )
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
                false
            }
            Self::Metrics { now_unix_ms, reply } => {
                let metrics = control.native_metrics(now_unix_ms);
                // The observation is published only after the serialized read.
                // A missing subscriber does not undo the durable state.
                publisher.send_replace(Some(NativePublishedMetrics::new(
                    metrics.clone(),
                    now_unix_ms,
                )));
                let _ = reply.send(metrics);
                false
            }
            Self::Compact { reply } => send_result(reply, control.compact_native_journal()),
            Self::Shutdown { reply } => {
                let _ = reply.send(());
                return AppliedCommand {
                    shutdown: true,
                    successful_reply_lost: false,
                };
            }
        };
        AppliedCommand {
            shutdown: false,
            successful_reply_lost,
        }
    }
}

fn send_result<T>(
    reply: oneshot::Sender<ActorResult<T>>,
    result: Result<T, codex_hepta_infer_core::durable_control::Error>,
) -> bool {
    let succeeded = result.is_ok();
    reply
        .send(result.map_err(|error| NativeControlActorError::Control(error.to_string())))
        .is_err()
        && succeeded
}
