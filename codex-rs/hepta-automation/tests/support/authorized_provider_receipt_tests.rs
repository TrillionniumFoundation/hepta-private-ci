use super::*;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

#[path = "authorized_provider_reopen_tests.rs"]
mod reopen_tests;

#[path = "authorized_dispatch_barrier_tests.rs"]
mod barrier_tests;

#[path = "authorized_provider_identity_tests.rs"]
mod identity_tests;

#[path = "authorized_provider_late_ack_tests.rs"]
mod late_ack_tests;

struct StartedEffect {
    store: AutomationStore,
    owner: TaskFlowFence,
    effect: AuthorizedEffectIntent,
    driver: ProviderEffectTaskFlowDriver<RecordingProviderEffectAdapter>,
}

fn provider_ack(
    effect: &AuthorizedEffectIntent,
    operation: &[u8],
    status: ProviderEffectAckStatus,
) -> ProviderEffectAck {
    ProviderEffectAck::new(
        ProviderEffectKey::for_taskflow_v2(
            &effect.destination_id,
            &AgentId::parse(AGENT_ID).expect("fixture owner"),
            &effect.run_id,
            &effect.step_id,
        )
        .expect("key"),
        effect.payload_digest.clone(),
        Sha256Digest::for_bytes(operation),
        status,
    )
}

async fn start(fixture: &Fixture, dispatch: ProviderEffectDispatch) -> StartedEffect {
    let (store, owner, effect, expected) = prepared_effect_store(fixture).await;
    let (authority, signed, _directory) =
        final_use(expected.clone(), "structured-provider-receipt");
    let adapter = RecordingProviderEffectAdapter::new(dispatch, ProviderEffectLookup::Unknown);
    let mut driver =
        ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter).expect("driver");
    let observed = store
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            AuthorizedEffectExecutionInput {
                intent: &effect,
                wire_payload: EFFECT_PAYLOAD,
                fence: &owner,
                signed_grant: &signed,
                expected_binding: &expected,
                command_id: "provider-receipt-dispatch",
                now_ms: 30,
            },
        )
        .await
        .expect("initial dispatch");
    assert_eq!(
        observed.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 1);
    StartedEffect {
        store,
        owner,
        effect,
        driver,
    }
}

async fn recover(
    started: &StartedEffect,
    receipt: AuthorizedEffectProviderReceipt,
) -> Result<AuthorizedEffectRecoveryResult, AuthorizedEffectError> {
    started
        .store
        .recover_authorized_taskflow_effect(
            &started.effect.run_id,
            &started.effect.step_id,
            started.effect.attempt,
            &started.owner,
            AuthorizedEffectRecovery::Observed(receipt),
            40,
        )
        .await
}

async fn database(store: &AutomationStore) -> sqlx::SqlitePool {
    let sqlite_home = AbsolutePathBuf::from_absolute_path(
        store.path().parent().expect("automation database parent"),
    )
    .expect("absolute sqlite home");
    SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(store.path())
        .await
        .expect("test database connection")
}

