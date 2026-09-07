use super::handlers;
use super::session::Session;
use crate::state::RunningTask;
use crate::state::TaskKind;
use crate::tasks::SuspensionHandoff;
use crate::tasks::SuspensionHandoffPhase;
use crate::tasks::SuspensionHandoffSlot;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::turn_input::SuspendTurnOutcome;
use futures::FutureExt;
use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::oneshot;
use tracing::warn;

/// The public caller is bounded independently from the detached handoff. A
/// timeout here only reports that the accepted operation is still fenced; it
/// never clears the active marker, aborts the writer owner, or signals the
/// completion registry.
const SUSPENSION_HANDOFF_CALLER_TIMEOUT: Duration = Duration::from_secs(30);

pub(super) async fn suspend_turn_and_shutdown(
    session: &Arc<Session>,
    submission_id: String,
) -> CodexResult<SuspendTurnOutcome> {
    suspend_turn_and_shutdown_inner(session, submission_id, /*check_descendants*/ true).await
}

#[cfg(test)]
pub(super) async fn suspend_turn_and_shutdown_for_test(
    session: &Arc<Session>,
    submission_id: String,
) -> CodexResult<SuspendTurnOutcome> {
    // Unit fixtures do not own a ThreadManager; skip only the descendant
    // inventory snapshot so the post-claim handoff itself is exercised.
    suspend_turn_and_shutdown_inner(session, submission_id, false).await
}

async fn suspend_turn_and_shutdown_inner(
    session: &Arc<Session>,
    submission_id: String,
    check_descendants: bool,
) -> CodexResult<SuspendTurnOutcome> {
    if session.shutdown_started() {
        return Ok(SuspendTurnOutcome::NotActive);
    }
    {
        let active = session.active_turn.lock().await;
        if active
            .as_ref()
            .is_some_and(|turn| turn.task_terminalization.is_some())
        {
            return Ok(SuspendTurnOutcome::NotActive);
        }
        let Some(task) = active.as_ref().and_then(|turn| turn.task.as_ref()) else {
            return Ok(SuspendTurnOutcome::NotActive);
        };
        if task.kind != TaskKind::Regular {
            return Ok(SuspendTurnOutcome::UnsupportedTask);
        }
    }

    // This is a snapshot of currently loaded descendants, not a spawn-admission seal.
    // Previously closed descendants and concurrent future spawns remain best effort.
    if check_descendants
        && session
            .services
            .agent_control
            .list_live_agent_subtree_thread_ids(session.thread_id)
            .await?
            .len()
            > 1
    {
        return Ok(SuspendTurnOutcome::HasLiveDescendants);
    }

    let live_thread = session
        .live_thread_for_persistence("suspend an unfinished root turn")
        .map_err(|error| CodexErr::Fatal(error.to_string()))?;
    // Flush before canceling execution so a persistence failure leaves the original turn running.
    live_thread.flush().await.map_err(|error| {
        CodexErr::Fatal(format!("flush before root turn suspension failed: {error}"))
    })?;

    // The flush can yield while the active turn completes or changes.  Claim
    // and detach by exact task/context/epoch identity only after the flush;
    // the typed marker remains installed until the writer is closed.
    let (reply_tx, reply_rx) = oneshot::channel();
    let handoff_slot: SuspensionHandoffSlot = Arc::new(std::sync::Mutex::new(None));
    let (identity, slot) = session
        .take_task_for_suspension(handoff_slot, live_thread.clone(), submission_id, reply_tx)
        .await
        .ok_or_else(|| CodexErr::Fatal("root turn changed during suspension".to_string()))?;
    let Some(started_rx) = spawn_suspension_handoff(
        Arc::clone(session),
        Arc::clone(&identity),
        Arc::clone(&slot),
    ) else {
        // There is no safe synchronous substitute for the writer close and
        // shutdown ordering. Leave the full witness fenced for a later
        // shutdown drain instead of pretending the thread is idle.
        return Err(CodexErr::Fatal(
            "root turn suspension owner could not be scheduled; handoff remains fenced".to_string(),
        ));
    };
    // `Handle::spawn` can accept a handle whose scheduler is already closing
    // and silently drop the task before its first poll.  Require an explicit
    // first-poll witness, but never clear or synchronously unwind the claimed
    // marker when the witness does not arrive; the registry slot remains
    // available to a later shutdown drain.
    if !matches!(
        tokio::time::timeout(Duration::from_secs(1), started_rx).await,
        Ok(Ok(()))
    ) {
        return Err(CodexErr::Fatal(
            "root turn suspension owner did not reach its runtime; handoff remains fenced"
                .to_string(),
        ));
    }
    match tokio::time::timeout(SUSPENSION_HANDOFF_CALLER_TIMEOUT, reply_rx).await {
        Ok(Ok(result)) => result,
        Ok(Err(_)) => Err(CodexErr::InternalAgentDied),
        Err(_) => Err(CodexErr::Fatal(
            "root turn suspension is still draining; ownership remains fenced".to_string(),
        )),
    }
}

