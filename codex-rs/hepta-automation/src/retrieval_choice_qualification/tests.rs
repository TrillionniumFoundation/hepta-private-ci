use super::*;

fn owner() -> Result<AgentId, codex_hepta_contracts::AgentIdParseError> {
    AgentId::parse("00000000-0000-4000-8000-000000000119")
}

#[tokio::test]
async fn bootstrap_uses_real_history_without_step_or_choice_rows() {
    let root = FixtureRoot::new_synthetic(owner().unwrap()).await.unwrap();
    let connection = root.connection().await.unwrap();
    let run = connection.bootstrap_fixed_activity().await.unwrap();
    let replay = connection
        .store
        .replay_taskflow_structural(RUN_ID)
        .await
        .unwrap();
    assert_eq!(replay.run_id, run.run_id);
    assert_eq!(replay.revision, run.revision);
    assert_eq!(replay.state, run.state);
    assert_eq!(replay.current_node, run.current_node);
    let transitions: Vec<String> = sqlx::query_scalar(
        "SELECT transition FROM taskflow_events WHERE owner_agent_id = ? AND run_id = ?
         ORDER BY event_seq",
    )
    .bind(owner().unwrap().as_str())
    .bind(RUN_ID)
    .fetch_all(connection.store.taskflow_pool())
    .await
    .unwrap();
    assert_eq!(transitions, ["run_created", "lease_claimed", "started"]);
    assert_eq!(replay.event_count, transitions.len() as u64);
    let steps: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_step_outbox")
        .fetch_one(connection.store.taskflow_pool())
        .await
        .unwrap();
    assert_eq!(steps, 0);
    assert!(connection.bootstrap_fixed_activity().await.is_err());
    assert_eq!(
        connection.store.taskflow_run(RUN_ID).await.unwrap(),
        Some(run)
    );
    connection.close().await;
}

#[tokio::test]
async fn explicit_close_and_reopen_preserve_owner_history_and_clock_capability() {
    let root = FixtureRoot::new_synthetic(owner().unwrap()).await.unwrap();
    let first = root.connection().await.unwrap();
    let run = first.bootstrap_fixed_activity().await.unwrap();
    root.capability.advance_clock(1_100).unwrap();
    assert!(root.capability.advance_clock(1_099).is_err());
    let second = root.connection().await.unwrap();
    assert!(Arc::ptr_eq(&first.capability, &second.capability));
    first.close().await;
    assert_eq!(second.capability.clock.load(Ordering::SeqCst), 1_100);
    assert_eq!(
        second.store.taskflow_run(RUN_ID).await.unwrap(),
        Some(run.clone())
    );
    second.close().await;
    let reopened = root.connection().await.unwrap();
    assert_eq!(
        reopened.store.taskflow_run(RUN_ID).await.unwrap(),
        Some(run)
    );
    let path = root.capability.root.clone();
    drop(root);
    assert!(
        path.exists(),
        "connection must retain its private root capability"
    );
    reopened.close().await;
    assert!(
        !path.exists(),
        "explicit close waited for pool shutdown before root removal"
    );
}

#[tokio::test]
async fn ordinary_open_rejects_marker_and_markerless_qualified_database() {
    let root = FixtureRoot::new_synthetic(owner().unwrap()).await.unwrap();
    let connection = root.connection().await.unwrap();
    let run = connection.bootstrap_fixed_activity().await.unwrap();
    assert!(
        AutomationStore::open_root(root.capability.root.clone(), owner().unwrap())
            .await
            .is_err()
    );
    std::fs::remove_file(root.capability.root.join(MARKER)).unwrap();
    assert!(
        AutomationStore::open_root(root.capability.root.clone(), owner().unwrap())
            .await
            .is_err()
    );
    assert_eq!(
        connection.store.taskflow_run(RUN_ID).await.unwrap(),
        Some(run)
    );
    connection.close().await;
}

