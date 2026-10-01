use super::*;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_fleet::AgentLifecycle;

async fn admitted_work(store: &AutomationStore) -> AutomationOccurrenceWork {
    let task = store
        .create_task(&AutomationTaskDraft::new(
            "019153a4-3088-7e03-a56a-9b1964f75ddd",
            "exact original prompt",
            AutomationSchedule::Once,
            100,
            1,
        ))
        .await
        .expect("task");
    let lease = store
        .claim_due(100, 1, 60_000)
        .await
        .expect("claim")
        .expect("lease");
    let occurrence = store
        .materialize_occurrence(&lease, 100)
        .await
        .expect("occurrence");
    store
        .prepare_occurrence_taskflow(&occurrence, &lease, 100, 60_000)
        .await
        .expect("TaskFlow intent");
    store
        .record_dispatch_uncertain(&lease, 101)
        .await
        .expect("armed dispatch");
    let occurrence = store
        .record_occurrence_admitted(
            &lease,
            &AutomationQueueReceipt {
                queued_submission_id: format!("queue:{}", lease.client_user_message_id),
                client_user_message_id: lease.client_user_message_id.clone(),
            },
            102,
        )
        .await
        .expect("admitted");
    AutomationOccurrenceWork {
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
    }
}

fn observed(
    work: &AutomationOccurrenceWork,
    outcome: QueueHistoricalOutcome,
) -> QueueHistoricalObservation {
    QueueHistoricalObservation {
        client_user_message_id: work.admission.client_user_message_id.clone(),
        payload_sha256: input_digest(&prompt_input(&work.admission.prompt)).expect("digest"),
        outcome,
    }
}

#[tokio::test]
async fn drained_historical_eof_is_indeterminate_and_exact_terminal_can_settle_it() {
    let (_temp, registry, state) = super::super::tests::fixture().await;
    let store = AutomationStore::open(&state.identity().layout)
        .await
        .expect("automation owner");
    let work = admitted_work(&store).await;
    registry
        .compare_and_transition(&state.identity().agent_id, 2, AgentLifecycle::Draining)
        .expect("ordinary drain");
    assert!(
        !state
            .automation_admission_ready()
            .expect("closed admission")
    );
    validate_observation_generation(&state).expect("historical owner remains current");
    let no_terminal = observed(
        &work,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-original".to_string(),
            terminal: None,
        },
    );
    settle(&store, &work, no_terminal, 103)
        .await
        .expect("classify unknown");
    let occurrence = store
        .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
        .await
        .unwrap()
        .unwrap();
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
    );
    settle(&store, &current_work, terminal, 104)
        .await
        .expect("settle real terminal");
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .unwrap()
            .unwrap()
            .state,
        AutomationOccurrenceState::Succeeded
    );
    assert!(!state.automation_admission_ready().unwrap());
}

#[tokio::test]
async fn drained_missing_keeps_uncertainty_and_mismatched_turn_cannot_complete() {
    let (_temp, _registry, state) = super::super::tests::fixture().await;
    let store = AutomationStore::open(&state.identity().layout)
        .await
        .expect("automation owner");
    let work = admitted_work(&store).await;
    settle(
        &store,
        &work,
        observed(&work, QueueHistoricalOutcome::Missing),
        103,
    )
    .await
    .expect("indeterminate absence");
    let occurrence = store
        .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
        .await
        .unwrap()
        .unwrap();
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
    );
    assert!(settle(&store, &current_work, wrong, 104,).await.is_err());
    assert_eq!(
        store
            .automation_occurrence(
                current_work.occurrence.task_id,
                current_work.occurrence.occurrence
            )
            .await
            .unwrap()
            .unwrap()
            .state,
        AutomationOccurrenceState::Indeterminate
    );
}

