use super::*;
use codex_hepta_automation::TaskFlowError;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn stale_recovery_cannot_poison_original_attempt_after_reopen() {
    for recovery in [
        AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Succeeded,
            receipt_digest: Sha256Digest::for_bytes(b"stale-owner-success"),
            provider_ack: None,
        }),
        AuthorizedEffectRecovery::ProvenAbsent {
            proof_digest: Sha256Digest::for_bytes(b"stale-owner-absence"),
        },
    ] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        let (authority, signed, _authority_dir) = final_use(expected.clone(), "owner-recovery");
        let mut driver =
            RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"original-unknown");
        let original = store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                AuthorizedEffectExecutionInput {
                    intent: &effect,
                    wire_payload: EFFECT_PAYLOAD,
                    fence: &owner,
                    signed_grant: &signed,
                    expected_binding: &expected,
                    command_id: "authorized-effect-dispatch",
                    now_ms: 30,
                },
            )
            .await
            .expect("original unknown effect");
        assert_eq!(driver.calls, 1);
        let pending = store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("pending original attempt");
        let mut stale_owner = owner.clone();
        stale_owner.generation += 1;
        stale_owner.fencing_token = "different-owner-fence".to_string();

        assert!(matches!(
            store
                .recover_authorized_taskflow_effect(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                    &stale_owner,
                    recovery,
                    31,
                )
                .await,
            Err(AuthorizedEffectError::TaskFlow(TaskFlowError::StaleFence))
        ));
        store.close().await;
        let reopened = AutomationStore::open(&fixture.layout)
            .await
            .expect("reopen after rejected owner");
        assert_eq!(
            reopened
                .pending_authorized_taskflow_effects(8)
                .await
                .expect("original remains pending"),
            pending
        );
        assert_eq!(
            reopened
                .read_taskflow_step(&effect.run_id, &effect.step_id, effect.attempt, &owner)
                .await
                .expect("read original step"),
            Some(original)
        );

        // The original owner may observe a late provider ACK after lease expiry;
        // this repairs the old attempt and grants no authority to dispatch again.
        let recovered = reopened
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner,
                AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                    outcome: AuthorizedEffectOutcome::Succeeded,
                    receipt_digest: Sha256Digest::for_bytes(b"original-owner-success"),
                    provider_ack: None,
                }),
                2_000,
            )
            .await
            .expect("original owner terminal reconciliation");
        let AuthorizedEffectRecoveryResult::Observed(receipt) = recovered else {
            panic!("original provider observation must settle the original step");
        };
        assert_eq!(receipt.state, TaskFlowStepState::Reconciled);
        assert_eq!(
            receipt.final_outcome,
            Some(TaskFlowReconcileOutcome::Succeeded)
        );
        assert_eq!(driver.calls, 1);
        reopened.close().await;
    }
}