#[tokio::test]
async fn wrong_root_owner_and_corrupt_marker_fail_closed() {
    let first = FixtureRoot::new_synthetic(owner().unwrap()).await.unwrap();
    let other = FixtureRoot::new_synthetic(owner().unwrap()).await.unwrap();
    assert!(
        check_root(
            first.capability.root(),
            &owner().unwrap(),
            Some(&other.capability)
        )
        .is_err()
    );
    let wrong_owner = AgentId::parse("00000000-0000-4000-8000-000000000120").unwrap();
    assert!(
        check_root(
            first.capability.root(),
            &wrong_owner,
            Some(&first.capability)
        )
        .is_err()
    );
    std::fs::write(first.capability.root.join(MARKER), vec![b'x'; 2_049]).unwrap();
    assert!(first.connection().await.is_err());
}

#[tokio::test]
async fn binding_is_immutable_and_unexpected_table_inventory_rejects_reopen() {
    let root = FixtureRoot::new_synthetic(owner().unwrap()).await.unwrap();
    let connection = root.connection().await.unwrap();
    assert!(
        sqlx::query("UPDATE qualification_retrieval_binding SET correlation_id = 'changed'")
            .execute(connection.store.taskflow_pool())
            .await
            .is_err()
    );
    assert!(
        sqlx::query("DELETE FROM qualification_retrieval_binding")
            .execute(connection.store.taskflow_pool())
            .await
            .is_err()
    );
    check_pool(
        connection.store.taskflow_pool(),
        &owner().unwrap(),
        Some(&root.capability),
    )
    .await
    .unwrap();
    // Deliberate test-controller corruption; never part of a fixture operation.
    sqlx::query("CREATE TABLE qualification_retrieval_extra (id INTEGER PRIMARY KEY)")
        .execute(connection.store.taskflow_pool())
        .await
        .unwrap();
    connection.close().await;
    assert!(root.connection().await.is_err());
}

#[tokio::test]
async fn missing_immutability_trigger_rejects_reopen_with_valid_binding_row() {
    let root = FixtureRoot::new_synthetic(owner().unwrap()).await.unwrap();
    let connection = root.connection().await.unwrap();
    sqlx::query("DROP TRIGGER qualification_binding_no_update")
        .execute(connection.store.taskflow_pool())
        .await
        .unwrap();
    let rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM qualification_retrieval_binding WHERE singleton = 1",
    )
    .fetch_one(connection.store.taskflow_pool())
    .await
    .unwrap();
    assert_eq!(rows, 1);
    connection.close().await;
    assert!(root.connection().await.is_err());
}

#[tokio::test]
async fn weakened_trigger_rejects_reopen_without_changing_binding_row() {
    let root = FixtureRoot::new_synthetic(owner().unwrap()).await.unwrap();
    let connection = root.connection().await.unwrap();
    // Keep the DROP and replacement CREATE on one SQLite connection.
    let mut tamper = connection.store.taskflow_pool().begin().await.unwrap();
    sqlx::query("DROP TRIGGER qualification_binding_no_update")
        .execute(&mut *tamper)
        .await
        .unwrap();
    sqlx::query("CREATE TRIGGER qualification_binding_no_update BEFORE UPDATE ON qualification_retrieval_binding WHEN 0 BEGIN SELECT RAISE(ABORT, 'qualification binding is immutable'); END")
        .execute(&mut *tamper).await.unwrap();
    tamper.commit().await.unwrap();
    let correlation: String = sqlx::query_scalar(
        "SELECT correlation_id FROM qualification_retrieval_binding WHERE singleton = 1",
    )
    .fetch_one(connection.store.taskflow_pool())
    .await
    .unwrap();
    assert_eq!(correlation, root.capability.correlation);
    connection.close().await;
    assert!(root.connection().await.is_err());
}

// Prepare/claim transaction qualification; original seven root tests retained.
use super::records::PhaseCommand;
use super::records::PhaseFault;
use super::records::PhaseOutcome;
use crate::TaskFlowStepState;

