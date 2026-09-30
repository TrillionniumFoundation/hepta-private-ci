use super::*;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::TaskFlowError;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;

async fn crash_at_dispatch_barrier(
    store: &AutomationStore,
    owner: &TaskFlowFence,
    effect: &AuthorizedEffectIntent,
    expected: &FinalUseBinding,
    command_id: &str,
    now_ms: u64,
) {
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "projection-crash");
    let store = store.clone();
    let owner = owner.clone();
    let effect = effect.clone();
    let expected = expected.clone();
    let command_id = command_id.to_string();
    let crashed = tokio::spawn(async move {
        store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut CrashAfterProviderContactDriver,
                &effect,
                EFFECT_PAYLOAD,
                &owner,
                &signed,
                &expected,
                &command_id,
                now_ms,
            )
            .await
    })
    .await
    .expect_err("barrier crash");
    assert!(crashed.is_panic());
}

async fn persist_terminal_cut(
    store: &AutomationStore,
    effect: &AuthorizedEffectIntent,
    observation: &str,
    evidence: &Sha256Digest,
    at_ms: u64,
) {
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(SqliteConnectOptions::new().filename(store.path()))
        .await
        .expect("test SQL");
    sqlx::query(
        "INSERT INTO taskflow_effect_dispatch_observations
         (owner_agent_id, run_id, step_id, attempt, observation, evidence_digest, observed_at_ms)
         VALUES (?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(AGENT_ID)
    .bind(&effect.run_id)
    .bind(&effect.step_id)
    .bind(i64::from(effect.attempt))
    .bind(observation)
    .bind(evidence.as_str())
    .bind(i64::try_from(at_ms).expect("timestamp"))
    .execute(&pool)
    .await
    .expect("terminal cut");
    pool.close().await;
}

#[tokio::test]
async fn terminal_observation_and_partial_step_projection_survive_restart_and_cancel() {
    for step_projected in [false, true] {
        for kind in ["succeeded", "failed", "proven_absent"] {
            let fixture = Fixture::new();
            let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
            let command_id = "projection-cut-dispatch";
            crash_at_dispatch_barrier(
                &store, &owner, &effect, &expected, command_id, /*now_ms*/ 30,
            )
            .await;
            let evidence = Sha256Digest::for_bytes(kind.as_bytes());
            persist_terminal_cut(&store, &effect, kind, &evidence, /*at_ms*/ 31).await;
            if step_projected {
                store
                    .record_taskflow_step(
                        &effect.run_id,
                        &effect.step_id,
                        effect.attempt,
                        &owner,
                        &effect.digest().expect("intent"),
                        &effect.payload_digest,
                        command_id,
                        &evidence,
                        match kind {
                            "succeeded" => TaskFlowStepObservation::Succeeded,
                            "failed" => TaskFlowStepObservation::Failed,
                            _ => TaskFlowStepObservation::Indeterminate,
                        },
                        /*now_ms*/ 31,
                    )
                    .await
                    .expect("step-only cut");
                if kind == "proven_absent" {
                    store
                        .reconcile_taskflow_step(
                            &effect.run_id,
                            &effect.step_id,
                            effect.attempt,
                            &owner,
                            &effect.digest().expect("intent"),
                            &effect.payload_digest,
                            "projection-cut-step-absent",
                            &evidence,
                            TaskFlowReconcileOutcome::Cancelled,
                            /*now_ms*/ 32,
                        )
                        .await
                        .expect("absence step-only cut");
                }
            }
            store.close().await;
            let reopened = AutomationStore::open(&fixture.layout)
                .await
                .expect("reopen cut");
            let pending = reopened
                .pending_authorized_taskflow_effects(/*limit*/ 1)
                .await
                .expect("terminal observation still scanned");
            assert_eq!(pending.len(), 1);
            assert_eq!(pending[0].attempt, effect.attempt);
            let run = reopened
                .taskflow_run(&effect.run_id)
                .await
                .expect("read")
                .expect("run");
            let cancelled = reopened
                .apply_taskflow_command(
                    &TaskFlowCommand::new(
                        &effect.run_id,
                        "cancel-partial-projection",
                        owner.clone(),
                        run.revision,
                        TaskFlowTransition::Cancel {
                            reason: "user_cancelled".to_string(),
                        },
                        /*now_ms*/ 33,
                    )
                    .expect("cancel"),
                )
                .await
                .expect("keep partial projection cancellation");
            assert_eq!(cancelled.state, TaskFlowRunState::Indeterminate);
            let recovery = if kind == "proven_absent" {
                AuthorizedEffectRecovery::ProvenAbsent {
                    proof_digest: evidence,
                }
            } else {
                AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                    outcome: if kind == "succeeded" {
                        AuthorizedEffectOutcome::Succeeded
                    } else {
                        AuthorizedEffectOutcome::Failed
                    },
                    receipt_digest: evidence,
                })
            };
            reopened
                .recover_authorized_taskflow_effect(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                    &owner,
                    recovery,
                    /*observed_at_ms*/ 1_500,
                )
                .await
                .expect("terminal projection recovery after lease expiry");
            let terminal = reopened
                .taskflow_run(&effect.run_id)
                .await
                .expect("read")
                .expect("run");
            assert_eq!(
                terminal.state,
                match kind {
                    "succeeded" => TaskFlowRunState::Succeeded,
                    "failed" => TaskFlowRunState::Failed,
                    _ => TaskFlowRunState::Cancelled,
                }
            );
            assert!(
                reopened
                    .pending_authorized_taskflow_effects(/*limit*/ 1)
                    .await
                    .expect("completed scan")
                    .is_empty()
            );
            #[cfg(feature = "taskflow-structural-qualification")]
            reopened
                .replay_taskflow_structural(&effect.run_id)
                .await
                .expect("partial-cut structural replay");
        }
    }
}

