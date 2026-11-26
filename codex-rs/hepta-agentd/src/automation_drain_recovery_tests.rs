type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

use super::*;
use codex_hepta_agent_components::automation::AutomationSchedule;
use codex_hepta_agent_components::automation::AutomationTaskDraft;
use codex_hepta_agent_components::fleet::AgentLifecycle;

async fn admitted_work(store: &AutomationStore) -> TestResult<AutomationOccurrenceWork> {
    let task = store
        .create_task(&AutomationTaskDraft::new(
            "019153a4-3088-7e03-a56a-9b1964f75ddd",
            "exact original prompt",
            AutomationSchedule::Once,
            100,
            1,
        ))
        .await?;
    let lease = store
        .claim_due(100, 1, 60_000)
        .await?
        .ok_or("original automation lease missing")?;
    let occurrence = store.materialize_occurrence(&lease, 100).await?;
    store
        .prepare_occurrence_taskflow(&occurrence, &lease, 100, 60_000)
        .await?;
    store.record_dispatch_uncertain(&lease, 101).await?;
    let occurrence = store
        .record_occurrence_admitted(
            &lease,
            &AutomationQueueReceipt {
                queued_submission_id: format!("queue:{}", lease.client_user_message_id),
                client_user_message_id: lease.client_user_message_id.clone(),
            },
            102,
        )
        .await?;
    Ok(AutomationOccurrenceWork {
        admission: AutomationAdmission {
            agent_id: task.owner_agent_id,
            task_id: task.task_id,
            occurrence: occurrence.occurrence,
            scheduled_for_ms: occurrence.scheduled_for_ms,
            thread_id: task.thread_id,
            prompt: task.prompt,
            client_user_message_id: occurrence.client_user_message_id.clone(),
        },
        occurrence,
    })
}

async fn historical_claims(
    store: &AutomationStore,
    run_id: &str,
) -> TestResult<Vec<(String, i64, i64, String, i64)>> {
    let sqlite = codex_state::SqliteConfig::from_sqlite_home(
        codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
            store
                .path()
                .parent()
                .ok_or("automation owner parent missing")?,
        )?,
    );
    let pool = sqlite.open_read_only_pool(store.path()).await?;
    let claims = sqlx::query_as(
        "SELECT owner_id, owner_epoch, generation, fencing_token, recorded_at_ms
         FROM taskflow_events WHERE owner_agent_id=? AND run_id=?
           AND transition='lease_claimed' ORDER BY event_seq",
    )
    .bind(store.owner_agent_id().as_str())
    .bind(run_id)
    .fetch_all(&pool)
    .await?;
    pool.close().await;
    Ok(claims)
}

fn observed(
    work: &AutomationOccurrenceWork,
    outcome: QueueHistoricalOutcome,
) -> TestResult<QueueHistoricalObservation> {
    Ok(QueueHistoricalObservation {
        client_user_message_id: work.admission.client_user_message_id.clone(),
        payload_sha256: input_digest(&prompt_input(&work.admission.prompt))?,
        outcome,
    })
}

#[tokio::test]
async fn drained_historical_eof_is_indeterminate_and_exact_terminal_can_settle_it() -> TestResult {
    let (_temp, registry, state) = super::super::tests::fixture().await?;
    let store = AutomationStore::open(&state.identity().layout).await?;
    let work = admitted_work(&store).await?;
    registry.compare_and_transition(&state.identity().agent_id, 2, AgentLifecycle::Draining)?;
    assert!(!state.automation_admission_ready()?);
    validate_observation_generation(&state)?;
    let no_terminal = observed(
        &work,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-original".to_string(),
            terminal: None,
        },
    )?;
    settle(&store, &work, no_terminal, 103).await?;
    let occurrence = store
        .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
        .await?
        .ok_or("original durable record missing")?;
    assert_eq!(occurrence.state, AutomationOccurrenceState::Indeterminate);
    assert_eq!(occurrence.turn_id.as_deref(), Some("turn-original"));
    let current_work = AutomationOccurrenceWork {
        admission: work.admission.clone(),
        occurrence,
    };
    let terminal = observed(
        &current_work,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-original".to_string(),
            terminal: Some(QueueHistoricalTerminal::Completed),
        },
    )?;
    settle(&store, &current_work, terminal, 104).await?;
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await?
            .ok_or("original durable record missing")?
            .state,
        AutomationOccurrenceState::Succeeded
    );
    assert!(!state.automation_admission_ready()?);
    Ok(())
}

