//! Original Core and QueueStore must preserve an unfinished hosted tail when
//! another client input arrives. The existing FixtureHost is synthetic: its
//! effect counter verifies this Core/queue contract, not a production grant.

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use codex_extension_api::ThreadIdleCause;
use codex_history::RolloutLine;
use codex_protocol::items::TurnItem;
use codex_protocol::turn_input::SuspendTurnOutcome;

async fn history(test: &TestCodex) -> anyhow::Result<Vec<RolloutItem>> {
    let mut reader = super::super::open_rollout_line_reader(
        &test.codex.rollout_path().context("original rollout")?).await?;
    let mut items = Vec::new();
    while let Some(line) = reader.next_line().await? {
        items.push(serde_json::from_str::<RolloutLine>(&line)?.item);
    }
    Ok(items)
}

// Error notification alone precedes final cleanup. The public original Core
// witness below flushes and scans the actual tail, then verifies idle/epoch.
pub(super) async fn held(test: &TestCodex, turn: &str) -> anyhow::Result<u64> {
    let event = tokio::time::timeout(Duration::from_secs(10), wait_for_event_match(&test.codex, |event| match event {
        EventMsg::Error(_) | EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_) => Some(event.clone()),
        _ => None,
    })).await.context("original hosted technical outcome was not reported")?;
    let EventMsg::Error(error) = event else {
        anyhow::bail!("technical held outcome invented a terminal event: {event:?}");
    };
    anyhow::ensure!(!error.message.is_empty(), "held result omitted its diagnostic");
    let epoch = idle_recovery_epoch(test, turn).await?;
    let history = history(test).await?;
    assert!(history.iter().any(|item| matches!(item,
        RolloutItem::TurnRecoveryRequestBinding(binding) if binding.turn_id == turn)));
    assert!(!history.iter().any(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnAborted(_) | EventMsg::TurnComplete(_)))),
        "unfinished hosted work must not be relabelled as cancelled/completed");
    Ok(epoch)
}

fn counts(state: &FixtureState) -> (usize, usize, usize) {
    (state.prepared.load(Ordering::SeqCst), state.effects.load(Ordering::SeqCst), state.recovered.load(Ordering::SeqCst))
}

