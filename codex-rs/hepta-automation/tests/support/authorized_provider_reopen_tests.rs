use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn taskflow_provider_receipt_first_binding_on_retry_preserves_earlier_absence() {
    retry_after_absence(/*authoritative_lookup*/ false).await;
}

#[tokio::test]
async fn taskflow_dispatch_barrier_explicit_absence_allows_new_fence_and_preserves_history() {
    retry_after_absence(/*authoritative_lookup*/ true).await;
}

async fn retry_after_absence(authoritative_lookup: bool) {
    let fixture = Fixture::new();
    let (store, first_owner, mut effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "first-absence");
    let adapter = RecordingProviderEffectAdapter::new(
        if authoritative_lookup {
            ProviderEffectDispatch::Unknown
        } else {
            ProviderEffectDispatch::NotDispatched {
                reason_code: "before-contact".to_string(),
            }
        },
        ProviderEffectLookup::Unknown,
    );
    let mut driver = ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter)
        .expect("provider driver");
    let initial = store
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            AuthorizedEffectExecutionInput {
                intent: &effect,
                wire_payload: EFFECT_PAYLOAD,
                fence: &first_owner,
                signed_grant: &signed,
                expected_binding: &expected,
                command_id: "first-provider-absence",
                now_ms: 30,
            },
        )
        .await;
    if authoritative_lookup {
        assert_eq!(
            initial.expect("initial uncertainty").observation,
            Some(TaskFlowStepObservation::Indeterminate)
        );
        store
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                1,
                &first_owner,
                AuthorizedEffectRecovery::ProvenAbsent {
                    proof_digest: Sha256Digest::for_bytes(b"authoritative-provider-absence"),
                },
                35,
            )
            .await
            .expect("original owner proves and settles absence");
    } else {
        assert!(matches!(
            initial,
            Err(AuthorizedEffectError::Driver(
                AuthorizedEffectDriverError::BeforeProviderContact
            ))
        ));
    }
    let reused_generation = TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent"),
        "authorized-effect-owner",
        2,
        1,
        "higher-epoch-reused-generation",
    )
    .expect("invalid historical reuse fixture");
    assert!(
        store
            .claim_taskflow_run(&effect.run_id, &reused_generation, 38, 1_000)
            .await
            .is_err()
    );
    let second_owner = TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent"),
        "authorized-effect-owner",
        1,
        2,
        "second-effect-fence",
    )
    .expect("new fence");
    let claimed = store
        .claim_taskflow_run(&effect.run_id, &second_owner, 40, 1_000)
        .await
        .expect("claim proved-absent run");
    store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &effect.run_id,
                "retry-start",
                second_owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                41,
            )
            .expect("start command"),
        )
        .await
        .expect("start retry");
    effect.attempt = 2;
    let digest = effect.digest().expect("retry intent");
    store
        .prepare_taskflow_step(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &second_owner,
            &digest,
            &effect.payload_digest,
            "retry-prepare",
            42,
        )
        .await
        .expect("prepare retry");
    store
        .claim_taskflow_step(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &second_owner,
            &digest,
            &effect.payload_digest,
            "retry-claim",
            43,
        )
        .await
        .expect("claim retry");
    let accepted = provider_ack(
        &effect,
        b"retry-operation",
        ProviderEffectAckStatus::Accepted,
    );
    driver.adapter_mut().dispatch_result = ProviderEffectDispatch::Ack(accepted.clone());
    let expected = binding(&effect);
    let (authority, signed, _retry_authority_dir) = final_use(expected.clone(), "retry-acceptance");
    store
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            AuthorizedEffectExecutionInput {
                intent: &effect,
                wire_payload: EFFECT_PAYLOAD,
                fence: &second_owner,
                signed_grant: &signed,
                expected_binding: &expected,
                command_id: "retry-dispatch",
                now_ms: 50,
            },
        )
        .await
        .expect("accept second attempt");
    assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 2);
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen both attempts");
    let first = reopened
        .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, 1)
        .await
        .expect("read prior attempt")
        .expect("prior attempt");
    let pending = reopened
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending retry");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].attempt, 2);
    assert_eq!(pending[0].provider_ack, Some(accepted));
    assert_eq!(first.provider_ack, None);
    assert_eq!(first.provider_effect_key, pending[0].provider_effect_key);
    let pool = database(&reopened).await;
    let history: Vec<(i64, String)> = sqlx::query_as(
        "SELECT attempt, observation FROM taskflow_effect_dispatch_observations ORDER BY attempt",
    )
    .fetch_all(&pool)
    .await
    .expect("original immutable observations");
    assert_eq!(
        history,
        vec![
            (
                1,
                if authoritative_lookup {
                    "indeterminate"
                } else {
                    "proven_absent"
                }
                .to_string()
            ),
            (2, "indeterminate".to_string())
        ]
    );
    pool.close().await;
}