#[tokio::test]
async fn drained_missing_keeps_uncertainty_and_mismatched_turn_cannot_complete() -> TestResult {
    let (_temp, _registry, state) = super::super::tests::fixture().await?;
    let store = AutomationStore::open(&state.identity().layout).await?;
    let work = admitted_work(&store).await?;
    settle(
        &store,
        &work,
        observed(&work, QueueHistoricalOutcome::Missing)?,
        103,
    )
    .await?;
    let occurrence = store
        .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
        .await?
        .ok_or("original durable record missing")?;
    assert_eq!(occurrence.state, AutomationOccurrenceState::Indeterminate);
    let mut current_work = AutomationOccurrenceWork {
        admission: work.admission,
        occurrence,
    };
    current_work.occurrence.turn_id = Some("turn-original".to_string());
    let wrong = observed(
        &current_work,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-other".to_string(),
            terminal: Some(QueueHistoricalTerminal::Completed),
        },
    )?;
    assert!(settle(&store, &current_work, wrong, 104,).await.is_err());
    assert_eq!(
        store
            .automation_occurrence(
                current_work.occurrence.task_id,
                current_work.occurrence.occurrence
            )
            .await?
            .ok_or("original durable record missing")?
            .state,
        AutomationOccurrenceState::Indeterminate
    );
    Ok(())
}

#[tokio::test]
async fn old_indeterminate_does_not_starve_a_later_drain_blocker() -> TestResult {
    let (_temp, _registry, state) = super::super::tests::fixture().await?;
    let store = AutomationStore::open(&state.identity().layout).await?;
    let older = admitted_work(&store).await?;
    settle(
        &store,
        &older,
        observed(&older, QueueHistoricalOutcome::Missing)?,
        103,
    )
    .await?;
    let newer = admitted_work(&store).await?;
    let selected = store.pending_drain_occurrence_work(1).await?.remove(0);
    assert_eq!(selected.occurrence.task_id, newer.occurrence.task_id);
    settle(
        &store,
        &selected,
        observed(
            &selected,
            QueueHistoricalOutcome::Persisted {
                turn_id: "turn-newer".to_string(),
                terminal: Some(QueueHistoricalTerminal::Completed),
            },
        )?,
        104,
    )
    .await?;
    assert_eq!(
        store
            .automation_occurrence(newer.occurrence.task_id, newer.occurrence.occurrence)
            .await?
            .ok_or("original durable record missing")?
            .state,
        AutomationOccurrenceState::Succeeded
    );
    assert_eq!(
        store
            .automation_occurrence(older.occurrence.task_id, older.occurrence.occurrence)
            .await?
            .ok_or("original durable record missing")?
            .state,
        AutomationOccurrenceState::Indeterminate
    );
    assert_eq!(store.drain_blockers().await?, 0);
    Ok(())
}