#[tokio::test]
async fn settled_absence_fact_read_survives_reopen_and_new_owner_without_redispatch() {
    for initial_unknown in [false, true] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        assert_eq!(
            store
                .read_settled_authorized_taskflow_effect_absence(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                )
                .await
                .expect("no attempt is not absence"),
            None
        );
        let (authority, signed, _directory) = final_use(expected.clone(), "settled-absence");
        let mut driver = if initial_unknown {
            RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"initial-unknown")
        } else {
            RecordingDriver::before_provider_contact()
        };
        let result = store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                AuthorizedEffectExecutionInput {
                    intent: &effect,
                    wire_payload: EFFECT_PAYLOAD,
                    fence: &owner,
                    signed_grant: &signed,
                    expected_binding: &expected,
                    command_id: "authorized-effect-dispatch",
                    now_ms: 30,
                },
            )
            .await;
        if initial_unknown {
            assert_eq!(
                result.expect("unknown observation").observation,
                Some(TaskFlowStepObservation::Indeterminate)
            );
            assert!(matches!(
                store
                    .recover_authorized_taskflow_effect(
                        &effect.run_id,
                        &effect.step_id,
                        effect.attempt,
                        &owner,
                        AuthorizedEffectRecovery::ProvenAbsent {
                            proof_digest: Sha256Digest::for_bytes(b"owner-proved-absence"),
                        },
                        31,
                    )
                    .await
                    .expect("settle owner-proved absence"),
                AuthorizedEffectRecoveryResult::ProvenAbsent
            ));
        } else {
            assert!(matches!(
                result,
                Err(AuthorizedEffectError::Driver(
                    AuthorizedEffectDriverError::BeforeProviderContact
                ))
            ));
        }
        let queued = store
            .taskflow_run(&effect.run_id)
            .await
            .expect("read settled run")
            .expect("run");
        assert_eq!(queued.state, TaskFlowRunState::Queued);
        assert_eq!(queued.owner_id, None);
        assert_eq!(queued.owner_epoch, None);
        assert_eq!(queued.generation, None);
        assert_eq!(queued.fencing_token, None);
        assert_eq!(queued.lease_expires_at_ms, None);
        let settled = store
            .read_taskflow_step(&effect.run_id, &effect.step_id, effect.attempt, &owner)
            .await
            .expect("original immutable step")
            .expect("step");
        assert_eq!(settled.state, TaskFlowStepState::Reconciled);
        assert_eq!(settled.final_outcome, Some(TaskFlowReconcileOutcome::Cancelled));
        assert_eq!(settled.fence, owner);
        store.close().await;
        let reopened = AutomationStore::open(&fixture.layout)
            .await
            .expect("reopen settled absence");
        assert_eq!(
            reopened
                .read_settled_authorized_taskflow_effect_absence(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                )
                .await
                .expect("owner-local settled absence"),
            Some(settled.clone())
        );
        let mut new_owner = owner.clone();
        new_owner.generation += 1;
        new_owner.fencing_token = "next-owner-fence".to_string();
        let claimed = reopened
            .claim_taskflow_run(&effect.run_id, &new_owner, 40, 1_000)
            .await
            .expect("claim requeued run under newer generation");
        reopened
            .apply_taskflow_command(
                &TaskFlowCommand::new(
                    &effect.run_id,
                    "new-owner-start",
                    new_owner,
                    claimed.revision,
                    TaskFlowTransition::Start,
                    41,
                )
                .expect("new owner start command"),
            )
            .await
            .expect("start after historical absence");
        let before = reopened.taskflow_run(&effect.run_id).await.expect("new run");
        assert_eq!(
            reopened
                .read_settled_authorized_taskflow_effect_absence(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                )
                .await
                .expect("history survives a newer run owner"),
            Some(settled)
        );
        assert_eq!(
            reopened.taskflow_run(&effect.run_id).await.expect("unchanged run"),
            before
        );
        assert!(
            reopened
                .execute_authorized_taskflow_effect(
                    &authority,
                    &mut driver,
                    AuthorizedEffectExecutionInput {
                        intent: &effect,
                        wire_payload: EFFECT_PAYLOAD,
                        fence: &owner,
                        signed_grant: &signed,
                        expected_binding: &expected,
                        command_id: "authorized-effect-dispatch",
                        now_ms: 42,
                    },
                )
                .await
                .is_err(),
            "a historical fact cannot authorize another dispatch"
        );
        assert_eq!(driver.calls, 1);
        assert_eq!(authority.capacity().expect("authority capacity").used_nonces, 1);
        reopened.close().await;
    }
}