async fn setup() -> Result<(FixtureRoot, FixtureConnection, PhaseCommand), FixtureError> {
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000119")
        .map_err(|_| FixtureError::Invalid)?;
    let root = FixtureRoot::new_synthetic(owner).await?;
    let connection = root.connection().await?;
    connection.bootstrap_fixed_activity().await?;
    let command = connection.prepare_command()?;
    Ok((root, connection, command))
}

async fn counts(connection: &FixtureConnection) -> Result<(i64, i64, i64), sqlx::Error> {
    let pool = connection.store.taskflow_pool();
    Ok((
        sqlx::query_scalar("SELECT COUNT(*) FROM qualification_retrieval_choices")
            .fetch_one(pool)
            .await?,
        sqlx::query_scalar("SELECT COUNT(*) FROM qualification_retrieval_claims")
            .fetch_one(pool)
            .await?,
        sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_step_outbox")
            .fetch_one(pool)
            .await?,
    ))
}

#[tokio::test]
async fn real_prepare_claim_dedup_and_reopen_never_return_second_fresh() {
    let (root, connection, prepare) = setup().await.unwrap();
    let original = connection.store.taskflow_run(RUN_ID).await.unwrap();
    let PhaseOutcome::Applied(receipt) = connection.phase(&prepare).await.unwrap() else {
        panic!("fresh prepare")
    };
    assert_eq!(receipt.native.state, TaskFlowStepState::Prepared);
    assert!(receipt.retained_bytes <= encoding::MAX_RETAINED_BYTES);
    assert_eq!(receipt.command_digest, prepare.canonical().unwrap().1);
    assert!(matches!(
        connection.phase(&prepare).await.unwrap(),
        PhaseOutcome::Historical(_)
    ));
    let claim = connection.claim_command(&prepare).unwrap();
    let PhaseOutcome::Fresh(fresh) = connection.phase(&claim).await.unwrap() else {
        panic!("one fresh claim")
    };
    assert_eq!(fresh.receipt.native.state, TaskFlowStepState::Claimed);
    assert!(fresh.receipt.retained_bytes <= encoding::MAX_RETAINED_BYTES);
    eprintln!(
        "current_phase_retained_bytes={}",
        fresh.receipt.retained_bytes
    );
    let PhaseOutcome::Historical(history) = connection.phase(&claim).await.unwrap() else {
        panic!("history only")
    };
    assert_eq!(history.native, fresh.receipt.native);
    assert_eq!(counts(&connection).await.unwrap(), (1, 1, 2));
    assert_eq!(
        connection.store.taskflow_run(RUN_ID).await.unwrap(),
        original
    );
    connection
        .store
        .replay_taskflow_structural(RUN_ID)
        .await
        .unwrap();
    connection.close().await;
    let reopened = root.connection().await.unwrap();
    assert!(matches!(
        reopened.phase(&claim).await.unwrap(),
        PhaseOutcome::Historical(_)
    ));
    assert_eq!(counts(&reopened).await.unwrap(), (1, 1, 2));
    reopened.close().await;
}

#[tokio::test]
async fn prepare_failpoints_rollback_both_native_and_choice_rows() {
    for fault in [
        PhaseFault::AfterNativeAppend,
        PhaseFault::AfterCorrelationInsert,
        PhaseFault::BeforeCommit,
    ] {
        let (_root, connection, prepare) = setup().await.unwrap();
        let original = connection.store.taskflow_run(RUN_ID).await.unwrap();
        assert!(matches!(
            connection
                .store
                .retrieval_phase_command(
                    &connection.capability,
                    &prepare,
                    fault,
                    /*before_write*/ None
                )
                .await,
            Err(FixtureError::Injected)
        ));
        assert_eq!(counts(&connection).await.unwrap(), (0, 0, 0));
        assert_eq!(
            connection.store.taskflow_run(RUN_ID).await.unwrap(),
            original
        );
        connection
            .store
            .replay_taskflow_structural(RUN_ID)
            .await
            .unwrap();
        connection.close().await;
    }
}