#[tokio::test]
async fn taskflow_provider_receipt_pins_accepted_identity_and_blocks_opaque_bypass() {
    let fixture = Fixture::new();
    let accepted = provider_ack(
        &intent(),
        b"original-operation",
        ProviderEffectAckStatus::Accepted,
    );
    let mut started = start(&fixture, ProviderEffectDispatch::Ack(accepted.clone())).await;
    started.store.close().await;
    started.store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen accepted effect");
    let pending = started
        .store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending");
    assert_eq!(pending[0].provider_ack, Some(accepted.clone()));
    assert_eq!(pending[0].wire_payload.as_deref(), Some(EFFECT_PAYLOAD));

    started.driver.adapter_mut().lookup_result = ProviderEffectLookup::NotFound;
    assert!(matches!(
        started.driver.lookup(&pending[0]).await,
        AuthorizedProviderEffectLookup::Unresolved
    ));
    for mut bad in [
        provider_ack(
            &started.effect,
            b"another-operation",
            ProviderEffectAckStatus::Completed,
        ),
        provider_ack(
            &started.effect,
            b"original-operation",
            ProviderEffectAckStatus::Rejected,
        ),
    ] {
        let receipt = AuthorizedEffectProviderReceipt::from_provider_ack(
            bad.clone(),
            ProviderEffectAckSource::StatusLookup,
        );
        assert!(recover(&started, receipt).await.is_err());
        bad.payload_sha256 = Sha256Digest::for_bytes(b"substituted payload");
        assert!(
            recover(
                &started,
                AuthorizedEffectProviderReceipt::from_provider_ack(
                    bad,
                    ProviderEffectAckSource::StatusLookup
                )
            )
            .await
            .is_err()
        );
    }
    assert!(
        recover(
            &started,
            AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: Sha256Digest::for_bytes(b"opaque bypass"),
                provider_ack: None,
            }
        )
        .await
        .is_err()
    );
    assert!(
        started
            .store
            .recover_authorized_taskflow_effect(
                &started.effect.run_id,
                &started.effect.step_id,
                started.effect.attempt,
                &started.owner,
                AuthorizedEffectRecovery::ProvenAbsent {
                    proof_digest: Sha256Digest::for_bytes(b"absence after acceptance")
                },
                40,
            )
            .await
            .is_err()
    );
    let after = started
        .store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("still pending");
    assert_eq!(after, pending);

    let complete = provider_ack(
        &started.effect,
        b"original-operation",
        ProviderEffectAckStatus::Completed,
    );
    let complete_receipt = AuthorizedEffectProviderReceipt::from_provider_ack(
        complete.clone(),
        ProviderEffectAckSource::StatusLookup,
    );
    let terminal_digest = complete_receipt.receipt_digest.clone();
    let result = recover(&started, complete_receipt)
        .await
        .expect("original operation completes");
    let pool = database(&started.store).await;
    let owner_projection: Vec<(String, Option<String>)> = sqlx::query_as(
        "SELECT o.observation, r.observation FROM taskflow_effect_dispatch_observations o
         LEFT JOIN taskflow_effect_dispatch_reconciliations r
         ON r.owner_agent_id=o.owner_agent_id AND r.run_id=o.run_id
         AND r.step_id=o.step_id AND r.attempt=o.attempt",
    )
    .fetch_all(&pool)
    .await
    .expect("actual provider owner projections");
    let terminal_json: String = sqlx::query_scalar(
        "SELECT provider_receipt_json FROM taskflow_effect_dispatch_reconciliations",
    )
    .fetch_one(&pool)
    .await
    .expect("exact terminal provider receipt");
    pool.close().await;
    let run_state = started
        .store
        .taskflow_run(&started.effect.run_id)
        .await
        .expect("actual run projection")
        .expect("run")
        .state;
    let AuthorizedEffectRecoveryResult::Observed(receipt) = result else {
        panic!("a completed operation must yield a reconciled observation");
    };
    assert_eq!(
        (
            receipt.state,
            receipt.observation,
            receipt.final_outcome,
            receipt.receipt_digest
        ),
        (
            TaskFlowStepState::Reconciled,
            Some(TaskFlowStepObservation::Indeterminate),
            Some(TaskFlowReconcileOutcome::Succeeded),
            Some(terminal_digest)
        ),
    );
    assert_eq!(
        owner_projection,
        vec![("indeterminate".to_string(), Some("succeeded".to_string()))]
    );
    assert_eq!(run_state, TaskFlowRunState::Succeeded);
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&terminal_json).expect("terminal JSON"),
        serde_json::json!({"schema_version": 1, "source": "status_lookup", "ack": complete})
    );
    assert_eq!(
        started
            .driver
            .adapter()
            .dispatch_calls
            .load(Ordering::Relaxed),
        1
    );
    started.store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen complete history");
    assert!(
        reopened
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("no pending")
            .is_empty()
    );
}

