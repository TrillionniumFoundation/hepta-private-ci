//! Actual runtime teardown and same-turn recovery assertions.

use pretty_assertions::assert_eq;

use super::*;
use std::path::PathBuf;

use super::store_pause::{PauseUserAppendStore, UserAppendPause, is_user_response};

#[derive(Clone, Copy)]
enum SuspendPoint { BeforeCheckpoint, BeforeUserAppend }

struct SuspendedOriginal {
    home: Arc<TempDir>,
    cwd: Arc<TempDir>,
    sqlite: SqliteConfig,
    rollout: PathBuf,
    thread_id: ThreadId,
    turn_id: String,
    item_id: String,
    input: TurnInput,
    digest: String,
    input_written: bool,
    old_thread: Weak<codex_core::CodexThread>,
    old_queue: Weak<FailDeleteOnceQueueStore>,
    old_thread_store: Weak<dyn codex_thread_store::ThreadStore>,
}

async fn suspend_original(owner: Arc<ExecutionOwner>, point: SuspendPoint) -> anyhow::Result<SuspendedOriginal> {
    let server = start_mock_server().await;
    let (builder, fixture, executor) = builder(owner.clone(), ResumeMode::Original);
    let pause = Arc::new(UserAppendPause::default());
    let mut builder = if matches!(point, SuspendPoint::BeforeUserAppend) {
        let pause = pause.clone();
        builder.with_thread_store_decorator(move |inner| PauseUserAppendStore::wrap(inner, pause))
    } else { builder };
    let test = builder.build(&server).await?;
    if matches!(point, SuspendPoint::BeforeUserAppend) { pause.arm(); }
    let (service, queue) = install_queue(&test, &fixture, executor, true)?;
    let thread_id = test.session_configured.thread_id;
    let input = structured_user_input("one retained preparation input");
    let TurnInput::UserInput { content, client_id: Some(client) } = &input else { unreachable!() };
    let digest = user_input_payload_sha256(content)?;
    let queued = service.reconcile(thread_id, test.codex.rollout_path(), input.clone(), digest.clone(), QueueReconcileMode::AllowIfAbsent).await?;
    let QueueReconcileOutcome::Queued { item, created: true } = queued.outcome else { anyhow::bail!("original client was not queued once"); };
    let start = tokio::spawn({
        let service = service.clone(); let thread = test.codex.clone(); let id = item.id.clone();
        async move { service.start(&thread, Some(id), None).await }
    });
    let input_written = matches!(point, SuspendPoint::BeforeCheckpoint);
    if input_written {
        tokio::time::timeout(Duration::from_secs(10), fixture.entered.notified()).await?;
    } else {
        tokio::time::timeout(Duration::from_secs(10), pause.entered.notified()).await?;
        // Read the actual fsynced Core provenance while its first user append
        // has not reached the original store. No history is created or removed.
        let attempted = pause.attempted.get().context("actual blocked user append")?;
        assert_eq!(attempted.thread_id, thread_id);
        assert_eq!(attempted.items.len(), 1);
        assert!(is_user_response(&attempted.items[0]));
        assert!(owner.recovery.get().is_none(), "host execution must not have begun");
        let preparation = owner.preparation.get().context("original executor preparation")?;
        let items = history(&test).await?;
        assert_provenance_only_history(&items, &preparation.turn_id, client);
        let bindings = items.iter().filter_map(|item| match item {
            RolloutItem::TurnRecoveryRequestBinding(binding) if binding.turn_id == preparation.turn_id => Some(binding.clone()),
            _ => None,
        }).collect::<Vec<_>>();
        assert_eq!(bindings.len(), 1, "Core must have persisted its exact original recovery once");
        assert_eq!(bindings[0].fingerprint_sha256, preparation.fingerprint);
        // This independent fixture owner records the original Core-produced
        // binding from real storage; it does not invent a replacement receipt.
        assert!(owner.recovery.set(bindings[0].clone()).is_ok());
    }
    let original = owner.recovery.get().context("original Core recovery before checkpoint")?;
    let turn_id = original.turn_id.clone();
    let session = test.thread_store.open_native_checkpoint(checkpoint(thread_id, &turn_id), NativeCheckpointOpenMode::Inspect,
        Arc::new(FixtureCurrentness)).await?;
    assert_eq!(test.thread_store.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Missing);
    if input_written {
        assert_original_history(&history(&test).await?, &turn_id, client, None);
    } else {
        assert_provenance_only_history(&history(&test).await?, &turn_id, client);
    }
    assert!(!start.is_finished());
    assert_eq!((owner.prepared.load(Ordering::SeqCst), owner.effects.load(Ordering::SeqCst), queue.complete_attempts.load(Ordering::SeqCst)), (1, 0, 0));
    // Reuse the established fixture's 250ms lease; real expiry alone must not
    // dislodge the original process-lock owner while its runtime remains live.
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert!(queue.try_acquire_client_dispatch_lock(thread_id, client.clone(), digest.clone())?.is_none());
    assert_eq!(test.codex.suspend_turn_and_shutdown().await?, SuspendTurnOutcome::Suspended { turn_id: turn_id.clone() });
    let stopped_start = tokio::time::timeout(Duration::from_secs(10), start).await??;
    assert!(stopped_start.is_err(), "pre-checkpoint shutdown must leave admission uncertain: {stopped_start:?}");
    assert!(queue.try_acquire_client_dispatch_lock(thread_id, client.clone(), digest.clone())?.is_none(),
        "the uncertain guardian must retain its process fence until runtime exit");
    if input_written {
        assert_original_history(&history(&test).await?, &turn_id, client, None);
    } else {
        assert_provenance_only_history(&history(&test).await?, &turn_id, client);
    }
    assert_eq!(service.list(thread_id).await?.iter().map(|item| item.id.as_str()).collect::<Vec<_>>(), vec![item.id.as_str()]);
    assert!(server.received_requests().await.context("provider capture")?.iter().all(|request| !request.url.path().ends_with("/responses")));
    test.thread_manager.remove_thread(&thread_id).await;
    Ok(SuspendedOriginal { home: test.home.clone(), cwd: test.cwd.clone(), sqlite: test.config.sqlite.clone(),
        rollout: test.codex.rollout_path().context("retained rollout")?, thread_id, turn_id, item_id: item.id,
        input, digest, input_written, old_thread: Arc::downgrade(&test.codex), old_queue: Arc::downgrade(&queue),
        old_thread_store: Arc::downgrade(&test.thread_store) })
}