#[tokio::test]
async fn completion_receipt_failure_and_same_proof_new_attempt_use_exact_history() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    crash_at_dispatch_barrier(
        &store,
        &owner,
        &effect,
        &expected,
        "old-absence",
        /*now_ms*/ 30,
    )
    .await;
    let proof = Sha256Digest::for_bytes(b"provider-absence-proof-can-be-reused");
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(SqliteConnectOptions::new().filename(store.path()))
        .await
        .expect("test SQL");
    sqlx::query("CREATE TRIGGER test_fail_projection BEFORE INSERT ON taskflow_effect_projection_receipts BEGIN SELECT RAISE(ABORT, 'test failure before completion receipt'); END")
        .execute(&pool).await.expect("marker failure cut");
    assert!(matches!(
        store
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner,
                AuthorizedEffectRecovery::ProvenAbsent {
                    proof_digest: proof.clone()
                },
                /*observed_at_ms*/ 31,
            )
            .await,
        Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Unavailable))
    ));
    assert_eq!(
        store
            .taskflow_run(&effect.run_id)
            .await
            .expect("read")
            .expect("run")
            .state,
        TaskFlowRunState::Queued
    );
    sqlx::query("DROP TRIGGER test_fail_projection")
        .execute(&pool)
        .await
        .expect("release marker failure");
    pool.close().await;

    let mut next_owner = owner.clone();
    next_owner.generation += 1;
    next_owner.fencing_token = "next-effect-fence".to_string();
    let claimed = store
        .claim_taskflow_run(
            &effect.run_id,
            &next_owner,
            /*now_ms*/ 100,
            /*lease_ms*/ 1_000,
        )
        .await
        .expect("next owner");
    store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &effect.run_id,
                "next-effect-start",
                next_owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                /*now_ms*/ 101,
            )
            .expect("start"),
        )
        .await
        .expect("next run");
    let before = store
        .taskflow_run(&effect.run_id)
        .await
        .expect("read")
        .expect("run");
    let pending = store
        .pending_authorized_taskflow_effects(/*limit*/ 1)
        .await
        .expect("old completion cut scanned");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].attempt, 1);
    store
        .recover_authorized_taskflow_effect(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &owner,
            AuthorizedEffectRecovery::ProvenAbsent {
                proof_digest: proof.clone(),
            },
            /*observed_at_ms*/ 102,
        )
        .await
        .expect("backfill exact old projection without requeueing current run");
    assert_eq!(
        store
            .taskflow_run(&effect.run_id)
            .await
            .expect("read")
            .expect("run"),
        before
    );

    let mut next_effect = effect.clone();
    next_effect.attempt += 1;
    let next_intent = next_effect.digest().expect("new intent");
    store
        .prepare_taskflow_step(
            &next_effect.run_id,
            &next_effect.step_id,
            next_effect.attempt,
            &next_owner,
            &next_intent,
            &next_effect.payload_digest,
            "prepare-next-effect",
            /*now_ms*/ 103,
        )
        .await
        .expect("next prepare");
    store
        .claim_taskflow_step(
            &next_effect.run_id,
            &next_effect.step_id,
            next_effect.attempt,
            &next_owner,
            &next_intent,
            &next_effect.payload_digest,
            "claim-next-effect",
            /*now_ms*/ 104,
        )
        .await
        .expect("next claim");
    crash_at_dispatch_barrier(
        &store,
        &next_owner,
        &next_effect,
        &binding(&next_effect),
        "next-absence",
        /*now_ms*/ 105,
    )
    .await;
    persist_terminal_cut(
        &store,
        &next_effect,
        "proven_absent",
        &proof,
        /*at_ms*/ 106,
    )
    .await;
    store
        .record_taskflow_step(
            &next_effect.run_id,
            &next_effect.step_id,
            next_effect.attempt,
            &next_owner,
            &next_intent,
            &next_effect.payload_digest,
            "next-absence",
            &proof,
            TaskFlowStepObservation::Indeterminate,
            /*now_ms*/ 106,
        )
        .await
        .expect("next step-only cut");
    store
        .reconcile_taskflow_step(
            &next_effect.run_id,
            &next_effect.step_id,
            next_effect.attempt,
            &next_owner,
            &next_intent,
            &next_effect.payload_digest,
            "next-step-absence",
            &proof,
            TaskFlowReconcileOutcome::Cancelled,
            /*now_ms*/ 107,
        )
        .await
        .expect("next absence step");
    let run = store
        .taskflow_run(&effect.run_id)
        .await
        .expect("read")
        .expect("run");
    let pending_cancel = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &effect.run_id,
                "cancel-next-partial",
                next_owner.clone(),
                run.revision,
                TaskFlowTransition::Cancel {
                    reason: "user_cancelled".to_string(),
                },
                /*now_ms*/ 108,
            )
            .expect("cancel"),
        )
        .await
        .expect("old same-proof event cannot prove next attempt complete");
    assert_eq!(pending_cancel.state, TaskFlowRunState::Indeterminate);
    let pending = store
        .pending_authorized_taskflow_effects(/*limit*/ 1)
        .await
        .expect("only next attempt remains");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].attempt, 2);
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen same-proof cut");
    reopened
        .recover_authorized_taskflow_effect(
            &next_effect.run_id,
            &next_effect.step_id,
            next_effect.attempt,
            &next_owner,
            AuthorizedEffectRecovery::ProvenAbsent {
                proof_digest: proof,
            },
            /*observed_at_ms*/ 1_500,
        )
        .await
        .expect("settle next cancellation");
    assert!(
        reopened
            .pending_authorized_taskflow_effects(/*limit*/ 1)
            .await
            .expect("scan drained")
            .is_empty()
    );
}

#[tokio::test]
async fn forged_completion_receipt_cannot_hide_unprojected_effect_on_open() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    crash_at_dispatch_barrier(
        &store,
        &owner,
        &effect,
        &expected,
        "forged-completion",
        /*now_ms*/ 30,
    )
    .await;
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(SqliteConnectOptions::new().filename(store.path()))
        .await
        .expect("test SQL");
    sqlx::query(
        "INSERT INTO taskflow_effect_projection_receipts
         (owner_agent_id, run_id, step_id, attempt, observation, evidence_digest, projected_at_ms)
         VALUES (?, ?, ?, ?, 'succeeded', ?, 31)",
    )
    .bind(AGENT_ID)
    .bind(&effect.run_id)
    .bind(&effect.step_id)
    .bind(i64::from(effect.attempt))
    .bind(Sha256Digest::for_bytes(b"not-real-projection").as_str())
    .execute(&pool)
    .await
    .expect("hostile legacy completion row");
    pool.close().await;
    store.close().await;
    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(AutomationError::Corrupt)
    ));
}