async fn recover(test: &TestCodex, turn: &str) -> anyhow::Result<()> {
    let epoch = idle_recovery_epoch(test, turn).await?;
    assert_eq!(test.codex.recover_turn_if_idle(RecoverTurnRequest {
        turn_id: turn.to_owned(), expected_epoch: epoch, thread_settings: Default::default(), trace: None,
    }).await?, StartIfIdleSubmission::Started { turn_id: turn.to_owned() });
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn held_original_turn_blocks_next_queue_input_until_original_observer_finishes() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let state = Arc::new(FixtureState::default());
    state.pending.store(true, Ordering::SeqCst);
    state.fail_recovery_once.store(true, Ordering::SeqCst);
    state.allow_checkpoint.notify_one();
    let (mut builder, executor) = fixture_builder(&state);
    let test = builder.build_with_auto_env(&server).await?;
    let service = install_queue(&test, &state, executor)?;
    let thread_id = test.session_configured.thread_id;
    let (first_id, first_input, first_digest) = queue_input(&test, &service).await?;
    let StartIfIdleSubmission::Started { turn_id } = service.start(&test.codex, Some(first_id), None).await? else {
        anyhow::bail!("first original queue input did not start");
    };
    tokio::time::timeout(Duration::from_secs(10), state.entered.notified()).await?;
    held(&test, &turn_id).await?;
    assert_eq!(counts(&state), (1, 1, 0));
    assert_eq!(service.reconcile(thread_id, test.codex.rollout_path(), first_input.clone(), first_digest.clone(),
        QueueReconcileMode::ReconcileOnly).await?.outcome, QueueReconcileOutcome::Persisted { turn_id: turn_id.clone() });
    assert!(service.list(thread_id).await?.is_empty());

    // First admission has completed its original queue claim and Core is now
    // positively idle/readable. The second row is created through that same
    // QueueStore only after that witness; a temporary task fence cannot pass.
    let second_client = "second-client-after-held".to_owned();
    let mut second_input = super::super::structured_user_input("a distinct next queued input");
    let TurnInput::UserInput { client_id, content } = &mut second_input else { unreachable!() };
    *client_id = Some(second_client.clone());
    let second_digest = user_input_payload_sha256(content)?;
    let second = service.reconcile(thread_id, test.codex.rollout_path(), second_input.clone(), second_digest.clone(),
        QueueReconcileMode::AllowIfAbsent).await?;
    let QueueReconcileOutcome::Queued { item: second, created: true } = second.outcome else {
        anyhow::bail!("the distinct second input was not queued once");
    };
    let original_binding = state.original_recovery.get().context("first original typed binding")?.clone();

    // Exercise both PendingObservation and a subsequent technical observer
    // error. Neither may allow a new logical turn over the unfinished tail.
    for recovered in [0, 1] {
        idle_recovery_epoch(&test, &turn_id).await?;
        let before = history(&test).await?;
        tokio::time::timeout(Duration::from_secs(10), super::super::emit_idle_with_cause(
            &service, thread_id, ThreadIdleCause::Failed)).await.context("original Failed idle dispatch blocked")?;
        assert_eq!(tokio::time::timeout(Duration::from_secs(10),
            service.start(&test.codex, Some(second.id.clone()), None)).await??,
            StartIfIdleSubmission::NotSubmitted { reason: NotSubmittedReason::RecoveryStateChanged });
        assert_eq!(counts(&state), (1, 1, recovered));
        let rows = service.list(thread_id).await?;
        assert_eq!(rows.len(), 1);
        assert_eq!((&rows[0].id, &rows[0].input), (&second.id, &second_input));
        // A definite NotSubmitted releases the existing dispatch lease/lock;
        // it must not hide this refusal behind an uncertain guardian instead.
        let original_queue = state.queue.get().context("original queue owner")?;
        let lock = original_queue.try_acquire_client_dispatch_lock(thread_id, second_client.clone(), second_digest.clone())?
            .context("declined second admission retained its process lock")?;
        drop(lock);
        assert!(test.codex.recovery_epoch_if_idle(&turn_id).await.is_some());
        assert_eq!(serde_json::to_value(history(&test).await?)?, serde_json::to_value(before)?,
            "rejected second input changed the first turn history");
        assert_eq!(state.original_recovery.get(), Some(&original_binding));
        assert_eq!(service.reconcile(thread_id, test.codex.rollout_path(), first_input.clone(), first_digest.clone(),
            QueueReconcileMode::ReconcileOnly).await?.outcome, QueueReconcileOutcome::Persisted { turn_id: turn_id.clone() });
        if recovered == 0 {
            recover(&test, &turn_id).await?;
            held(&test, &turn_id).await?;
            assert_eq!(counts(&state), (1, 1, 1));
        }
    }

    recover(&test, &turn_id).await?;
    let completed = tokio::time::timeout(Duration::from_secs(10), wait_for_event_match(&test.codex, |event| match event {
        EventMsg::TurnComplete(event) => Some(Some(event.turn_id.clone())),
        EventMsg::Error(_) | EventMsg::TurnAborted(_) => Some(None), _ => None,
    })).await?;
    assert_eq!(completed, Some(turn_id.clone()));
    assert_eq!(counts(&state), (1, 1, 2));
    test.codex.flush_rollout().await?;
    let items = history(&test).await?;
    assert_eq!(items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnComplete(event)) if event.turn_id == turn_id)).count(), 1);
    assert!(!items.iter().any(|item| matches!(item, RolloutItem::EventMsg(EventMsg::TurnAborted(_)))));
    assert_eq!(items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if event.turn_id == turn_id
            && matches!(&event.item, TurnItem::UserMessage(_)))).count(), 1);
    assert_eq!(service.list(thread_id).await?.iter().map(|item| item.id.clone()).collect::<Vec<_>>(), vec![second.id.clone()]);

    // Completion releases the history gate: the distinct queued input can now
    // enter its own normal prepare. Suspend it at the fixture's existing
    // pre-checkpoint barrier; this one-turn FixtureHost is not a second owner.
    let next = tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            let mut attempt = tokio::spawn({
                let service = Arc::clone(&service); let thread = Arc::clone(&test.codex); let id = second.id.clone();
                async move { service.start(&thread, Some(id), None).await }
            });
            tokio::select! {
                () = state.entered.notified() => return Ok::<_, anyhow::Error>(attempt),
                result = &mut attempt => match result?? {
                    // TurnComplete notification may precede the final fence
                    // release. Retrying this definite refusal retains the
                    // original queue row; it never manufactures another turn.
                    StartIfIdleSubmission::NotSubmitted { reason: NotSubmittedReason::NotIdle
                        | NotSubmittedReason::RecoveryStateChanged } => {
                        tokio::time::sleep(Duration::from_millis(10)).await;
                    }
                    other => anyhow::bail!("second admission bypassed its original checkpoint barrier: {other:?}"),
                }
            }
        }
    }).await.context("original completion did not release the next queue input")??;
    assert!(!next.is_finished());
    assert_eq!(counts(&state), (2, 1, 2));
    let second_turn = tokio::time::timeout(Duration::from_secs(10), wait_for_event_match(&test.codex, |event| match event {
        EventMsg::TurnStarted(event) => Some(event.turn_id.clone()), _ => None,
    })).await?;
    assert_ne!(second_turn, turn_id);
    assert_eq!(test.codex.suspend_turn_and_shutdown().await?, SuspendTurnOutcome::Suspended { turn_id: second_turn });
    assert!(tokio::time::timeout(Duration::from_secs(10), next).await??.is_err(),
        "second input must remain uncertain until its original checkpoint exists");
    assert_eq!(counts(&state), (2, 1, 2));
    assert!(server.received_requests().await.context("Core provider capture")?.iter()
        .all(|request| !request.url.path().ends_with("/responses")), "Core must not fall back to its model sampler");
    Ok(())
}