async fn resume_original(owner: Arc<ExecutionOwner>, original: SuspendedOriginal, mode: ResumeMode) -> anyhow::Result<()> {
    assert!(original.old_thread.upgrade().is_none(), "old Core/guardian must have stopped with its runtime");
    assert!(original.old_queue.upgrade().is_none(), "old QueueStore/guardian must have dropped before reopen");
    assert!(original.old_thread_store.upgrade().is_none(), "old ThreadStore writer must have dropped before reopen");
    let server = start_mock_server().await;
    let (builder, fixture, executor) = builder(owner.clone(), mode);
    let cwd = original.cwd.path().abs();
    let sqlite = original.sqlite.clone();
    let mut builder = builder.with_config(move |config| { config.cwd = cwd; config.sqlite = sqlite; });
    let test = builder.resume(&server, original.home.clone(), original.rollout.clone()).await?;
    assert_eq!(test.session_configured.thread_id, original.thread_id);
    let (service, queue) = install_queue(&test, &fixture, executor, false)?;
    let TurnInput::UserInput { client_id: Some(client), .. } = &original.input else { unreachable!() };
    let lock = queue.try_acquire_client_dispatch_lock(original.thread_id, client.clone(), original.digest.clone())?
        .context("runtime teardown did not release the original process lock")?;
    drop(lock);
    let rows = service.list(original.thread_id).await?;
    assert_eq!(rows.len(), 1);
    assert_eq!((&rows[0].id, &rows[0].input), (&original.item_id, &original.input));
    if original.input_written {
        assert_original_history(&history(&test).await?, &original.turn_id, client, None);
    } else {
        assert_provenance_only_history(&history(&test).await?, &original.turn_id, client);
    }
    let start = tokio::spawn({
        let service = service.clone(); let thread = test.codex.clone(); let id = original.item_id.clone();
        async move { service.start(&thread, Some(id), None).await }
    });
    if matches!(mode, ResumeMode::Original) {
        tokio::time::timeout(Duration::from_secs(10), fixture.checkpointed.notified()).await?;
        assert!(!start.is_finished());
        assert_eq!((owner.prepared.load(Ordering::SeqCst), owner.resumed.load(Ordering::SeqCst), owner.effects.load(Ordering::SeqCst)), (1, 1, 0));
        assert_eq!(queue.complete_attempts.load(Ordering::SeqCst), 0);
        assert_eq!(service.list(original.thread_id).await?[0].id, original.item_id);
        fixture.allow_confirmation.notify_one();
        assert_eq!(tokio::time::timeout(Duration::from_secs(10), start).await???,
            StartIfIdleSubmission::Started { turn_id: original.turn_id.clone() });
        let completed = wait_for_event_match(&test.codex, |event| match event {
            EventMsg::TurnComplete(event) => Some(event.turn_id.clone()), _ => None,
        }).await;
        assert_eq!(completed, original.turn_id);
        assert_eq!((owner.prepared.load(Ordering::SeqCst), owner.resumed.load(Ordering::SeqCst), owner.effects.load(Ordering::SeqCst),
            queue.complete_attempts.load(Ordering::SeqCst)), (1, 1, 1, 1));
        assert!(service.list(original.thread_id).await?.is_empty());
        assert_eq!(service.reconcile(original.thread_id, test.codex.rollout_path(), original.input.clone(), original.digest.clone(),
            QueueReconcileMode::ReconcileOnly).await?.outcome, QueueReconcileOutcome::Persisted { turn_id: original.turn_id.clone() });
    } else {
        let expected = if matches!(mode, ResumeMode::NoProof) { "this hosted executor cannot restore original preparation" }
            else { "hosted preparation changed its original fingerprint or correlation" };
        wait_for_event_match(&test.codex, |event| match event {
            EventMsg::Error(error) if error.message.contains(expected) => Some(()), _ => None,
        }).await;
        assert!(tokio::time::timeout(Duration::from_secs(10), start).await??.is_err());
        // Error delivery alone is not a durability or idle witness. This
        // original Core API flushes/scans the unfinished tail and rechecks its
        // idle epoch after the technical failure has released the turn fence.
        tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                if test.codex.recovery_epoch_if_idle(&original.turn_id).await.is_some() { break; }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        }).await?;
        assert_original_history(&history(&test).await?, &original.turn_id, client, None);
        assert_eq!((owner.prepared.load(Ordering::SeqCst), owner.resumed.load(Ordering::SeqCst), owner.effects.load(Ordering::SeqCst),
            queue.complete_attempts.load(Ordering::SeqCst)), (1, if matches!(mode, ResumeMode::ChangedFingerprint) { 1 } else { 0 }, 0, 0));
        assert_eq!(service.list(original.thread_id).await?[0].id, original.item_id);
        let session = test.thread_store.open_native_checkpoint(checkpoint(original.thread_id, &original.turn_id),
            NativeCheckpointOpenMode::Inspect, Arc::new(FixtureCurrentness)).await?;
        assert_eq!(test.thread_store.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Missing);
    }
    assert!(server.received_requests().await.context("provider capture")?.iter().all(|request| !request.url.path().ends_with("/responses")));
    test.codex.shutdown_and_wait().await?;
    let final_history = history(&test).await?;
    assert_original_history(&final_history, &original.turn_id, client, matches!(mode, ResumeMode::Original).then_some(true));
    if !original.input_written && matches!(mode, ResumeMode::Original) {
        assert_eq!(final_history.iter().filter(|item| is_user_response(item)).count(), 1,
            "same-turn restoration must append the absent original user response exactly once");
    }
    test.thread_manager.remove_thread(&original.thread_id).await;
    Ok(())
}