#[tokio::test]
async fn claim_failpoints_rollback_both_native_and_claim_rows() {
    for fault in [
        PhaseFault::AfterNativeAppend,
        PhaseFault::AfterCorrelationInsert,
        PhaseFault::BeforeCommit,
    ] {
        let (_root, connection, prepare) = setup().await.unwrap();
        connection.phase(&prepare).await.unwrap();
        let claim = connection.claim_command(&prepare).unwrap();
        let original = connection.store.taskflow_run(RUN_ID).await.unwrap();
        let previous = connection
            .store
            .read_taskflow_step(RUN_ID, ACTIVITY, /*attempt*/ 1, &prepare.fence)
            .await
            .unwrap();
        assert!(matches!(
            connection
                .store
                .retrieval_phase_command(
                    &connection.capability,
                    &claim,
                    fault,
                    /*before_write*/ None
                )
                .await,
            Err(FixtureError::Injected)
        ));
        assert_eq!(counts(&connection).await.unwrap(), (1, 0, 1));
        assert_eq!(
            connection
                .store
                .read_taskflow_step(RUN_ID, ACTIVITY, /*attempt*/ 1, &prepare.fence)
                .await
                .unwrap(),
            previous
        );
        assert_eq!(
            connection.store.taskflow_run(RUN_ID).await.unwrap(),
            original
        );
        connection
            .store
            .replay_taskflow_structural(RUN_ID)
            .await
            .unwrap();
        connection.close().await;
    }
}

#[tokio::test]
async fn committed_ack_loss_is_history_after_reopen_not_fresh() {
    let (root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let claim = connection.claim_command(&prepare).unwrap();
    assert!(matches!(
        connection
            .store
            .retrieval_phase_command(
                &connection.capability,
                &claim,
                PhaseFault::AfterCommitAckLoss,
                /*before_write*/ None
            )
            .await,
        Err(FixtureError::Injected)
    ));
    assert_eq!(counts(&connection).await.unwrap(), (1, 1, 2));
    connection.close().await;
    let reopened = root.connection().await.unwrap();
    assert!(matches!(
        reopened.phase(&claim).await.unwrap(),
        PhaseOutcome::Historical(_)
    ));
    assert_eq!(counts(&reopened).await.unwrap(), (1, 1, 2));
    reopened.close().await;
}

#[tokio::test]
async fn independent_sqlite_pools_race_before_first_write_for_one_fresh() {
    let (root, first, prepare) = setup().await.unwrap();
    first.phase(&prepare).await.unwrap();
    let second = root.connection().await.unwrap();
    let claim = first.claim_command(&prepare).unwrap();
    let barrier = tokio::sync::Barrier::new(2);
    let (left, right) = tokio::join!(
        first.store.retrieval_phase_command(
            &first.capability,
            &claim,
            PhaseFault::None,
            Some((&barrier, None))
        ),
        second.store.retrieval_phase_command(
            &second.capability,
            &claim,
            PhaseFault::None,
            Some((&barrier, None))
        ),
    );
    let fresh_count = usize::from(matches!(left, Ok(PhaseOutcome::Fresh(_))))
        + usize::from(matches!(right, Ok(PhaseOutcome::Fresh(_))));
    assert_eq!(
        fresh_count, 1,
        "no faults or expiry were injected in this race"
    );
    assert_eq!(counts(&first).await.unwrap(), (1, 1, 2));
    assert!(matches!(
        second.phase(&claim).await.unwrap(),
        PhaseOutcome::Historical(_)
    ));
    first.close().await;
    second.close().await;
}

#[tokio::test]
async fn changed_command_bytes_or_activation_cannot_rebind_choice() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let mut changed = prepare.clone();
    changed.command_id = "other001".to_owned();
    assert!(connection.phase(&changed).await.is_err());
    let mut claim = connection.claim_command(&prepare).unwrap();
    claim.activation_id = "otheract".to_owned();
    assert!(connection.phase(&claim).await.is_err());
    assert_eq!(counts(&connection).await.unwrap(), (1, 0, 1));
    connection.close().await;
}