#[tokio::test]
async fn old_indeterminate_does_not_starve_a_later_drain_blocker() {
    let (_temp, _registry, state) = super::super::tests::fixture().await;
    let store = AutomationStore::open(&state.identity().layout)
        .await
        .unwrap();
    let older = admitted_work(&store).await;
    settle(
        &store,
        &older,
        observed(&older, QueueHistoricalOutcome::Missing),
        103,
    )
    .await
    .unwrap();
    let newer = admitted_work(&store).await;
    let selected = store
        .pending_drain_occurrence_work(1)
        .await
        .unwrap()
        .remove(0);
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
        ),
        104,
    )
    .await
    .unwrap();
    assert_eq!(
        store
            .automation_occurrence(newer.occurrence.task_id, newer.occurrence.occurrence)
            .await
            .unwrap()
            .unwrap()
            .state,
        AutomationOccurrenceState::Succeeded
    );
    assert_eq!(
        store
            .automation_occurrence(older.occurrence.task_id, older.occurrence.occurrence)
            .await
            .unwrap()
            .unwrap()
            .state,
        AutomationOccurrenceState::Indeterminate
    );
    assert_eq!(store.drain_blockers().await.unwrap(), 0);
}

#[tokio::test]
async fn drained_exact_terminal_recovers_the_expired_original_taskflow_lease() {
    let (_temp, registry, state) = super::super::tests::fixture().await;
    let store = AutomationStore::open(&state.identity().layout)
        .await
        .unwrap();
    let work = admitted_work(&store).await;
    let before = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        before.state,
        codex_hepta_automation::TaskFlowRunState::Running
    );
    registry
        .compare_and_transition(&state.identity().agent_id, 2, AgentLifecycle::Draining)
        .unwrap();
    validate_observation_generation(&state).unwrap();
    let terminal = observed(
        &work,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-expired".to_string(),
            terminal: Some(QueueHistoricalTerminal::Completed),
        },
    );
    settle(&store, &work, terminal, 60_101).await.unwrap();
    let after = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        after.state,
        codex_hepta_automation::TaskFlowRunState::Succeeded
    );
    assert_eq!(
        after.generation,
        before
            .generation
            .and_then(|generation| generation.checked_add(1))
    );
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .unwrap()
            .unwrap()
            .state,
        AutomationOccurrenceState::Succeeded
    );
    assert!(!state.automation_admission_ready().unwrap());
}

#[tokio::test]
async fn drained_unknown_or_wrong_turn_never_takes_an_expired_run_lease() {
    let (_temp, _registry, state) = super::super::tests::fixture().await;
    let store = AutomationStore::open(&state.identity().layout)
        .await
        .unwrap();
    let work = admitted_work(&store).await;
    let before = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await
        .unwrap()
        .unwrap();
    settle(
        &store,
        &work,
        observed(&work, QueueHistoricalOutcome::Unknown),
        60_101,
    )
    .await
    .unwrap();
    let after = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(after, before);
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .unwrap()
            .unwrap()
            .state,
        AutomationOccurrenceState::Indeterminate
    );
    let other = admitted_work(&store).await;
    store
        .record_occurrence_turn(
            other.occurrence.task_id,
            other.occurrence.occurrence,
            &other.occurrence.client_user_message_id,
            "turn-original",
            &input_digest(&prompt_input(&other.admission.prompt)).unwrap(),
            103,
        )
        .await
        .unwrap();
    let occurrence = store
        .automation_occurrence(other.occurrence.task_id, other.occurrence.occurrence)
        .await
        .unwrap()
        .unwrap();
    let other = AutomationOccurrenceWork {
        admission: other.admission,
        occurrence,
    };
    let before = store
        .taskflow_run(&other.occurrence.taskflow_run_id)
        .await
        .unwrap()
        .unwrap();
    let wrong = observed(
        &other,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-different".to_string(),
            terminal: Some(QueueHistoricalTerminal::Completed),
        },
    );
    assert!(settle(&store, &other, wrong, 60_101).await.is_err());
    assert_eq!(
        store
            .taskflow_run(&other.occurrence.taskflow_run_id)
            .await
            .unwrap()
            .unwrap(),
        before
    );
}