#[tokio::test]
async fn taskflow_provider_receipt_reopen_requires_all_append_only_guards() {
    for statement in [
        "DROP TRIGGER taskflow_effect_dispatch_attempts_no_update",
        "DROP TRIGGER taskflow_effect_dispatch_attempts_no_delete",
        "DROP TRIGGER taskflow_effect_dispatch_observations_no_update",
        "DROP TRIGGER taskflow_effect_dispatch_observations_no_delete",
        "DROP TRIGGER taskflow_effect_dispatch_reconciliations_no_update",
        "DROP TRIGGER taskflow_effect_dispatch_reconciliations_no_delete",
        "DROP TRIGGER taskflow_effect_provider_bindings_no_update",
        "DROP TRIGGER taskflow_effect_provider_bindings_no_delete",
    ] {
        let fixture = Fixture::new();
        let store = AutomationStore::open(&fixture.layout)
            .await
            .expect("fresh store");
        store.close().await;
        let pool = database(&store).await;
        sqlx::query(statement)
            .execute(&pool)
            .await
            .expect("remove one relied-on guard");
        pool.close().await;
        assert!(
            matches!(
                AutomationStore::open(&fixture.layout).await,
                Err(codex_hepta_automation::AutomationError::Corrupt)
            ),
            "missing guard must fail reopen after: {statement}"
        );
    }
}

#[tokio::test]
async fn taskflow_provider_receipt_reopen_rejects_terminal_binding_without_observation() {
    for status in [
        ProviderEffectAckStatus::Completed,
        ProviderEffectAckStatus::Rejected,
    ] {
        let fixture = Fixture::new();
        let started = start(&fixture, ProviderEffectDispatch::Unknown).await;
        let ack = provider_ack(&started.effect, b"never-observed-terminal", status);
        let digest = AuthorizedEffectProviderReceipt::from_provider_ack(
            ack.clone(),
            ProviderEffectAckSource::StatusLookup,
        )
        .receipt_digest;
        let json = format!(
            "{{\"schema_version\":1,\"source\":\"status_lookup\",\"ack\":{}}}",
            serde_json::to_string(&ack).expect("canonical ACK"),
        );
        let pool = database(&started.store).await;
        sqlx::query(
            "INSERT INTO taskflow_effect_provider_bindings
             (owner_agent_id, run_id, step_id, attempt, receipt_json, receipt_digest, observed_at_ms)
             SELECT owner_agent_id, run_id, step_id, attempt, ?, ?, 40
             FROM taskflow_effect_dispatch_attempts"
        ).bind(json).bind(digest.as_str()).execute(&pool).await
            .expect("import canonical terminal binding without its observation");
        pool.close().await;
        started.store.close().await;
        assert!(matches!(
            AutomationStore::open(&fixture.layout).await,
            Err(codex_hepta_automation::AutomationError::Corrupt)
        ));
    }
}

#[tokio::test]
async fn taskflow_provider_receipt_reopen_rejects_reconciliation_without_uncertainty() {
    let fixture = Fixture::new();
    let started = start(&fixture, ProviderEffectDispatch::Unknown).await;
    let pool = database(&started.store).await;
    sqlx::query("DROP TRIGGER taskflow_effect_dispatch_observations_no_update")
        .execute(&pool)
        .await
        .expect("fault injection");
    sqlx::query("UPDATE taskflow_effect_dispatch_observations SET observation='succeeded'")
        .execute(&pool)
        .await
        .expect("import terminal initial observation");
    sqlx::query(
        "CREATE TRIGGER taskflow_effect_dispatch_observations_no_update
        BEFORE UPDATE ON taskflow_effect_dispatch_observations
        BEGIN SELECT RAISE(ABORT, 'TaskFlow effect dispatch observations are immutable'); END",
    )
    .execute(&pool)
    .await
    .expect("restore original guard");
    sqlx::query(
        "INSERT INTO taskflow_effect_dispatch_reconciliations
         (owner_agent_id, run_id, step_id, attempt, observation, evidence_digest, observed_at_ms)
         SELECT owner_agent_id, run_id, step_id, attempt, 'failed', evidence_digest, 40
         FROM taskflow_effect_dispatch_observations",
    )
    .execute(&pool)
    .await
    .expect("import inconsistent reconciliation");
    pool.close().await;
    started.store.close().await;
    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(codex_hepta_automation::AutomationError::Corrupt)
    ));
}

