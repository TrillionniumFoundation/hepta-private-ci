use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::time::Duration;

use anyhow::{Context, Result};
use codex_protocol::ThreadId;
use codex_protocol::error::CodexErr;
use codex_protocol::protocol::TurnAbortReason;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use tokio::sync::{mpsc, oneshot};
use tokio_util::sync::CancellationToken;

use crate::session::TurnInput;
use crate::session::session::Session;
use crate::session::tests::make_session_and_context;
use crate::session::turn_context::TurnContext;
use crate::state::TaskKind;
use crate::tasks::{SessionTask, SessionTaskResult};

use super::{HostedTurnEntry, invalid};

struct CaptureTask {
    confirmed: Arc<AtomicBool>,
    captured: mpsc::UnboundedSender<Arc<HostedTurnEntry>>,
}

impl SessionTask for CaptureTask {
    fn kind(&self) -> TaskKind { TaskKind::Regular }
    fn hosted_execution(&self) -> bool { true }
    fn span_name(&self) -> &'static str { "session_task.hosted_entry_fixture" }

    async fn run(self: Arc<Self>, session: Arc<Session>, context: Arc<TurnContext>,
        _input: Vec<TurnInput>, cancellation: CancellationToken) -> SessionTaskResult {
        let entry = HostedTurnEntry::capture(&session, &context, cancellation.clone(),
            Arc::clone(&self.confirmed)).await?;
        self.captured.send(entry).map_err(|_| invalid("entry fixture receiver closed"))?;
        cancellation.cancelled().await;
        Err(CodexErr::TurnAborted)
    }
}

async fn attach(session: &Arc<Session>, context: &Arc<TurnContext>,
    confirmed: Arc<AtomicBool>) -> Result<Arc<HostedTurnEntry>> {
    let (captured, mut receiver) = mpsc::unbounded_channel();
    session.spawn_task(Arc::clone(context), Vec::new(), CaptureTask { confirmed, captured }).await?;
    tokio::time::timeout(Duration::from_secs(5), receiver.recv()).await?
        .context("original attached task did not capture its entry")
}

#[tokio::test]
async fn hosted_entry_requires_original_queue_confirmation_and_exact_turn() -> Result<()> {
    let (session, context) = make_session_and_context().await;
    let session = Arc::new(session);
    let context = Arc::new(context);
    let confirmed = Arc::new(AtomicBool::new(false));
    let entry = attach(&session, &context, Arc::clone(&confirmed)).await?;
    let effects = AtomicUsize::new(0);
    assert!(entry.with_current(session.thread_id, &context.sub_id, || effects.fetch_add(1, Ordering::SeqCst)).is_err());
    confirmed.store(true, Ordering::Release);
    assert!(entry.with_current(ThreadId::new(), &context.sub_id, || effects.fetch_add(1, Ordering::SeqCst)).is_err());
    assert!(entry.with_current(session.thread_id, "another-turn", || effects.fetch_add(1, Ordering::SeqCst)).is_err());
    assert_eq!(effects.load(Ordering::SeqCst), 0);
    entry.with_current(session.thread_id, &context.sub_id, || effects.fetch_add(1, Ordering::SeqCst))?;
    assert_eq!(effects.load(Ordering::SeqCst), 1);
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    Ok(())
}