#[tokio::test]
async fn settled_absence_fact_read_rejects_unknown_unsettled_and_corrupt_evidence() {
    for fault in ["unknown", "unsettled", "proof", "intent", "payload", "fence", "settlement_time"] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        let sqlite_home = AbsolutePathBuf::from_absolute_path(
            store.path().parent().expect("automation database parent"),
        )
        .expect("absolute sqlite home");
        let pool = SqliteConfig::from_sqlite_home(sqlite_home)
            .open_durable_evidence_pool(store.path())
            .await
            .expect("fault injection database");
        if fault == "unsettled" {
            sqlx::query(
                "CREATE TRIGGER test_refuse_absence_settlement BEFORE INSERT ON taskflow_events
                 WHEN NEW.transition = 'requeued_proven_absent'
                 BEGIN SELECT RAISE(ABORT, 'injected interruption before run settlement'); END",
            )
            .execute(&pool)
            .await
            .expect("install settlement interruption");
        }
        let (authority, signed, _directory) = final_use(expected.clone(), "absence-negative");
        let mut driver = if fault == "unknown" {
            RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"still-unknown")
        } else {
            RecordingDriver::before_provider_contact()
        };
        let result = store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                AuthorizedEffectExecutionInput {
                    intent: &effect,
                    wire_payload: EFFECT_PAYLOAD,
                    fence: &owner,
                    signed_grant: &signed,
                    expected_binding: &expected,
                    command_id: "authorized-effect-dispatch",
                    now_ms: 30,
                },
            )
            .await;
        if fault == "unknown" {
            assert_eq!(
                result.expect("persist unknown").observation,
                Some(TaskFlowStepObservation::Indeterminate)
            );
        } else if fault == "unsettled" {
            assert!(matches!(result, Err(AuthorizedEffectError::TaskFlow(_))));
            let recorded: String = sqlx::query_scalar(
                "SELECT observation FROM taskflow_effect_dispatch_observations",
            )
            .fetch_one(&pool)
            .await
            .expect("absence recorded before the interrupted projection");
            assert_eq!(recorded, "proven_absent");
        } else {
            assert!(matches!(
                result,
                Err(AuthorizedEffectError::Driver(
                    AuthorizedEffectDriverError::BeforeProviderContact
                ))
            ));
        }
        if matches!(fault, "unknown" | "unsettled") {
            let before = store.taskflow_run(&effect.run_id).await.expect("run before read");
            assert_eq!(
                store
                    .read_settled_authorized_taskflow_effect_absence(
                        &effect.run_id,
                        &effect.step_id,
                        effect.attempt,
                    )
                    .await
                    .expect("unsettled evidence remains unknown"),
                None,
                "{fault}"
            );
            assert_eq!(
                store.taskflow_run(&effect.run_id).await.expect("run after read"),
                before
            );
        } else {
            assert!(
                store
                    .read_settled_authorized_taskflow_effect_absence(
                        &effect.run_id,
                        &effect.step_id,
                        effect.attempt,
                    )
                    .await
                    .expect("untainted settled evidence")
                    .is_some()
            );
            let value = Sha256Digest::for_bytes(b"injected-absence-corruption");
            let mutation = || match fault {
                "proof" => sqlx::query(
                    "UPDATE taskflow_step_outbox SET receipt_digest = ? WHERE event_kind = 'reconciled'",
                ).bind(value.as_str()),
                "intent" => sqlx::query("UPDATE taskflow_step_outbox SET intent_digest = ?")
                    .bind(value.as_str()),
                "payload" => sqlx::query("UPDATE taskflow_step_outbox SET payload_digest = ?")
                    .bind(value.as_str()),
                "fence" => sqlx::query("UPDATE taskflow_step_outbox SET fencing_token = ?")
                    .bind(value.as_str()),
                "settlement_time" => sqlx::query(
                    "UPDATE taskflow_events SET recorded_at_ms = recorded_at_ms + 1 WHERE transition = 'requeued_proven_absent'",
                ),
                _ => unreachable!("enumerated fault"),
            };
            assert!(mutation().execute(&pool).await.is_err());
            if fault == "settlement_time" {
                sqlx::query("DROP TRIGGER taskflow_events_no_update").execute(&pool).await
            } else {
                sqlx::query("DROP TRIGGER taskflow_step_outbox_no_update").execute(&pool).await
            }
            .expect("explicit corrupt-import injection");
            let changed = mutation()
                .execute(&pool)
                .await
                .expect("publish corrupt evidence");
            assert!(changed.rows_affected() > 0);
            let read = store
                .read_settled_authorized_taskflow_effect_absence(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                )
                .await;
            if fault == "settlement_time" {
                assert!(matches!(read,
                    Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Corrupt(message)))
                    if message == "provider absence requeue differs from immutable step fence"
                ));
            } else {
                assert!(matches!(read,
                    Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Corrupt(_) | TaskFlowError::Conflict(_)))
                ), "{fault}");
            }
        }
        assert_eq!(driver.calls, 1);
        assert_eq!(authority.capacity().expect("authority capacity").used_nonces, 1);
        pool.close().await;
        store.close().await;
    }
}
