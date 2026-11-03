//! Borrow the original Core task's lifecycle at an external effect's final entry.
//! This handle creates no turn, queue claim, writer lease or FinalUse grant.

use std::sync::Arc;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_protocol::ThreadId;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use crate::state::ActiveTurn;
use crate::state::TurnState;
use crate::tasks::AnySessionTask;

use super::invalid;

#[path = "hosted_turn_stream.rs"]
mod stream;
pub use stream::HostedTextDelta;

/// A sealed view of one attached Core task, usable only while that exact task
/// remains current and its original queue completion has been confirmed.
/// Retaining this handle never keeps the Session or its task alive. Every
/// effect must still pass the embedding's original writer/FinalUse gates.
pub struct HostedTurnEntry {
    session: Weak<Session>,
    thread_id: ThreadId,
    turn_id: String,
    task: Weak<dyn AnySessionTask>,
    context: Weak<TurnContext>,
    turn_state: Weak<Mutex<TurnState>>,
    attach_epoch: u64,
    cancellation: CancellationToken,
    confirmed: Arc<AtomicBool>,
    stream_items: Mutex<std::collections::BTreeSet<String>>,
}

impl HostedTurnEntry {
    pub(crate) async fn capture(
        session: &Arc<Session>,
        context: &Arc<TurnContext>,
        cancellation: CancellationToken,
        confirmed: Arc<AtomicBool>,
    ) -> CodexResult<Arc<Self>> {
        // start_task_owned publishes RunningTask while holding this lock. A
        // task polled before that publication waits for its real attach epoch.
        let active = session.active_turn.lock().await;
        let active = active
            .as_ref()
            .ok_or_else(|| invalid("hosted Core task is no longer active"))?;
        let task = active
            .task
            .as_ref()
            .ok_or_else(|| invalid("hosted Core task is not attached"))?;
        if !Arc::ptr_eq(&task.turn_context, context) || !task.task.hosted_execution_owner() {
            return Err(invalid("hosted Core entry belongs to another task"));
        }
        let entry = Arc::new(Self {
            session: Arc::downgrade(session),
            thread_id: session.thread_id,
            turn_id: context.sub_id.clone(),
            task: Arc::downgrade(&task.task),
            context: Arc::downgrade(context),
            turn_state: Arc::downgrade(&active.turn_state),
            attach_epoch: task.attach_epoch,
            cancellation,
            confirmed,
            stream_items: Mutex::new(std::collections::BTreeSet::new()),
        });
        entry.validate_task(session, active)?;
        Ok(entry)
    }

    /// Execute one bounded synchronous final-entry callback under Core's
    /// original lifecycle locks. The callback must perform its actual writer
    /// and FinalUse consume here, without awaiting or reentering Core.
    ///
    /// Busy, cancelled, replaced, terminalizing and stopped tasks fail closed.
    /// A successful callback is ordered before a later Core abort/shutdown;
    /// it does not imply that an asynchronous external operation completed.
    pub fn with_current<T>(
        &self,
        thread_id: ThreadId,
        turn_id: &str,
        enter: impl FnOnce() -> T,
    ) -> CodexResult<T> {
        self.with_attached(thread_id, turn_id, || {
            if !self.confirmed.load(Ordering::Acquire) {
                return Err(invalid("original hosted queue completion is not confirmed"));
            }
            Ok(enter())
        })?
    }

    pub(super) fn require_current(&self) -> CodexResult<()> {
        self.with_attached(self.thread_id, &self.turn_id, || ())
    }

    pub(super) fn confirm_queue_completion(&self) -> CodexResult<()> {
        self.with_attached(self.thread_id, &self.turn_id, || {
            self.confirmed.store(true, Ordering::Release)
        })
    }

    fn with_attached<T>(
        &self,
        thread_id: ThreadId,
        turn_id: &str,
        enter: impl FnOnce() -> T,
    ) -> CodexResult<T> {
        if thread_id != self.thread_id || turn_id != self.turn_id {
            return Err(invalid("hosted Core entry changed its original turn"));
        }
        let session = self
            .session
            .upgrade()
            .ok_or_else(|| invalid("original hosted Core owner stopped"))?;
        let active = session
            .active_turn
            .try_lock()
            .map_err(|_| invalid("original hosted Core lifecycle is busy"))?;
        // Match the existing attach lock order. begin_shutdown uses this same
        // gate, so shutdown cannot publish between our check and callback.
        let _admission_gate = session
            .start_admission_gate
            .try_lock()
            .map_err(|_| invalid("original hosted Core admission gate is unavailable"))?;
        let active = active
            .as_ref()
            .ok_or_else(|| invalid("original hosted Core task ended"))?;
        self.validate_task(&session, active)?;
        Ok(enter())
    }

    fn validate_task(&self, session: &Session, active: &ActiveTurn) -> CodexResult<()> {
        let task = active
            .task
            .as_ref()
            .ok_or_else(|| invalid("original hosted Core task is no longer attached"))?;
        if session.thread_id != self.thread_id
            || task.turn_context.sub_id != self.turn_id
            || active.start_reservation.is_some()
            || active.start_transition.is_some()
            || active.task_terminalization.is_some()
            || task.attach_epoch != self.attach_epoch
            || session.turn_epoch.load(Ordering::Acquire) != self.attach_epoch
            || !Weak::ptr_eq(&self.task, &Arc::downgrade(&task.task))
            || !Weak::ptr_eq(&self.context, &Arc::downgrade(&task.turn_context))
            || !Weak::ptr_eq(&self.turn_state, &Arc::downgrade(&active.turn_state))
        {
            return Err(invalid(
                "original hosted Core task was replaced or terminalized",
            ));
        }
        if session.shutdown_started()
            || task.cancellation_token.is_cancelled()
            || self.cancellation.is_cancelled()
            || task
                .turn_context
                .extension_data
                .get::<codex_extension_api::TurnStartGate>()
                .is_some_and(|gate| !gate.is_allowed())
        {
            return Err(CodexErr::TurnAborted);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "hosted_turn_entry_tests.rs"]
mod tests;