#[tokio::test]
async fn hosted_entry_rejects_original_abort_before_callback() -> Result<()> {
    let (session, context) = make_session_and_context().await;
    let session = Arc::new(session);
    let context = Arc::new(context);
    let entry = attach(&session, &context, Arc::new(AtomicBool::new(true))).await?;
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    let effects = AtomicUsize::new(0);
    assert!(entry.with_current(session.thread_id, &context.sub_id, || effects.fetch_add(1, Ordering::SeqCst)).is_err());
    assert_eq!(effects.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn hosted_entry_rejects_shutdown_while_original_task_is_still_attached() -> Result<()> {
    let (session, context) = make_session_and_context().await;
    let session = Arc::new(session);
    let context = Arc::new(context);
    let entry = attach(&session, &context, Arc::new(AtomicBool::new(true))).await?;
    session.begin_shutdown();
    assert!(session.active_turn.lock().await.as_ref().is_some_and(|active| active.task.is_some()));
    let effects = AtomicUsize::new(0);
    assert!(entry.with_current(session.thread_id, &context.sub_id, || effects.fetch_add(1, Ordering::SeqCst)).is_err());
    assert_eq!(effects.load(Ordering::SeqCst), 0);
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    Ok(())
}

#[tokio::test]
async fn hosted_entry_rejects_replacement_even_when_turn_and_context_are_reused() -> Result<()> {
    let (session, context) = make_session_and_context().await;
    let session = Arc::new(session);
    let context = Arc::new(context);
    let old = attach(&session, &context, Arc::new(AtomicBool::new(true))).await?;
    // Use the original lifecycle's replacement, not a synthesized epoch or
    // edited token. Reusing the string and context must not revive old work.
    let current = attach(&session, &context, Arc::new(AtomicBool::new(true))).await?;
    assert!(current.attach_epoch > old.attach_epoch);
    let effects = AtomicUsize::new(0);
    assert!(old.with_current(session.thread_id, &context.sub_id, || effects.fetch_add(1, Ordering::SeqCst)).is_err());
    assert_eq!(effects.load(Ordering::SeqCst), 0);
    current.with_current(session.thread_id, &context.sub_id, || effects.fetch_add(1, Ordering::SeqCst))?;
    assert_eq!(effects.load(Ordering::SeqCst), 1);
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    Ok(())
}

#[tokio::test]
async fn hosted_entry_busy_original_locks_never_run_callback() -> Result<()> {
    let (session, context) = make_session_and_context().await;
    let session = Arc::new(session);
    let context = Arc::new(context);
    let entry = attach(&session, &context, Arc::new(AtomicBool::new(true))).await?;
    let effects = AtomicUsize::new(0);
    {
        let _active = session.active_turn.lock().await;
        assert!(entry.with_current(session.thread_id, &context.sub_id, || effects.fetch_add(1, Ordering::SeqCst)).is_err());
    }
    {
        let _gate = session.start_admission_gate.lock().map_err(|_| anyhow::anyhow!("fixture admission gate poisoned"))?;
        assert!(entry.with_current(session.thread_id, &context.sub_id, || effects.fetch_add(1, Ordering::SeqCst)).is_err());
    }
    assert_eq!(effects.load(Ordering::SeqCst), 0);
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    Ok(())
}

#[tokio::test]
async fn hosted_entry_final_callback_serializes_with_original_abort() -> Result<()> {
    let (session, context) = make_session_and_context().await;
    let session = Arc::new(session);
    let context = Arc::new(context);
    let entry = attach(&session, &context, Arc::new(AtomicBool::new(true))).await?;
    let effects = Arc::new(AtomicUsize::new(0));
    let (entered, observed) = oneshot::channel();
    let (release, released) = std::sync::mpsc::channel();
    let callback = {
        let entry = Arc::clone(&entry);
        let effects = Arc::clone(&effects);
        let thread_id = session.thread_id;
        let turn_id = context.sub_id.clone();
        tokio::task::spawn_blocking(move || -> Result<()> {
            entry.with_current(thread_id, &turn_id, || -> Result<()> {
                entered.send(()).map_err(|_| anyhow::anyhow!("entry observer closed"))?;
                released.recv_timeout(Duration::from_secs(5))?;
                effects.fetch_add(1, Ordering::SeqCst);
                Ok(())
            })??;
            Ok(())
        })
    };
    tokio::time::timeout(Duration::from_secs(5), observed).await??;
    let mut abort = Box::pin(session.abort_all_tasks(TurnAbortReason::Interrupted));
    assert!(abort.as_mut().now_or_never().is_none(), "abort must wait for the in-flight final callback");
    assert!(session.active_turn.try_lock().is_err(), "the original lifecycle lock must span the callback");
    assert_eq!(effects.load(Ordering::SeqCst), 0);
    release.send(())?;
    callback.await??;
    abort.await;
    assert_eq!(effects.load(Ordering::SeqCst), 1);
    assert!(entry.with_current(session.thread_id, &context.sub_id, || effects.fetch_add(1, Ordering::SeqCst)).is_err());
    assert_eq!(effects.load(Ordering::SeqCst), 1);
    Ok(())
}