#[tokio::test]
async fn expiry_preserves_prepared_and_same_byte_history_without_fresh() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let claim = connection.claim_command(&prepare).unwrap();
    connection.capability.advance_clock(5_000).unwrap();
    assert!(connection.phase(&claim).await.is_err());
    assert!(matches!(
        connection.phase(&prepare).await.unwrap(),
        PhaseOutcome::Historical(_)
    ));
    assert_eq!(counts(&connection).await.unwrap(), (1, 0, 1));
    connection.close().await;
}

#[tokio::test]
async fn ordinary_wait_resume_fault_makes_frozen_revision_stale() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let claim = connection.claim_command(&prepare).unwrap();
    // External test-controller mutation via the REAL ordinary owner API. This
    // does not claim that ordinary transitions enforce the fixture budget.
    let wait = TaskFlowCommand::new(
        RUN_ID,
        "wait0001",
        prepare.fence.clone(),
        prepare.revision,
        TaskFlowTransition::Wait {
            token: "waittok".to_owned(),
            resume_node: None,
        },
        prepare.now_ms,
    )
    .unwrap();
    let result = connection
        .store
        .apply_taskflow_command(&wait)
        .await
        .unwrap();
    let resume = TaskFlowCommand::new(
        RUN_ID,
        "resume01",
        prepare.fence.clone(),
        result.revision,
        TaskFlowTransition::Resume {
            token: "waittok".to_owned(),
        },
        prepare.now_ms,
    )
    .unwrap();
    connection
        .store
        .apply_taskflow_command(&resume)
        .await
        .unwrap();
    assert!(connection.phase(&claim).await.is_err());
    assert_eq!(counts(&connection).await.unwrap(), (1, 0, 1));
    connection
        .store
        .replay_taskflow_structural(RUN_ID)
        .await
        .unwrap();
    connection.close().await;
}

#[tokio::test]
async fn live_cancel_is_sticky_and_phase_adds_no_unknown_or_claim() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let claim = connection.claim_command(&prepare).unwrap();
    let cancel = TaskFlowCommand::new(
        RUN_ID,
        "cancel01",
        prepare.fence.clone(),
        prepare.revision,
        TaskFlowTransition::Cancel {
            reason: "fixture cancellation".to_owned(),
        },
        prepare.now_ms,
    )
    .unwrap();
    connection
        .store
        .apply_taskflow_command(&cancel)
        .await
        .unwrap();
    assert!(connection.phase(&claim).await.is_err());
    assert!(matches!(
        connection.phase(&prepare).await.unwrap(),
        PhaseOutcome::Historical(_)
    ));
    assert_eq!(counts(&connection).await.unwrap(), (1, 0, 1));
    assert_eq!(
        connection
            .store
            .taskflow_run(RUN_ID)
            .await
            .unwrap()
            .unwrap()
            .state,
        TaskFlowRunState::Cancelled
    );
    connection.close().await;
}

#[tokio::test]
async fn same_owner_other_root_capability_is_rejected_before_mutation() {
    let (_a, first, prepare) = setup().await.unwrap();
    let (_b, second, _) = setup().await.unwrap();
    assert!(
        first
            .store
            .retrieval_phase_command(
                &second.capability,
                &prepare,
                PhaseFault::None,
                /*before_write*/ None
            )
            .await
            .is_err()
    );
    assert_eq!(counts(&first).await.unwrap(), (0, 0, 0));
    assert_eq!(counts(&second).await.unwrap(), (0, 0, 0));
    first.close().await;
    second.close().await;
}