fn exercise_at(mode: ResumeMode, point: SuspendPoint) -> anyhow::Result<()> {
    let owner = Arc::new(ExecutionOwner::default());
    let first = tokio::runtime::Builder::new_multi_thread().worker_threads(2).enable_all().build()?;
    let original = first.block_on(suspend_original(owner.clone(), point))?;
    let home = original.home.clone();
    let cwd = original.cwd.clone();
    first.shutdown_timeout(Duration::from_secs(3));
    let second = tokio::runtime::Builder::new_multi_thread().worker_threads(2).enable_all().build()?;
    let result = second.block_on(resume_original(owner, original, mode));
    second.shutdown_timeout(Duration::from_secs(3));
    drop(home);
    drop(cwd);
    result
}

fn assert_provenance_only_history(items: &[RolloutItem], turn: &str, client: &str) {
    assert_original_history_with_input_count(items, turn, client, None, 0);
    assert_eq!(items.iter().filter(|item| matches!(item,
        RolloutItem::TurnContext(context) if context.turn_id.as_deref() == Some(turn))).count(), 1);
    assert_eq!(items.iter().filter(|item| matches!(item,
        RolloutItem::TurnRecoveryRequestBinding(binding) if binding.turn_id == turn)).count(), 1);
    assert_eq!(items.iter().filter(|item| is_user_response(item)).count(), 0,
        "the original user response must not have reached durable history");
    assert!(items.iter().all(|item| !matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemStarted(event)) if event.turn_id == turn
            && matches!(&event.item, TurnItem::UserMessage(_)))));
    assert!(items.iter().all(|item| !matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if event.turn_id == turn
            && matches!(&event.item, TurnItem::UserMessage(_)))));
}

fn exercise(mode: ResumeMode) -> anyhow::Result<()> {
    exercise_at(mode, SuspendPoint::BeforeCheckpoint)
}

#[test]
fn same_turn_preparation_restores_input_after_durable_provenance_before_user_append() -> anyhow::Result<()> {
    exercise_at(ResumeMode::Original, SuspendPoint::BeforeUserAppend)
}

#[test]
fn same_turn_preparation_resumes_after_real_runtime_owner_exit() -> anyhow::Result<()> { exercise(ResumeMode::Original) }

#[test]
fn same_turn_preparation_without_independent_executor_proof_stays_held() -> anyhow::Result<()> { exercise(ResumeMode::NoProof) }

#[test]
fn same_turn_preparation_with_changed_fingerprint_never_enters_effect() -> anyhow::Result<()> { exercise(ResumeMode::ChangedFingerprint) }