#[tokio::test]
async fn taskflow_provider_receipt_lost_ack_then_accepted_is_bounded_and_concurrent_safe() {
    let fixture = Fixture::new();
    let mut started = start(&fixture, ProviderEffectDispatch::Unknown).await;
    let original = started
        .store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending");
    assert_eq!(original[0].provider_ack, None);
    let accepted = provider_ack(
        &started.effect,
        b"original-operation",
        ProviderEffectAckStatus::Accepted,
    );
    started.driver.adapter_mut().lookup_result = ProviderEffectLookup::Ack(accepted.clone());
    for _ in 0..16 {
        let AuthorizedProviderEffectLookup::Observed(receipt) =
            started.driver.lookup(&original[0]).await
        else {
            panic!("Accepted lookup must reach the durable owner");
        };
        let result = recover(&started, receipt)
            .await
            .expect("record accepted lookup");
        assert!(
            matches!(result, AuthorizedEffectRecoveryResult::Observed(receipt) if receipt.observation == Some(TaskFlowStepObservation::Indeterminate))
        );
    }
    let pool = database(&started.store).await;
    let binding_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_effect_provider_bindings")
            .fetch_one(&pool)
            .await
            .expect("binding count");
    let observations: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_effect_dispatch_observations")
            .fetch_one(&pool)
            .await
            .expect("observation count");
    assert_eq!((binding_count, observations), (1, 1));
    pool.close().await;
    started.store.close().await;
    started.store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen accepted lookup");
    let pending = started
        .store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending");
    assert_eq!(pending[0].provider_ack, Some(accepted));

    let correct = AuthorizedEffectProviderReceipt::from_provider_ack(
        provider_ack(
            &started.effect,
            b"original-operation",
            ProviderEffectAckStatus::Completed,
        ),
        ProviderEffectAckSource::StatusLookup,
    );
    let substituted = AuthorizedEffectProviderReceipt::from_provider_ack(
        provider_ack(
            &started.effect,
            b"another-operation",
            ProviderEffectAckStatus::Completed,
        ),
        ProviderEffectAckSource::StatusLookup,
    );
    let (good, bad) = tokio::join!(recover(&started, correct), recover(&started, substituted));
    assert!(good.is_ok());
    assert!(bad.is_err());
    assert_eq!(
        started
            .driver
            .adapter()
            .dispatch_calls
            .load(Ordering::Relaxed),
        1
    );
    let pool = database(&started.store).await;
    let reconciliations: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_effect_dispatch_reconciliations")
            .fetch_one(&pool)
            .await
            .expect("reconciliation count");
    assert_eq!(reconciliations, 1);
    pool.close().await;
}

#[tokio::test]
async fn taskflow_provider_receipt_reopen_rejects_canonical_substitution() {
    let fixture = Fixture::new();
    let accepted = provider_ack(
        &intent(),
        b"original-operation",
        ProviderEffectAckStatus::Accepted,
    );
    let started = start(&fixture, ProviderEffectDispatch::Ack(accepted.clone())).await;
    let complete = provider_ack(
        &started.effect,
        b"original-operation",
        ProviderEffectAckStatus::Completed,
    );
    recover(
        &started,
        AuthorizedEffectProviderReceipt::from_provider_ack(
            complete,
            ProviderEffectAckSource::StatusLookup,
        ),
    )
    .await
    .expect("complete");
    let pool = database(&started.store).await;
    let mut transaction = pool.begin().await.expect("fault injection transaction");
    let original: String = sqlx::query_scalar(
        "SELECT provider_receipt_json FROM taskflow_effect_dispatch_reconciliations",
    )
    .fetch_one(&mut *transaction)
    .await
    .expect("original receipt JSON");
    let other = provider_ack(
        &started.effect,
        b"another-operation",
        ProviderEffectAckStatus::Completed,
    );
    let modified = original.replace(
        accepted.provider_operation_id_sha256.as_str(),
        other.provider_operation_id_sha256.as_str(),
    );
    let digest = AuthorizedEffectProviderReceipt::from_provider_ack(
        other,
        ProviderEffectAckSource::StatusLookup,
    )
    .receipt_digest;
    assert!(
        sqlx::query("UPDATE taskflow_effect_dispatch_reconciliations SET provider_receipt_json=?")
            .bind(&modified)
            .execute(&mut *transaction)
            .await
            .is_err()
    );
    sqlx::query("DROP TRIGGER taskflow_effect_dispatch_reconciliations_no_update")
        .execute(&mut *transaction)
        .await
        .expect("fault injection");
    sqlx::query("UPDATE taskflow_effect_dispatch_reconciliations SET provider_receipt_json=?, evidence_digest=?")
        .bind(modified).bind(digest.as_str()).execute(&mut *transaction).await.expect("canonical imported substitution");
    sqlx::query(
        "CREATE TRIGGER taskflow_effect_dispatch_reconciliations_no_update
        BEFORE UPDATE ON taskflow_effect_dispatch_reconciliations
        BEGIN SELECT RAISE(ABORT, 'TaskFlow effect reconciliations are immutable'); END",
    )
    .execute(&mut *transaction)
    .await
    .expect("restore original schema");
    transaction
        .commit()
        .await
        .expect("publish imported substitution");
    pool.close().await;
    started.store.close().await;
    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(codex_hepta_automation::AutomationError::Corrupt)
    ));
}