#[tokio::test]
async fn phase_rows_are_immutable_and_fk_points_to_real_native_event() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let pool = connection.store.taskflow_pool();
    let enabled: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
        .fetch_one(pool)
        .await
        .unwrap();
    assert_eq!(enabled, 1);
    assert!(
        sqlx::query("UPDATE qualification_retrieval_choices SET activation_id = 'otheract'")
            .execute(pool)
            .await
            .is_err()
    );
    assert!(
        sqlx::query("DELETE FROM qualification_retrieval_choices")
            .execute(pool)
            .await
            .is_err()
    );
    assert!(sqlx::query("INSERT INTO qualification_retrieval_claims
        (owner_agent_id,run_id,activation_id,command_id,command_digest,command_bytes,native_command_digest,step_id,attempt,event_seq)
        SELECT owner_agent_id,run_id,activation_id,'claim001',command_digest,command_bytes,native_command_digest,step_id,1,999
        FROM qualification_retrieval_choices").execute(pool).await.is_err());
    let violations = sqlx::query("PRAGMA foreign_key_check")
        .fetch_all(pool)
        .await
        .unwrap();
    assert!(violations.is_empty());
    assert_eq!(counts(&connection).await.unwrap(), (1, 0, 1));
    connection.close().await;
}

#[tokio::test]
async fn prepare_ack_loss_preserves_atomic_pair_and_replays_as_history() {
    let (root, connection, prepare) = setup().await.unwrap();
    assert!(matches!(
        connection
            .store
            .retrieval_phase_command(
                &connection.capability,
                &prepare,
                PhaseFault::AfterCommitAckLoss,
                /*before_write*/ None
            )
            .await,
        Err(FixtureError::Injected)
    ));
    assert_eq!(counts(&connection).await.unwrap(), (1, 0, 1));
    connection.close().await;
    let reopened = root.connection().await.unwrap();
    assert!(matches!(
        reopened.phase(&prepare).await.unwrap(),
        PhaseOutcome::Historical(_)
    ));
    assert_eq!(counts(&reopened).await.unwrap(), (1, 0, 1));
    reopened.close().await;
}

#[tokio::test]
async fn actual_sql_inventory_over_budget_is_rejected_without_phase_writes() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let claim = connection.claim_command(&prepare).unwrap();
    let mut revision = prepare.revision;
    // Real ordinary-owner fault injection, explicitly OUTSIDE phase budget
    // enforcement. The phase does not retroactively authorize or hide these rows.
    for index in 0..32 {
        let token = format!("t{index:07}");
        let wait = TaskFlowCommand::new(
            RUN_ID,
            format!("w{index:07}"),
            prepare.fence.clone(),
            revision,
            TaskFlowTransition::Wait {
                token: token.clone(),
                resume_node: None,
            },
            prepare.now_ms,
        )
        .unwrap();
        revision = connection
            .store
            .apply_taskflow_command(&wait)
            .await
            .unwrap()
            .revision;
        let resume = TaskFlowCommand::new(
            RUN_ID,
            format!("r{index:07}"),
            prepare.fence.clone(),
            revision,
            TaskFlowTransition::Resume { token },
            prepare.now_ms,
        )
        .unwrap();
        revision = connection
            .store
            .apply_taskflow_command(&resume)
            .await
            .unwrap()
            .revision;
    }
    let before = connection.store.taskflow_run(RUN_ID).await.unwrap();
    let mut tx = connection.store.taskflow_pool().begin().await.unwrap();
    assert!(matches!(
        budget::retained_bytes(&mut tx, &prepare, prepare.bootstrap_event_seq as i64).await,
        Err(FixtureError::Budget)
    ));
    tx.rollback().await.unwrap();
    assert!(connection.phase(&claim).await.is_err());
    assert_eq!(counts(&connection).await.unwrap(), (1, 0, 1));
    assert_eq!(connection.store.taskflow_run(RUN_ID).await.unwrap(), before);
    connection
        .store
        .replay_taskflow_structural(RUN_ID)
        .await
        .unwrap();
    connection.close().await;
}

