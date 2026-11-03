//! Core continuation consumes only the originally installed queue's persisted
//! evidence. The execution fixture is synthetic; all lifecycle/storage are real.

use super::*;
use codex_core::hosted_turn::HostedTurnExecutor;
use codex_protocol::protocol::Op;
use codex_protocol::turn_input::RecoverTurnRequest;
use pretty_assertions::assert_eq;

#[path = "hosted_checkpoint_continuation_fixture.rs"]
mod fixture;
use fixture::{Case, Fixture, Host, Install, ObservationResult, CONTINUATION_CONFLICT, ORIGINAL_OBSERVATION_ERROR};

async fn history(test: &TestCodex) -> anyhow::Result<Vec<RolloutItem>> {
    let mut reader = open_rollout_line_reader(&test.codex.rollout_path().context("original rollout")?).await?;
    let mut items = Vec::new();
    while let Some(line) = reader.next_line().await? {
        items.push(serde_json::from_str::<RolloutLine>(&line)?.item);
    }
    Ok(items)
}

async fn held(test: &TestCodex, turn_id: &str) -> anyhow::Result<(u64, String)> {
    let event = tokio::time::timeout(Duration::from_secs(10), wait_for_event_match(&test.codex, |event| match event {
        EventMsg::Error(_) | EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_) => Some(event.clone()), _ => None,
    })).await?;
    let EventMsg::Error(error) = event else {
        anyhow::bail!("held original turn emitted a terminal event: {event:?}");
    };
    let epoch = tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if let Some(epoch) = test.codex.recovery_epoch_if_idle(turn_id).await { return epoch; }
            tokio::task::yield_now().await;
        }
    }).await.context("original held turn was not readable and idle")?;
    assert!(history(test).await?.iter().all(|item| !matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnAborted(_) | EventMsg::TurnComplete(_)))));
    Ok((epoch, error.message))
}