#[tokio::test]
async fn drained_exact_terminal_recovers_the_expired_original_taskflow_lease() -> TestResult {
    let (_temp, registry, state) = super::super::tests::fixture().await?;
    let store = AutomationStore::open(&state.identity().layout).await?;
    let work = admitted_work(&store).await?;
    let before = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await?
        .ok_or("original durable record missing")?;
    assert_eq!(
        before.state,
        codex_hepta_agent_components::automation::TaskFlowRunState::Running
    );
    registry.compare_and_transition(&state.identity().agent_id, 2, AgentLifecycle::Draining)?;
    validate_observation_generation(&state)?;
    let terminal = observed(
        &work,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-expired".to_string(),
            terminal: Some(QueueHistoricalTerminal::Completed),
        },
    )?;
    settle(&store, &work, terminal, 60_101).await?;
    let after = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await?
        .ok_or("original durable record missing")?;
    assert_eq!(
        after.state,
        codex_hepta_agent_components::automation::TaskFlowRunState::Succeeded
    );
    assert_eq!(
        (
            after.owner_id,
            after.owner_epoch,
            after.generation,
            after.fencing_token,
            after.lease_expires_at_ms
        ),
        (None, None, None, None, None),
    );
    let generation = before
        .generation
        .ok_or("original run generation missing")?
        .checked_add(1)
        .ok_or("recovery generation overflow")?;
    let claims = historical_claims(&store, &work.occurrence.taskflow_run_id).await?;
    assert_eq!(claims.len(), 2);
    let mut token_bytes = b"hepta.automation.taskflow.recovery-fence.v1\0".to_vec();
    token_bytes.extend_from_slice(work.occurrence.occurrence_id.as_bytes());
    token_bytes.extend_from_slice(&generation.to_be_bytes());
    assert_eq!(
        claims.last().ok_or("recovery claim missing")?,
        &(
            format!("automation.scheduler:{}", work.occurrence.task_id),
            i64::try_from(generation)?,
            i64::try_from(generation)?,
            Sha256Digest::for_bytes(&token_bytes).as_str().to_string(),
            60_101
        ),
    );
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await?
            .ok_or("original durable record missing")?
            .state,
        AutomationOccurrenceState::Succeeded
    );
    assert!(!state.automation_admission_ready()?);
    Ok(())
}

#[tokio::test]
async fn drained_unknown_or_wrong_turn_never_takes_an_expired_run_lease() -> TestResult {
    let (_temp, _registry, state) = super::super::tests::fixture().await?;
    let store = AutomationStore::open(&state.identity().layout).await?;
    let work = admitted_work(&store).await?;
    let before = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await?
        .ok_or("original durable record missing")?;
    settle(
        &store,
        &work,
        observed(&work, QueueHistoricalOutcome::Unknown)?,
        60_101,
    )
    .await?;
    let after = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await?
        .ok_or("original durable record missing")?;
    assert_eq!(after, before);
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await?
            .ok_or("original durable record missing")?
            .state,
        AutomationOccurrenceState::Indeterminate
    );
    let other = admitted_work(&store).await?;
    store
        .record_occurrence_turn(
            other.occurrence.task_id,
            other.occurrence.occurrence,
            &other.occurrence.client_user_message_id,
            "turn-original",
            &input_digest(&prompt_input(&other.admission.prompt))?,
            103,
        )
        .await?;
    let occurrence = store
        .automation_occurrence(other.occurrence.task_id, other.occurrence.occurrence)
        .await?
        .ok_or("original durable record missing")?;
    let other = AutomationOccurrenceWork {
        admission: other.admission,
        occurrence,
    };
    let before = store
        .taskflow_run(&other.occurrence.taskflow_run_id)
        .await?
        .ok_or("original durable record missing")?;
    let wrong = observed(
        &other,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-different".to_string(),
            terminal: Some(QueueHistoricalTerminal::Completed),
        },
    )?;
    assert!(settle(&store, &other, wrong, 60_101).await.is_err());
    assert_eq!(
        store
            .taskflow_run(&other.occurrence.taskflow_run_id)
            .await?
            .ok_or("original durable record missing")?,
        before
    );
    Ok(())
}

#[tokio::test]
async fn drain_replays_the_original_terminal_receipt_across_the_occurrence_crash_window()
-> TestResult {
    let (_temp, registry, state) = super::super::tests::fixture().await?;
    let store = AutomationStore::open(&state.identity().layout).await?;
    let work = admitted_work(&store).await?;
    store
        .ensure_admitted_taskflow_uncertainty(&work, 103)
        .await?;
    let original_receipt = Sha256Digest::for_bytes(b"original Running RPC terminal observation");
    store
        .reconcile_occurrence_taskflow_terminal_with_recovery(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &original_receipt,
            104,
            1,
            30_000,
        )
        .await?;
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await?
            .ok_or("original durable record missing")?
            .state,
        AutomationOccurrenceState::Admitted
    );
    registry.compare_and_transition(&state.identity().agent_id, 2, AgentLifecycle::Draining)?;
    validate_observation_generation(&state)?;
    let history = observed(
        &work,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-original".to_string(),
            terminal: Some(QueueHistoricalTerminal::Completed),
        },
    )?;
    settle(&store, &work, history, 105).await?;
    let occurrence = store
        .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
        .await?
        .ok_or("original durable record missing")?;
    assert_eq!(occurrence.state, AutomationOccurrenceState::Succeeded);
    assert_eq!(occurrence.terminal_receipt_digest, Some(original_receipt));
    Ok(())
}