/// Runs the accepted suspension handoff independently of its submitting
/// future. Dropping the caller's `JoinHandle` therefore cannot drop the task,
/// writer, or exact terminalization witness.
fn spawn_suspension_handoff(
    session: Arc<Session>,
    identity: Arc<()>,
    slot: SuspensionHandoffSlot,
) -> Option<oneshot::Receiver<()>> {
    let runtime_handle = tokio::runtime::Handle::try_current().ok()?;
    let (started_tx, started_rx) = oneshot::channel();
    runtime_handle.spawn(async move {
        let _ = started_tx.send(());
        let Some(handoff) = take_suspension_handoff(&slot) else {
            return;
        };
        if tokio::time::timeout(
            crate::tasks::TERMINALIZER_WATCHDOG_TIMEOUT,
            drive_suspension_handoff(session, identity, slot, handoff),
        )
        .await
        .is_err()
        {
            warn!("suspension handoff watchdog expired; retaining its completion fence");
        }
    });
    Some(started_rx)
}

fn take_suspension_handoff(slot: &SuspensionHandoffSlot) -> Option<SuspensionHandoff> {
    slot.lock()
        .expect("suspension handoff slot mutex poisoned")
        .take()
}

fn retain_suspension_handoff(slot: &SuspensionHandoffSlot, handoff: SuspensionHandoff) {
    let mut current = slot.lock().expect("suspension handoff slot mutex poisoned");
    if current.is_some() {
        warn!("suspension handoff slot already has an owner; retaining the existing fence");
    } else {
        *current = Some(handoff);
    }
}

/// Owns a claimed handoff while its detached worker is being polled. If the
/// worker itself is cancelled by runtime teardown, the complete witness is
/// returned to the registry slot instead of being dropped with the future.
struct SuspensionHandoffOwner {
    slot: SuspensionHandoffSlot,
    handoff: Option<SuspensionHandoff>,
}

impl SuspensionHandoffOwner {
    fn new(slot: SuspensionHandoffSlot, handoff: SuspensionHandoff) -> Self {
        Self {
            slot,
            handoff: Some(handoff),
        }
    }

    fn handoff_mut(&mut self) -> &mut SuspensionHandoff {
        self.handoff
            .as_mut()
            .expect("suspension owner remains armed")
    }

    fn disarm(mut self) -> SuspensionHandoff {
        self.handoff.take().expect("suspension owner remains armed")
    }
}

impl Drop for SuspensionHandoffOwner {
    fn drop(&mut self) {
        if let Some(handoff) = self.handoff.take() {
            let mut handoff = handoff;
            // Repeating cancellation/reap and input clearing is safe. Once
            // shutdown or writer persistence has started, a dropped runtime
            // leaves an external side effect uncertain; retain the marker
            // explicitly fail-closed instead of blindly repeating a close.
            if matches!(
                handoff.phase,
                SuspensionHandoffPhase::RuntimeStopping
                    | SuspensionHandoffPhase::WriterFlushing
                    | SuspensionHandoffPhase::WriterClosing
                    | SuspensionHandoffPhase::LifecyclePublishing
                    | SuspensionHandoffPhase::EventPublishing
                    | SuspensionHandoffPhase::MarkerReleasing
            ) {
                handoff.failed_closed = true;
            }
            retain_suspension_handoff(&self.slot, handoff);
        }
    }
}

/// Keeps the complete `RunningTask` inside the handoff while it is being
/// cancelled and reaped.  In particular, the execution/diagnostic/timer
/// guards must not be dropped merely because the submitting future vanished.
struct SuspensionRunningTaskGuard<'a> {
    handoff: &'a mut SuspensionHandoff,
    task: Option<RunningTask>,
    finished: bool,
}

impl<'a> SuspensionRunningTaskGuard<'a> {
    fn take(handoff: &'a mut SuspensionHandoff) -> Option<Self> {
        handoff.suspended.task.take().map(|task| Self {
            handoff,
            task: Some(task),
            finished: false,
        })
    }