async fn exercise(case: Case) -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let home = Arc::new(tempfile::tempdir()?);
    let sqlite = SqliteConfig::new_for_testing(home.path().abs());
    let runtime = StateRuntime::init(sqlite.clone(), "test-provider".to_owned()).await?;
    let fixture = Fixture::new(case, runtime);
    let executor: Arc<dyn HostedTurnExecutor> = Arc::new(Host(fixture.clone()));
    let queue: Arc<dyn QueueStore> = fixture.queue.clone();
    let mut extensions = ExtensionRegistryBuilder::new();
    extensions.thread_lifecycle_contributor(Arc::new(Install { executor: executor.clone(), queue: queue.clone() }));
    let mut builder = test_codex().with_home(home).with_extensions(Arc::new(extensions.build()))
        .with_history_mode(ThreadHistoryMode::Paginated).with_config(move |config| {
            config.sqlite = sqlite;
            config.include_environment_context = false;
            let _ = config.features.enable(codex_features::Feature::HeptaTurnRecovery);
        });
    let test = builder.build_with_auto_env(&server).await?;
    let service = Arc::new(QueuedItemService::new(queue.clone(), Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink)).with_hosted_turn_executor(Some(executor)));
    let thread_id = test.session_configured.thread_id;
    let input = structured_user_input("one original checkpoint input");
    let TurnInput::UserInput { content, client_id: Some(client) } = &input else { anyhow::bail!("missing original client input"); };
    let digest = user_input_payload_sha256(content)?;
    let queued = service.reconcile(thread_id, test.codex.rollout_path(), input.clone(), digest.clone(), QueueReconcileMode::AllowIfAbsent).await?;
    let QueueReconcileOutcome::Queued { item, created: true } = queued.outcome else { anyhow::bail!("original input was not queued once"); };
    let StartIfIdleSubmission::Started { turn_id } = service.start(&test.codex, Some(item.id), None).await? else { anyhow::bail!("original turn was not started"); };
    let (epoch, _) = held(&test, &turn_id).await?;
    let original = fixture.original.get().context("original typed recovery")?.clone();
    let persisted = queue.observe_persisted_client_binding(thread_id, client.clone(), digest.clone()).await?
        .context("original queue completion is absent")?;
    assert_eq!(persisted.turn_id, turn_id);
    let queue_revision = queue.change_version().await?;
    assert!(service.list(thread_id).await?.is_empty());
    assert_eq!((fixture.prepared.load(Ordering::SeqCst), fixture.effects.load(Ordering::SeqCst)), (1, 0));

    assert_eq!(test.codex.recover_turn_if_idle(RecoverTurnRequest {
        turn_id: turn_id.clone(), expected_epoch: epoch, thread_settings: Default::default(), trace: None,
    }).await?, StartIfIdleSubmission::Started { turn_id: turn_id.clone() });
    match case {
        Case::Continue | Case::AfterObservation(ObservationResult::Pending | ObservationResult::Error | ObservationResult::Completed) => {
            let completed = tokio::time::timeout(Duration::from_secs(10), wait_for_event_match(&test.codex, |event| match event {
                EventMsg::TurnComplete(event) => Some(Some(event.turn_id.clone())),
                EventMsg::TurnAborted(_) | EventMsg::Error(_) => Some(None), _ => None,
            })).await?;
            assert_eq!(completed, Some(turn_id.clone()));
        }
        Case::Cancel => {
            tokio::time::timeout(Duration::from_secs(10), fixture.entered.notified()).await?;
            test.codex.submit(Op::Interrupt).await?;
            tokio::time::timeout(Duration::from_secs(10), wait_for_event_match(&test.codex, |event| match event {
                EventMsg::TurnAborted(_) => Some(()), _ => None,
            })).await?;
            let origin = fixture.origin.get().context("captured original continuation origin")?;
            assert!(origin.origin.validate(&origin.observation).is_err());
            let entry = fixture.entry.get().context("original continuation entry")?;
            assert!(entry.with_current(thread_id, &turn_id, || fixture.effects.fetch_add(1, Ordering::SeqCst)).is_err());
        }
        Case::AfterObservation(ObservationResult::Cancelled | ObservationResult::Aborted | ObservationResult::TokenCancelled) => {
            let aborted = tokio::time::timeout(Duration::from_secs(10), wait_for_event_match(&test.codex, |event| match event {
                EventMsg::TurnAborted(_) => Some(true),
                EventMsg::TurnComplete(_) | EventMsg::Error(_) => Some(false), _ => None,
            })).await?;
            assert!(aborted, "original observer cancellation must stay terminal");
        }
        Case::ChangedPlan | Case::ChangedObservation | Case::BindingDeleted | Case::OptOut
        | Case::AfterObservation(ObservationResult::Unavailable | ObservationResult::Conflict) => {
            let (_, error) = held(&test, &turn_id).await?;
            match case {
                Case::AfterObservation(ObservationResult::Unavailable) => {
                    assert!(error.contains(ORIGINAL_OBSERVATION_ERROR), "original error was replaced: {error}");
                }
                Case::AfterObservation(ObservationResult::Conflict) => {
                    assert!(error.contains(CONTINUATION_CONFLICT), "conflicting proof was ignored: {error}");
                    assert!(!error.contains(ORIGINAL_OBSERVATION_ERROR));
                }
                _ => {}
            }
        }
    }
    let (hook_calls, observer_calls, effects, completed, aborted) = match case {
        Case::Continue => (1, 0, 1, 1, 0),
        Case::ChangedPlan | Case::ChangedObservation | Case::BindingDeleted => (1, 0, 0, 0, 0),
        Case::Cancel => (1, 0, 0, 0, 1),
        Case::OptOut => (0, 1, 0, 0, 0),
        Case::AfterObservation(ObservationResult::Pending | ObservationResult::Error) => (2, 1, 1, 1, 0),
        Case::AfterObservation(ObservationResult::Unavailable | ObservationResult::Conflict) => (2, 1, 0, 0, 0),
        Case::AfterObservation(ObservationResult::Completed) => (1, 1, 0, 1, 0),
        Case::AfterObservation(ObservationResult::Cancelled | ObservationResult::Aborted | ObservationResult::TokenCancelled) => (1, 1, 0, 0, 1),
    };
    assert_eq!((fixture.prepared.load(Ordering::SeqCst), fixture.continued.load(Ordering::SeqCst),
        fixture.observed.load(Ordering::SeqCst), fixture.effects.load(Ordering::SeqCst)), (1, hook_calls, observer_calls, effects));
    assert_eq!(fixture.original.get(), Some(&original));
    if !matches!(case, Case::BindingDeleted) {
        assert_eq!(queue.observe_persisted_client_binding(thread_id, client.clone(), digest).await?, Some(persisted));
        assert_eq!(queue.change_version().await?, queue_revision, "continuation must never claim, requeue or complete again");
    }
    test.codex.flush_rollout().await?;
    let items = history(&test).await?;
    assert_eq!(items.iter().filter_map(|item| match item {
        RolloutItem::EventMsg(EventMsg::TurnStarted(event)) => Some(event.turn_id.as_str()), _ => None,
    }).collect::<HashSet<_>>(), HashSet::from([turn_id.as_str()]));
    assert_eq!(items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if event.turn_id == turn_id
            && matches!(&event.item, TurnItem::UserMessage(message) if message.client_id.as_deref() == Some(client.as_str())))).count(), 1);
    assert_eq!(items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnComplete(_)))).count(), completed);
    assert_eq!(items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnAborted(_)))).count(), aborted);
    let bindings = items.iter().filter_map(|item| match item {
        RolloutItem::TurnRecoveryRequestBinding(binding) if binding.turn_id == turn_id => Some(binding), _ => None,
    }).collect::<Vec<_>>();
    assert_eq!(bindings.len(), 2, "only the original Core typed successor may be appended");
    assert_eq!(bindings[0], &original);
    assert_eq!((bindings[1].generation, bindings[1].replay_applied_from_generation),
        (original.generation + 1, Some(original.generation)));
    assert!(server.received_requests().await.context("Core provider capture")?.iter()
        .all(|request| !request.url.path().ends_with("/responses")));
    test.codex.shutdown_and_wait().await?;
    Ok(())
}