#[tokio::test]
async fn historical_recovery_rejects_a_conflicting_existing_terminal_receipt() -> TestResult {
    let (_temp, _registry, state) = super::super::tests::fixture().await?;
    let store = AutomationStore::open(&state.identity().layout).await?;
    let work = admitted_work(&store).await?;
    store
        .ensure_admitted_taskflow_uncertainty(&work, 103)
        .await?;
    let receipt = Sha256Digest::for_bytes(b"original terminal receipt");
    store
        .reconcile_occurrence_taskflow_terminal_with_recovery(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &receipt,
            104,
            1,
            30_000,
        )
        .await?;
    let before = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await?
        .ok_or("original durable record missing")?;
    let conflicting = observed(
        &work,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-original".to_string(),
            terminal: Some(QueueHistoricalTerminal::Failed),
        },
    )?;
    assert!(settle(&store, &work, conflicting, 60_101).await.is_err());
    assert_eq!(
        store
            .taskflow_run(&work.occurrence.taskflow_run_id)
            .await?
            .ok_or("original durable record missing")?,
        before
    );
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await?
            .ok_or("original durable record missing")?
            .state,
        AutomationOccurrenceState::Running
    );
    Ok(())
}

#[tokio::test]
async fn historical_recovery_finishes_a_claimed_projection_without_taking_a_live_lease()
-> TestResult {
    let (_temp, _registry, state) = super::super::tests::fixture().await?;
    let store = AutomationStore::open(&state.identity().layout).await?;
    let work = admitted_work(&store).await?;
    store
        .ensure_admitted_taskflow_uncertainty(&work, 60_101)
        .await?;
    let receipt = Sha256Digest::for_bytes(b"exact terminal before projection recovery");
    assert!(
        store
            .reconcile_occurrence_taskflow_terminal(
                &work,
                AutomationOccurrenceTerminalState::Succeeded,
                &receipt,
                60_101
            )
            .await
            .is_err()
    );
    let run = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await?
        .ok_or("original durable record missing")?;
    let generation = run
        .generation
        .ok_or("original run generation missing")?
        .checked_add(1)
        .ok_or("recovery generation overflow")?;
    let fence = codex_hepta_agent_components::automation::TaskFlowFence {
        owner_agent_id: state.identity().agent_id.clone(),
        owner_id: run.owner_id.ok_or("original run owner missing")?,
        owner_epoch: generation,
        generation,
        fencing_token: "recovery-before-quarantine-crash".to_string(),
    };
    let claimed = store
        .claim_taskflow_run(&work.occurrence.taskflow_run_id, &fence, 60_102, 30_000)
        .await?;
    let claims_before = historical_claims(&store, &work.occurrence.taskflow_run_id).await?;
    assert_eq!(
        claims_before
            .last()
            .ok_or("claimed recovery history missing")?,
        &(
            fence.owner_id.clone(),
            i64::try_from(fence.owner_epoch)?,
            i64::try_from(fence.generation)?,
            fence.fencing_token.clone(),
            60_102
        )
    );
    let canonical = store
        .reconcile_occurrence_taskflow_historical_terminal(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &Sha256Digest::for_bytes(b"different readonly observation"),
            60_103,
            30_000,
        )
        .await?;
    assert_eq!(canonical, receipt);
    let settled = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await?
        .ok_or("original durable record missing")?;
    assert_eq!(
        (
            settled.owner_id,
            settled.owner_epoch,
            settled.generation,
            settled.fencing_token,
            settled.lease_expires_at_ms
        ),
        (None, None, None, None, None),
    );
    assert_eq!(
        historical_claims(&store, &work.occurrence.taskflow_run_id).await?,
        claims_before
    );
    assert_eq!(
        settled.revision,
        claimed
            .revision
            .checked_add(2)
            .ok_or("terminal revision overflow")?
    );
    assert_eq!(
        settled.state,
        codex_hepta_agent_components::automation::TaskFlowRunState::Succeeded
    );
    Ok(())
}