    fn task_mut(&mut self) -> &mut RunningTask {
        self.task
            .as_mut()
            .expect("suspension running task remains armed")
    }

    fn complete(&mut self) {
        self.finished = true;
        self.task.take();
    }
}

impl Drop for SuspensionRunningTaskGuard<'_> {
    fn drop(&mut self) {
        if !self.finished {
            if self.handoff.suspended.task.is_none() {
                self.handoff.suspended.task = self.task.take();
            } else {
                warn!(
                    "suspension handoff already contains its running task during owner cancellation"
                );
            }
        }
    }
}

async fn drive_suspension_handoff(
    session: Arc<Session>,
    identity: Arc<()>,
    slot: SuspensionHandoffSlot,
    handoff: SuspensionHandoff,
) {
    if !take_handoff_identity(&handoff, &identity) {
        let mut handoff = handoff;
        handoff.failed_closed = true;
        if let Some(reply) = handoff.reply.take() {
            let _ = reply.send(Err(CodexErr::Fatal(
                "suspension handoff identity changed; ownership remains fenced".to_string(),
            )));
        }
        retain_suspension_handoff(&slot, handoff);
        return;
    }
    let mut owner = SuspensionHandoffOwner::new(Arc::clone(&slot), handoff);
    let result = AssertUnwindSafe(run_suspension_handoff(&session, owner.handoff_mut()))
        .catch_unwind()
        .await;
    match result {
        Ok(Ok(outcome)) => {
            let mut handoff = owner.disarm();
            if let Some(reply) = handoff.reply.take() {
                let _ = reply.send(Ok(outcome));
            }
        }
        Ok(Err(error)) => {
            if let Some(reply) = owner.handoff_mut().reply.take() {
                let _ = reply.send(Err(error));
            }
            owner.handoff_mut().failed_closed = true;
        }
        Err(_) => {
            warn!(
                %session.thread_id,
                "suspension handoff panicked; retaining its completion fence"
            );
            if let Some(reply) = owner.handoff_mut().reply.take() {
                let _ = reply.send(Err(CodexErr::Fatal(
                    "root turn suspension handoff panicked; ownership remains fenced".to_string(),
                )));
            }
            owner.handoff_mut().failed_closed = true;
        }
    }
}

fn take_handoff_identity(handoff: &SuspensionHandoff, identity: &Arc<()>) -> bool {
    Arc::ptr_eq(&handoff.suspended.terminalization_identity, identity)
}