#[tokio::test]
async fn drain_replays_the_original_terminal_receipt_across_the_occurrence_crash_window() {
    let (_temp, registry, state) = super::super::tests::fixture().await;
    let store = AutomationStore::open(&state.identity().layout)
        .await
        .unwrap();
    let work = admitted_work(&store).await;
    store
        .ensure_admitted_taskflow_uncertainty(&work, 103)
        .await
        .unwrap();
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
        .await
        .unwrap();
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .unwrap()
            .unwrap()
            .state,
        AutomationOccurrenceState::Admitted
    );
    registry
        .compare_and_transition(&state.identity().agent_id, 2, AgentLifecycle::Draining)
        .unwrap();
    validate_observation_generation(&state).unwrap();
    let history = observed(
        &work,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-original".to_string(),
            terminal: Some(QueueHistoricalTerminal::Completed),
        },
    );
    settle(&store, &work, history, 105).await.unwrap();
    let occurrence = store
        .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(occurrence.state, AutomationOccurrenceState::Succeeded);
    assert_eq!(occurrence.terminal_receipt_digest, Some(original_receipt));
}

#[tokio::test]
async fn historical_recovery_rejects_a_conflicting_existing_terminal_receipt() {
    let (_temp, _registry, state) = super::super::tests::fixture().await;
    let store = AutomationStore::open(&state.identity().layout)
        .await
        .unwrap();
    let work = admitted_work(&store).await;
    store
        .ensure_admitted_taskflow_uncertainty(&work, 103)
        .await
        .unwrap();
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
        .await
        .unwrap();
    let before = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await
        .unwrap()
        .unwrap();
    let conflicting = observed(
        &work,
        QueueHistoricalOutcome::Persisted {
            turn_id: "turn-original".to_string(),
            terminal: Some(QueueHistoricalTerminal::Failed),
        },
    );
    assert!(settle(&store, &work, conflicting, 60_101).await.is_err());
    assert_eq!(
        store
            .taskflow_run(&work.occurrence.taskflow_run_id)
            .await
            .unwrap()
            .unwrap(),
        before
    );
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .unwrap()
            .unwrap()
            .state,
        AutomationOccurrenceState::Running
    );
}

#[tokio::test]
async fn historical_recovery_finishes_a_claimed_projection_without_taking_a_live_lease() {
    let (_temp, _registry, state) = super::super::tests::fixture().await;
    let store = AutomationStore::open(&state.identity().layout)
        .await
        .unwrap();
    let work = admitted_work(&store).await;
    store
        .ensure_admitted_taskflow_uncertainty(&work, 60_101)
        .await
        .unwrap();
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
        .await
        .unwrap()
        .unwrap();
    let generation = run.generation.unwrap().checked_add(1).unwrap();
    let fence = codex_hepta_automation::TaskFlowFence {
        owner_agent_id: state.identity().agent_id.clone(),
        owner_id: run.owner_id.unwrap(),
        owner_epoch: generation,
        generation,
        fencing_token: "recovery-before-quarantine-crash".to_string(),
    };
    let claimed = store
        .claim_taskflow_run(&work.occurrence.taskflow_run_id, &fence, 60_102, 30_000)
        .await
        .unwrap();
    let canonical = store
        .reconcile_occurrence_taskflow_historical_terminal(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &Sha256Digest::for_bytes(b"different readonly observation"),
            60_103,
            30_000,
        )
        .await
        .unwrap();
    assert_eq!(canonical, receipt);
    let settled = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(settled.generation, claimed.generation);
    assert_eq!(settled.owner_epoch, claimed.owner_epoch);
    assert_eq!(
        settled.state,
        codex_hepta_automation::TaskFlowRunState::Succeeded
    );
}