#[tokio::test]
async fn historical_prepare_rejects_corrupt_claimed_tail() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let claim = connection.claim_command(&prepare).unwrap();
    connection.phase(&claim).await.unwrap();
    let pool = connection.store.taskflow_pool();
    // Controller-only DDL and corruption share one connection and commit.
    let mut tamper = pool.begin().await.unwrap();
    // Controller-only corruption; restore the trigger before exercising replay.
    sqlx::query("DROP TRIGGER taskflow_step_outbox_no_update")
        .execute(&mut *tamper)
        .await
        .unwrap();
    sqlx::query("UPDATE taskflow_step_outbox SET event_digest = '0000000000000000000000000000000000000000000000000000000000000000' WHERE event_kind = 'claimed'").execute(&mut *tamper).await.unwrap();
    sqlx::query("CREATE TRIGGER IF NOT EXISTS taskflow_step_outbox_no_update\nBEFORE UPDATE ON taskflow_step_outbox\nBEGIN\n    SELECT RAISE(ABORT, 'TaskFlow step outbox is append-only');\nEND;").execute(&mut *tamper).await.unwrap();
    tamper.commit().await.unwrap();
    let before = counts(&connection).await.unwrap();
    assert!(matches!(
        connection.phase(&prepare).await,
        Err(FixtureError::TaskFlow(crate::TaskFlowError::Corrupt(_)))
    ));
    assert_eq!(counts(&connection).await.unwrap(), before);
    connection.close().await;
}

#[tokio::test]
async fn historical_replay_rejects_corrupt_registry_definition() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let pool = connection.store.taskflow_pool();
    // Controller-only DDL and corruption share one connection and commit.
    let mut tamper = pool.begin().await.unwrap();
    // Controller-only corruption; restore the trigger before exercising replay.
    sqlx::query("DROP TRIGGER taskflow_definitions_no_update")
        .execute(&mut *tamper)
        .await
        .unwrap();
    sqlx::query("UPDATE taskflow_definitions SET definition_json = '{}'")
        .execute(&mut *tamper)
        .await
        .unwrap();
    sqlx::query("CREATE TRIGGER taskflow_definitions_no_update\nBEFORE UPDATE ON taskflow_definitions\nBEGIN\n    SELECT RAISE(ABORT, 'TaskFlow definitions are immutable');\nEND;").execute(&mut *tamper).await.unwrap();
    tamper.commit().await.unwrap();
    let before = counts(&connection).await.unwrap();
    assert!(matches!(
        connection.phase(&prepare).await,
        Err(FixtureError::TaskFlow(crate::TaskFlowError::Corrupt(_)))
    ));
    assert_eq!(counts(&connection).await.unwrap(), before);
    connection.close().await;
}

#[tokio::test]
async fn corrupted_choice_command_column_rejects_canonical_replay() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let pool = connection.store.taskflow_pool();
    // Controller-only DDL and corruption share one connection and commit.
    let mut tamper = pool.begin().await.unwrap();
    sqlx::query("DROP TRIGGER qualification_choices_no_update")
        .execute(&mut *tamper)
        .await
        .unwrap();
    sqlx::query("UPDATE qualification_retrieval_choices SET command_id = 'badcmd01'")
        .execute(&mut *tamper)
        .await
        .unwrap();
    sqlx::query("CREATE TRIGGER qualification_choices_no_update\nBEFORE UPDATE ON qualification_retrieval_choices BEGIN\n    SELECT RAISE(ABORT, 'qualification choice is immutable');\nEND;").execute(&mut *tamper).await.unwrap();
    tamper.commit().await.unwrap();
    check_pool(
        pool,
        connection.store.owner_agent_id(),
        Some(&connection.capability),
    )
    .await
    .unwrap();
    let before = counts(&connection).await.unwrap();
    assert!(matches!(
        connection.phase(&prepare).await,
        Err(FixtureError::Invalid)
    ));
    assert_eq!(counts(&connection).await.unwrap(), before);
    connection.close().await;
}

