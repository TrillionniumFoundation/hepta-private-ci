use super::*;
use codex_hepta_automation::TaskFlowCommandStatus;
use codex_hepta_automation::TaskFlowError;

#[tokio::test]
async fn cancelled_or_expired_runs_cannot_dispatch_but_keep_historical_step_reads() {
    for cancelled in [true, false] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        let (authority, signed, _authority_dir) =
            final_use(expected.clone(), "live-effect-admission");
        if cancelled {
            let run = store
                .taskflow_run(&effect.run_id)
                .await
                .expect("run read")
                .expect("run");
            store
                .apply_taskflow_command(
                    &TaskFlowCommand::new(
                        &effect.run_id,
                        "cancel-before-dispatch",
                        owner.clone(),
                        run.revision,
                        TaskFlowTransition::Cancel {
                            reason: "user_cancelled".to_string(),
                        },
                        /*now_ms*/ 30,
                    )
                    .expect("cancel command"),
                )
                .await
                .expect("cancel run");
        }
        let now_ms = if cancelled { 31 } else { 1_020 };
        let historical = store
            .read_taskflow_step(&effect.run_id, &effect.step_id, effect.attempt, &owner)
            .await
            .expect("historical step remains readable")
            .expect("step");
        assert_eq!(historical.state, TaskFlowStepState::Claimed);
        let mut sync_driver =
            RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"must-not-send");
        assert!(
            store
                .execute_authorized_taskflow_effect(
                    &authority,
                    &mut sync_driver,
                    &effect,
                    EFFECT_PAYLOAD,
                    &owner,
                    &signed,
                    &expected,
                    "dispatch-rejected",
                    now_ms,
                )
                .await
                .is_err()
        );
        assert_eq!(sync_driver.calls, 0);
        let adapter = RecordingProviderEffectAdapter::new(
            ProviderEffectDispatch::Unknown,
            ProviderEffectLookup::Unknown,
        );
        let mut async_driver =
            ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter)
                .expect("driver");
        assert!(
            store
                .execute_authorized_taskflow_effect_async(
                    &authority,
                    &mut async_driver,
                    &effect,
                    EFFECT_PAYLOAD,
                    &owner,
                    &signed,
                    &expected,
                    "dispatch-rejected",
                    now_ms,
                )
                .await
                .is_err()
        );
        assert_eq!(
            async_driver
                .adapter()
                .dispatch_calls
                .load(Ordering::Relaxed),
            0
        );
        assert!(
            store
                .pending_authorized_taskflow_effects(/*limit*/ 8)
                .await
                .expect("pending")
                .is_empty()
        );
        authority
            .claim(&signed, &expected)
            .expect("rejection must not burn final-use grant");
    }
}