#[tokio::test]
async fn taskflow_provider_receipt_migration_preserves_legacy_recovery_material() {
    for retain_recovery_material in [true, false] {
        let fixture = Fixture::new();
        let mut started = start(&fixture, ProviderEffectDispatch::Unknown).await;
        let before = started
            .store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("pending");
        started.store.close().await;
        let pool = database(&started.store).await;
        let mut transaction = pool.begin().await.expect("legacy fixture transaction");
        for statement in [
            "DROP TABLE taskflow_effect_provider_bindings",
            "ALTER TABLE taskflow_effect_dispatch_observations DROP COLUMN provider_receipt_json",
            "ALTER TABLE taskflow_effect_dispatch_reconciliations DROP COLUMN provider_receipt_json",
            "DELETE FROM _sqlx_migrations WHERE version=21",
            "DROP TRIGGER automation_meta_no_update",
            "UPDATE automation_meta SET schema_version=20 WHERE singleton=1",
            "CREATE TRIGGER automation_meta_no_update BEFORE UPDATE ON automation_meta
             BEGIN SELECT RAISE(ABORT, 'automation owner metadata is immutable'); END",
        ] {
            sqlx::query(statement)
                .execute(&mut *transaction)
                .await
                .expect("rewind to actual v20 shape");
        }
        if !retain_recovery_material {
            sqlx::query("DROP TRIGGER taskflow_effect_dispatch_attempts_no_update")
                .execute(&mut *transaction)
                .await
                .expect("construct pre-v20 compatible row");
            sqlx::query("UPDATE taskflow_effect_dispatch_attempts SET provider_effect_key=NULL, wire_payload=NULL")
                .execute(&mut *transaction).await.expect("legacy digest-only recovery material");
            sqlx::query(
                "CREATE TRIGGER taskflow_effect_dispatch_attempts_no_update
                BEFORE UPDATE ON taskflow_effect_dispatch_attempts
                BEGIN SELECT RAISE(ABORT, 'TaskFlow effect dispatch attempts are immutable'); END",
            )
            .execute(&mut *transaction)
            .await
            .expect("restore attempt guard");
        }
        transaction.commit().await.expect("publish legacy fixture");
        pool.close().await;
        started.store = AutomationStore::open(&fixture.layout)
            .await
            .expect("actual v20 to v21 migration");
        let after = started
            .store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("legacy pending");
        let mut expected = before;
        if !retain_recovery_material {
            expected[0].provider_effect_key = None;
            expected[0].wire_payload = None;
        }
        assert_eq!(after, expected);
        let accepted = provider_ack(
            &started.effect,
            b"original-operation",
            ProviderEffectAckStatus::Accepted,
        );
        started.driver.adapter_mut().lookup_result = ProviderEffectLookup::Ack(accepted);
        let lookup = started.driver.lookup(&after[0]).await;
        if retain_recovery_material {
            let AuthorizedProviderEffectLookup::Observed(receipt) = lookup else {
                panic!("exact legacy key must remain queryable");
            };
            recover(&started, receipt)
                .await
                .expect("bind recovered legacy ACK");
        } else {
            assert!(matches!(lookup, AuthorizedProviderEffectLookup::Unresolved));
        }
        assert_eq!(
            started
                .driver
                .adapter()
                .dispatch_calls
                .load(Ordering::Relaxed),
            1
        );
        started.store.close().await;
        AutomationStore::open(&fixture.layout)
            .await
            .expect("reopen migrated history");
    }
}

#[tokio::test]
async fn taskflow_provider_receipt_storage_rejects_oversized_binding_without_partial_write() {
    let fixture = Fixture::new();
    let started = start(&fixture, ProviderEffectDispatch::Unknown).await;
    let pool = database(&started.store).await;
    let oversized = "x".repeat(1025);
    let result = sqlx::query(
        "INSERT INTO taskflow_effect_provider_bindings
         (owner_agent_id, run_id, step_id, attempt, receipt_json, receipt_digest, observed_at_ms)
         SELECT owner_agent_id, run_id, step_id, attempt, ?, ?, 40
         FROM taskflow_effect_dispatch_attempts",
    )
    .bind(oversized)
    .bind(Sha256Digest::for_bytes(b"oversized").as_str())
    .execute(&pool)
    .await;
    assert!(result.is_err());
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_effect_provider_bindings")
        .fetch_one(&pool)
        .await
        .expect("no partial receipt");
    assert_eq!(count, 0);
    pool.close().await;
    started.store.close().await;
    AutomationStore::open(&fixture.layout)
        .await
        .expect("oversize rejection preserves valid history");
}