/// Performs every post-claim operation in the required order. The marker and
/// completion registry remain installed through writer close and all
/// lifecycle/event delivery; any earlier error leaves the handoff fenced.
async fn run_suspension_handoff(
    session: &Arc<Session>,
    handoff: &mut SuspensionHandoff,
) -> CodexResult<SuspendTurnOutcome> {
    let turn_id = handoff.suspended.turn_context.sub_id.clone();
    let task_phase = handoff.phase;
    if matches!(
        task_phase,
        SuspensionHandoffPhase::Claimed | SuspensionHandoffPhase::TaskQuiescing
    ) {
        handoff.phase = SuspensionHandoffPhase::TaskQuiescing;
        let Some(mut task_guard) = SuspensionRunningTaskGuard::take(handoff) else {
            return Err(CodexErr::Fatal(
                "accepted root turn suspension had no running task".to_string(),
            ));
        };
        // Normal shutdown records a terminal turn event, preventing another
        // worker from recovering this turn under its original ID. Cancel
        // without that event while retaining the complete task witness in the
        // guard.
        task_guard.task_mut().cancellation_token.cancel();
        task_guard
            .task_mut()
            .turn_context
            .turn_metadata_state
            .cancel_git_enrichment_task();
        let gracefully_reaped = {
            let handle = &mut task_guard.task_mut().handle;
            match tokio::time::timeout(
                Duration::from_millis(crate::tasks::GRACEFULL_INTERRUPTION_TIMEOUT_MS),
                handle,
            )
            .await
            {
                Ok(Ok(())) => true,
                Ok(Err(error)) => {
                    warn!(thread_id = %session.thread_id, %error, "suspended turn task exited abnormally");
                    true
                }
                Err(_) => {
                    warn!(
                        thread_id = %session.thread_id,
                        "suspended turn task did not stop gracefully; aborting it"
                    );
                    false
                }
            }
        };
        if !gracefully_reaped {
            task_guard.task_mut().handle.abort();
            // Do not await a possibly non-cooperative JoinHandle without a
            // second bound. If it remains live, return while the guard still
            // owns the task and the outer handoff keeps its marker/registry
            // fence.
            let quiesced = tokio::time::timeout(
                Duration::from_millis(crate::tasks::GRACEFULL_INTERRUPTION_TIMEOUT_MS),
                async {
                    while !task_guard.task_mut().handle.is_finished() {
                        tokio::task::yield_now().await;
                    }
                },
            )
            .await
            .is_ok();
            if !quiesced {
                return Err(CodexErr::Fatal(
                    "suspended turn task did not quiesce after abort; ownership remains fenced"
                        .to_string(),
                ));
            }
        }
        task_guard.complete();
    } else if !matches!(
        task_phase,
        SuspensionHandoffPhase::InputClearing
            | SuspensionHandoffPhase::RuntimeStopping
            | SuspensionHandoffPhase::WriterFlushing
            | SuspensionHandoffPhase::WriterClosing
            | SuspensionHandoffPhase::LifecyclePublishing
            | SuspensionHandoffPhase::EventPublishing
            | SuspensionHandoffPhase::MarkerReleasing
    ) {
        return Err(CodexErr::Fatal(
            "accepted root turn suspension had no running task".to_string(),
        ));
    }
    // Pending accepted input and interactive waiters live only in this process.
    handoff.phase = SuspensionHandoffPhase::InputClearing;
    session
        .input_queue
        .clear_pending_for_turn_state(&handoff.suspended.turn_state)
        .await;

    // Stop all producers before flushing their final history and closing its
    // writer. Exclude this exact handoff from the recursive drain.
    handoff.phase = SuspensionHandoffPhase::RuntimeStopping;
    Box::pin(
        handlers::shutdown_session_runtime_excluding_with_suspension(
            session,
            Some(&handoff.suspended.terminalization_identity),
            Some(&handoff.suspended.terminalization_identity),
        ),
    )
    .await;
    handoff.phase = SuspensionHandoffPhase::WriterFlushing;
    handoff.live_thread.flush().await.map_err(|error| {
        CodexErr::Fatal(format!("flush after root turn suspension failed: {error}"))
    })?;
    handoff.phase = SuspensionHandoffPhase::WriterClosing;
    handoff.live_thread.shutdown().await.map_err(|error| {
        CodexErr::Fatal(format!("close suspended root turn writer failed: {error}"))
    })?;
    // Announce thread shutdown only after its writer closes so a replacement
    // worker cannot write the same thread concurrently.
    handoff.phase = SuspensionHandoffPhase::LifecyclePublishing;
    handlers::emit_thread_stop_lifecycle(session.as_ref()).await;
    handoff.phase = SuspensionHandoffPhase::EventPublishing;
    session
        .deliver_event_raw(Event {
            id: handoff.submission_id.clone(),
            msg: EventMsg::ShutdownComplete,
        })
        .await;
    // This exact CAS is the final await in the handoff.  Keeping the marker
    // installed through lifecycle/event delivery ensures a cancellation or
    // runtime teardown cannot publish an idle session before the final
    // shutdown evidence has been attempted.
    handoff.phase = SuspensionHandoffPhase::MarkerReleasing;
    if !session.finish_task_suspension(&handoff.suspended).await {
        return Err(CodexErr::Fatal(
            "suspended root turn ownership changed before final release".to_string(),
        ));
    }
    handoff.phase = SuspensionHandoffPhase::Complete;
    Ok(SuspendTurnOutcome::Suspended { turn_id })
}

/// Adopts any suspension witness whose detached task was queued but never
/// polled (including an already-closing runtime). Running owners have an empty
/// slot and are waited on through the existing terminalization completion
/// fence; failed owners remain fenced and are never retried blindly.
pub(super) async fn drain_suspension_handoffs_for_shutdown_excluding(
    session: &Arc<Session>,
    excluded_identity: Option<&Arc<()>>,
) {
    loop {
        let candidates = session.pending_suspension_handoffs_except(excluded_identity);
        let mut adopted = false;
        for (identity, slot) in candidates {
            let Some(handoff) = take_suspension_handoff(&slot) else {
                continue;
            };
            if handoff.failed_closed {
                retain_suspension_handoff(&slot, handoff);
                continue;
            }
            adopted = true;
            drive_suspension_handoff(Arc::clone(session), identity, slot, handoff).await;
        }
        if !adopted {
            return;
        }
    }
}