#[tokio::test]
async fn cancel_after_provider_barrier_survives_restart_and_reconciles_without_redispatch() {
    for provider_absent in [false, true] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        let (authority, signed, _authority_dir) =
            final_use(expected.clone(), "cancel-after-barrier");
        let crash_store = store.clone();
        let crash_owner = owner.clone();
        let crash_effect = effect.clone();
        let crash_expected = expected.clone();
        let crashed = tokio::spawn(async move {
            crash_store
                .execute_authorized_taskflow_effect(
                    &authority,
                    &mut CrashAfterProviderContactDriver,
                    &crash_effect,
                    EFFECT_PAYLOAD,
                    &crash_owner,
                    &signed,
                    &crash_expected,
                    "cancel-pending-dispatch",
                    /*now_ms*/ 30,
                )
                .await
        })
        .await
        .expect_err("crash after durable provider barrier");
        assert!(crashed.is_panic());
        let run = store
            .taskflow_run(&effect.run_id)
            .await
            .expect("run read")
            .expect("run");
        let cancel = TaskFlowCommand::new(
            &effect.run_id,
            "cancel-pending-effect",
            owner.clone(),
            run.revision,
            TaskFlowTransition::Cancel {
                reason: "user_cancelled".to_string(),
            },
            /*now_ms*/ 31,
        )
        .expect("cancel command");
        let cancelled = store
            .apply_taskflow_command(&cancel)
            .await
            .expect("retain cancellation intent");
        assert_eq!(cancelled.state, TaskFlowRunState::Indeterminate);
        let pending_run = store
            .taskflow_run(&effect.run_id)
            .await
            .expect("read")
            .expect("run");
        assert!(pending_run.cancel_requested);
        #[cfg(feature = "taskflow-structural-qualification")]
        store
            .replay_taskflow_structural(&effect.run_id)
            .await
            .expect("pending cancellation remains structurally replayable");
        store.close().await;
        let reopened = AutomationStore::open(&fixture.layout)
            .await
            .expect("reopen pending cancellation");
        let replay = reopened
            .apply_taskflow_command(&cancel)
            .await
            .expect("cancel retry is idempotent");
        assert_eq!(replay.status, TaskFlowCommandStatus::AlreadyApplied);
        assert_eq!(replay.state, TaskFlowRunState::Indeterminate);
        let recovery = if provider_absent {
            AuthorizedEffectRecovery::ProvenAbsent {
                proof_digest: Sha256Digest::for_bytes(b"provider-proved-absence"),
            }
        } else {
            AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: Sha256Digest::for_bytes(b"provider-proved-success"),
            })
        };
        reopened
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner,
                recovery.clone(),
                /*observed_at_ms*/ 1_500,
            )
            .await
            .expect("reconcile after owner lease expiry");
        let terminal = reopened
            .taskflow_run(&effect.run_id)
            .await
            .expect("read")
            .expect("run");
        assert_eq!(
            terminal.state,
            if provider_absent {
                TaskFlowRunState::Cancelled
            } else {
                TaskFlowRunState::Succeeded
            }
        );
        assert!(terminal.cancel_requested);
        #[cfg(feature = "taskflow-structural-qualification")]
        reopened
            .replay_taskflow_structural(&effect.run_id)
            .await
            .expect("provider terminality remains structurally replayable");
        reopened
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner,
                recovery,
                /*observed_at_ms*/ 1_501,
            )
            .await
            .expect("terminal evidence retry is idempotent");
        let repeated = reopened
            .apply_taskflow_command(&cancel)
            .await
            .expect("original cancel still idempotent after reconciliation");
        assert_eq!(repeated.status, TaskFlowCommandStatus::AlreadyApplied);
        assert_eq!(repeated.state, terminal.state);
        assert!(
            reopened
                .pending_authorized_taskflow_effects(/*limit*/ 8)
                .await
                .expect("pending")
                .is_empty()
        );
    }
}

#[tokio::test]
async fn ambiguous_legacy_provider_keys_are_rejected_before_new_dispatch() {
    let mut first = intent();
    first.run_id = "a:b".to_string();
    first.step_id = "c".to_string();
    let mut second = intent();
    second.run_id = "a".to_string();
    second.step_id = "b:c".to_string();
    assert_ne!(
        first.digest().expect("first intent"),
        second.digest().expect("second intent")
    );
    assert_eq!(
        format!("taskflow:{}:{}", first.run_id, first.step_id),
        format!("taskflow:{}:{}", second.run_id, second.step_id)
    );
    for effect in [first, second] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store_for(&fixture, effect).await;
        let (authority, signed, _authority_dir) =
            final_use(expected.clone(), "ambiguous-provider-key");
        let mut sync_driver =
            RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"must-not-send");
        assert!(matches!(
            store
                .execute_authorized_taskflow_effect(
                    &authority,
                    &mut sync_driver,
                    &effect,
                    EFFECT_PAYLOAD,
                    &owner,
                    &signed,
                    &expected,
                    "ambiguous-key-dispatch",
                    /*now_ms*/ 30,
                )
                .await,
            Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Invalid(_)))
        ));
        assert_eq!(sync_driver.calls, 0);
        let adapter = RecordingProviderEffectAdapter::new(
            ProviderEffectDispatch::Unknown,
            ProviderEffectLookup::Unknown,
        );
        let mut async_driver =
            ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter)
                .expect("driver");
        assert!(matches!(
            store
                .execute_authorized_taskflow_effect_async(
                    &authority,
                    &mut async_driver,
                    &effect,
                    EFFECT_PAYLOAD,
                    &owner,
                    &signed,
                    &expected,
                    "ambiguous-key-dispatch",
                    /*now_ms*/ 30,
                )
                .await,
            Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Invalid(_)))
        ));
        assert_eq!(
            async_driver
                .adapter()
                .dispatch_calls
                .load(Ordering::Relaxed),
            0
        );
        authority
            .claim(&signed, &expected)
            .expect("ambiguous identity did not burn grant");
    }
}