#[tokio::test]
async fn corrupted_claim_command_column_rejects_canonical_replay() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let claim = connection.claim_command(&prepare).unwrap();
    connection.phase(&claim).await.unwrap();
    let pool = connection.store.taskflow_pool();
    // Controller-only DDL and corruption share one connection and commit.
    let mut tamper = pool.begin().await.unwrap();
    sqlx::query("DROP TRIGGER qualification_claims_no_update")
        .execute(&mut *tamper)
        .await
        .unwrap();
    sqlx::query("UPDATE qualification_retrieval_claims SET command_id = 'badcmd01'")
        .execute(&mut *tamper)
        .await
        .unwrap();
    sqlx::query("CREATE TRIGGER qualification_claims_no_update\nBEFORE UPDATE ON qualification_retrieval_claims BEGIN\n    SELECT RAISE(ABORT, 'qualification claim is immutable');\nEND;").execute(&mut *tamper).await.unwrap();
    tamper.commit().await.unwrap();
    check_pool(
        pool,
        connection.store.owner_agent_id(),
        Some(&connection.capability),
    )
    .await
    .unwrap();
    let before = counts(&connection).await.unwrap();
    assert!(matches!(
        connection.phase(&claim).await,
        Err(FixtureError::Invalid)
    ));
    assert_eq!(counts(&connection).await.unwrap(), before);
    connection.close().await;
}

#[tokio::test]
async fn corrupted_choice_activation_column_rejects_canonical_replay() {
    let (_root, connection, prepare) = setup().await.unwrap();
    connection.phase(&prepare).await.unwrap();
    let claim = connection.claim_command(&prepare).unwrap();
    let pool = connection.store.taskflow_pool();
    // Controller-only DDL and corruption share one connection and commit.
    let mut tamper = pool.begin().await.unwrap();
    sqlx::query("DROP TRIGGER qualification_choices_no_update")
        .execute(&mut *tamper)
        .await
        .unwrap();
    sqlx::query("UPDATE qualification_retrieval_choices SET activation_id = 'badact01'")
        .execute(&mut *tamper)
        .await
        .unwrap();
    sqlx::query("CREATE TRIGGER qualification_choices_no_update\nBEFORE UPDATE ON qualification_retrieval_choices BEGIN\n    SELECT RAISE(ABORT, 'qualification choice is immutable');\nEND;").execute(&mut *tamper).await.unwrap();
    tamper.commit().await.unwrap();
    check_pool(
        pool,
        connection.store.owner_agent_id(),
        Some(&connection.capability),
    )
    .await
    .unwrap();
    let before = counts(&connection).await.unwrap();
    assert!(matches!(
        connection.phase(&claim).await,
        Err(FixtureError::Invalid)
    ));
    assert_eq!(counts(&connection).await.unwrap(), before);
    connection.close().await;
}

#[tokio::test]
async fn cancel_committed_after_claim_snapshot_prevents_fresh_write() {
    let (root, first, prepare) = setup().await.unwrap();
    first.phase(&prepare).await.unwrap();
    let second = root.connection().await.unwrap();
    let claim = first.claim_command(&prepare).unwrap();
    let ready = tokio::sync::Barrier::new(2);
    let release = tokio::sync::Barrier::new(2);
    let cancel = TaskFlowCommand::new(
        RUN_ID,
        "cancel01",
        prepare.fence.clone(),
        prepare.revision,
        TaskFlowTransition::Cancel {
            reason: "fixture cancellation".to_owned(),
        },
        prepare.now_ms,
    )
    .unwrap();
    let (result, cancelled) = tokio::join!(
        first.store.retrieval_phase_command(
            &first.capability,
            &claim,
            PhaseFault::None,
            Some((&ready, Some(&release))),
        ),
        async {
            // Both arrive only after the claim has read its snapshot, before
            // its first write. This separate pool commits Cancel before release.
            ready.wait().await;
            let result = second.store.apply_taskflow_command(&cancel).await;
            release.wait().await;
            result
        },
    );
    cancelled.unwrap();
    assert!(result.is_err(), "stale snapshot must not commit a claim");
    assert_eq!(counts(&first).await.unwrap(), (1, 0, 1));
    assert_eq!(
        second
            .store
            .taskflow_run(RUN_ID)
            .await
            .unwrap()
            .unwrap()
            .state,
        TaskFlowRunState::Cancelled
    );
    first.close().await;
    second.close().await;
}