#[tokio::test]
async fn checkpoint_continuation_uses_original_persisted_queue_without_dispatch() -> anyhow::Result<()> { exercise(Case::Continue).await }
#[tokio::test]
async fn checkpoint_continuation_changed_plan_stays_held_without_observer_fallback() -> anyhow::Result<()> { exercise(Case::ChangedPlan).await }
#[tokio::test]
async fn checkpoint_continuation_public_dto_cannot_replace_original_provenance() -> anyhow::Result<()> { exercise(Case::ChangedObservation).await }
#[tokio::test]
async fn checkpoint_continuation_rechecks_original_completion_before_final_entry() -> anyhow::Result<()> { exercise(Case::BindingDeleted).await }
#[tokio::test]
async fn checkpoint_continuation_original_cancel_revokes_retained_origin_and_entry() -> anyhow::Result<()> { exercise(Case::Cancel).await }
#[tokio::test]
async fn checkpoint_continuation_opt_out_preserves_observation_only_recovery() -> anyhow::Result<()> { exercise(Case::OptOut).await }

#[tokio::test]
async fn checkpoint_continuation_after_pending_observation_completes_in_the_same_call() -> anyhow::Result<()> {
    exercise(Case::AfterObservation(ObservationResult::Pending)).await
}
#[tokio::test]
async fn checkpoint_continuation_after_observer_error_completes_in_the_same_call() -> anyhow::Result<()> {
    exercise(Case::AfterObservation(ObservationResult::Error)).await
}
#[tokio::test]
async fn checkpoint_continuation_after_observation_checks_once_and_preserves_an_unavailable_error() -> anyhow::Result<()> {
    exercise(Case::AfterObservation(ObservationResult::Unavailable)).await
}
#[tokio::test]
async fn checkpoint_continuation_after_observation_conflict_stays_held_without_reobserving() -> anyhow::Result<()> {
    exercise(Case::AfterObservation(ObservationResult::Conflict)).await
}
#[tokio::test]
async fn checkpoint_continuation_observed_completion_does_not_reenter_execution() -> anyhow::Result<()> {
    exercise(Case::AfterObservation(ObservationResult::Completed)).await
}
#[tokio::test]
async fn checkpoint_continuation_observed_cancellation_does_not_reenter_execution() -> anyhow::Result<()> {
    for result in [ObservationResult::Cancelled, ObservationResult::Aborted, ObservationResult::TokenCancelled] {
        exercise(Case::AfterObservation(result)).await?;
    }
    Ok(())
}
