use super::*;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use tokio::sync::Notify;

#[derive(Clone)]
struct PausedProvider {
    entered: Arc<Notify>,
    release: Arc<Notify>,
    contacts: Arc<AtomicUsize>,
    accepted: ProviderEffectAck,
    dispatch_ack: ProviderEffectAck,
}

impl ProviderEffectAdapter for PausedProvider {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async {
            ProviderEffectDispatch::NotDispatched {
                reason_code: "wire_required".to_string(),
            }
        })
    }

    fn dispatch_with_payload<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        wire: &'a [u8],
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async move {
            assert_eq!(
                (&intent.key, &intent.payload_sha256, wire),
                (
                    &self.accepted.key,
                    &self.accepted.payload_sha256,
                    EFFECT_PAYLOAD
                )
            );
            self.contacts.fetch_add(1, Ordering::Relaxed);
            self.entered.notify_one();
            self.release.notified().await;
            ProviderEffectDispatch::Ack(self.dispatch_ack.clone())
        })
    }

    fn lookup<'a>(
        &'a self,
        key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async move {
            assert_eq!(key, &self.accepted.key);
            ProviderEffectLookup::Ack(self.accepted.clone())
        })
    }
}

#[derive(Clone, Copy)]
enum LateReply {
    Completed,
    CompletedAfterUnknownLookup,
    CompletedAfterCancel,
    DifferentOperation,
    Rejected,
}

async fn late_dispatch_after_lookup(reply: LateReply) {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let accepted = provider_ack(
        &effect,
        b"in-flight-operation",
        ProviderEffectAckStatus::Accepted,
    );
    let terminal = match reply {
        LateReply::Completed
        | LateReply::CompletedAfterUnknownLookup
        | LateReply::CompletedAfterCancel => provider_ack(
            &effect,
            b"in-flight-operation",
            ProviderEffectAckStatus::Completed,
        ),
        LateReply::DifferentOperation => provider_ack(
            &effect,
            b"substituted-in-flight-operation",
            ProviderEffectAckStatus::Completed,
        ),
        LateReply::Rejected => provider_ack(
            &effect,
            b"in-flight-operation",
            ProviderEffectAckStatus::Rejected,
        ),
    };
    // No status result is authority to create a provider-contact barrier.
    assert!(
        store
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner,
                AuthorizedEffectRecovery::Observed(
                    AuthorizedEffectProviderReceipt::from_provider_ack(
                        accepted.clone(),
                        ProviderEffectAckSource::StatusLookup
                    )
                ),
                /*now_ms*/ 29
            )
            .await
            .is_err()
    );
    let adapter = PausedProvider {
        entered: Arc::new(Notify::new()),
        release: Arc::new(Notify::new()),
        contacts: Arc::new(AtomicUsize::new(0)),
        accepted: accepted.clone(),
        dispatch_ack: terminal.clone(),
    };
    let mut dispatch_driver =
        ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter.clone())
            .expect("dispatch driver");
    let lookup_driver =
        ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter.clone())
            .expect("lookup driver");
    let (authority, signed, _directory) = final_use(expected.clone(), "in-flight-late-ack");
    let dispatch = store.execute_authorized_taskflow_effect_async(
        &authority,
        &mut dispatch_driver,
        AuthorizedEffectExecutionInput {
            intent: &effect,
            wire_payload: EFFECT_PAYLOAD,
            fence: &owner,
            signed_grant: &signed,
            expected_binding: &expected,
            command_id: "in-flight-dispatch",
            now_ms: 30,
        },
    );
    let lookup = async {
        adapter.entered.notified().await;
        assert_eq!(adapter.contacts.load(Ordering::Relaxed), 1);
        if matches!(reply, LateReply::CompletedAfterUnknownLookup) {
            store
                .recover_authorized_taskflow_effect(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                    &owner,
                    AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                        outcome: AuthorizedEffectOutcome::Indeterminate,
                        receipt_digest: Sha256Digest::for_bytes(b"original-status-unknown"),
                        provider_ack: None,
                    }),
                    /*now_ms*/ 31,
                )
                .await
                .expect("retain original opaque uncertainty");
        }
        let pending = store
            .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("in-flight barrier")
            .expect("durable barrier exists before lookup");
        let AuthorizedProviderEffectLookup::Observed(receipt) =
            lookup_driver.lookup(&pending).await
        else {
            panic!("Accepted status");
        };
        let recovered = store
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner,
                AuthorizedEffectRecovery::Observed(receipt),
                /*now_ms*/ 31,
            )
            .await
            .expect("persist lookup before physical response");
        assert!(
            matches!(recovered, AuthorizedEffectRecoveryResult::Observed(receipt)
            if receipt.observation == Some(TaskFlowStepObservation::Indeterminate) && receipt.final_outcome.is_none())
        );
        if matches!(reply, LateReply::CompletedAfterCancel) {
            let run = store
                .taskflow_run(&effect.run_id)
                .await
                .expect("run")
                .expect("run exists");
            store
                .apply_taskflow_command(
                    &TaskFlowCommand::new(
                        &effect.run_id,
                        "cancel-before-late-completion",
                        owner.clone(),
                        run.revision,
                        TaskFlowTransition::Cancel {
                            reason: "cancel while physical ACK is pending".to_string(),
                        },
                        /*now_ms*/ 32,
                    )
                    .expect("cancel command"),
                )
                .await
                .expect("cancel before late physical ACK");
        }
        adapter.release.notify_one();
    };
    let (result, ()) = tokio::time::timeout(Duration::from_secs(10), async {
        tokio::join!(dispatch, lookup)
    })
    .await
    .expect("bounded in-flight ACK race");
    assert_eq!(adapter.contacts.load(Ordering::Relaxed), 1);
    assert_eq!(authority.capacity().expect("capacity").used_nonces, 1);
    match reply {
        LateReply::Completed
        | LateReply::CompletedAfterUnknownLookup
        | LateReply::CompletedAfterCancel => {
            if matches!(reply, LateReply::CompletedAfterCancel) {
                assert!(
                    result.is_err(),
                    "a physical fact cannot override cancellation"
                );
            } else {
                let receipt =
                    result.expect("the original dispatch's late completion must be retained");
                assert_eq!(
                    (receipt.state, receipt.observation, receipt.final_outcome),
                    (
                        TaskFlowStepState::Reconciled,
                        Some(TaskFlowStepObservation::Indeterminate),
                        Some(TaskFlowReconcileOutcome::Succeeded)
                    )
                );
            }
            let pool = database(&store).await;
            let (initial, initial_digest, final_json): (Option<String>, String, String) =
                sqlx::query_as(
                    "SELECT o.provider_receipt_json, o.evidence_digest, r.provider_receipt_json
                 FROM taskflow_effect_dispatch_observations o
                 JOIN taskflow_effect_dispatch_reconciliations r
                 ON r.owner_agent_id=o.owner_agent_id AND r.run_id=o.run_id
                 AND r.step_id=o.step_id AND r.attempt=o.attempt",
                )
                .fetch_one(&pool)
                .await
                .expect("append-only source-preserving facts");
            if matches!(reply, LateReply::CompletedAfterUnknownLookup) {
                assert_eq!(
                    (initial, initial_digest),
                    (
                        None,
                        Sha256Digest::for_bytes(b"original-status-unknown")
                            .as_str()
                            .to_string()
                    )
                );
            } else {
                assert_eq!(
                    serde_json::from_str::<serde_json::Value>(
                        &initial.expect("initial Accepted JSON")
                    )
                    .expect("initial JSON"),
                    serde_json::json!({"schema_version":1,"source":"status_lookup","ack":accepted})
                );
                assert_eq!(
                    initial_digest,
                    AuthorizedEffectProviderReceipt::from_provider_ack(
                        accepted,
                        ProviderEffectAckSource::StatusLookup
                    )
                    .receipt_digest
                    .as_str()
                );
            }
            assert_eq!(
                serde_json::from_str::<serde_json::Value>(&final_json).expect("final JSON"),
                serde_json::json!({"schema_version":1,"source":"dispatch_response","ack":terminal})
            );
            pool.close().await;
        }
        LateReply::DifferentOperation | LateReply::Rejected => {
            assert!(result.is_err());
            let pending = store
                .pending_authorized_taskflow_effects(8)
                .await
                .expect("original binding retained");
            assert_eq!(pending.len(), 1);
            assert_eq!(pending[0].provider_ack, Some(accepted));
            let completed = provider_ack(
                &effect,
                b"in-flight-operation",
                ProviderEffectAckStatus::Completed,
            );
            store
                .recover_authorized_taskflow_effect(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                    &owner,
                    AuthorizedEffectRecovery::Observed(
                        AuthorizedEffectProviderReceipt::from_provider_ack(
                            completed,
                            ProviderEffectAckSource::StatusLookup,
                        ),
                    ),
                    /*now_ms*/ 40,
                )
                .await
                .expect("negative control cannot poison valid later reconciliation");
        }
    }
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen interleaved provider facts");
    let terminal = reopened
        .read_terminal_authorized_taskflow_effect(&effect.run_id, &effect.step_id, effect.attempt)
        .await
        .expect("terminal fact");
    if matches!(reply, LateReply::CompletedAfterCancel) {
        assert_eq!(terminal, None);
        assert_eq!(
            reopened
                .taskflow_run(&effect.run_id)
                .await
                .expect("run")
                .expect("run exists")
                .state,
            TaskFlowRunState::Cancelled
        );
        let mut retry = ProviderEffectTaskFlowDriver::new(
            effect.destination_id.clone(),
            RecordingProviderEffectAdapter::new(
                ProviderEffectDispatch::Unknown,
                ProviderEffectLookup::Unknown,
            ),
        )
        .expect("fresh driver");
        let (authority, fresh, _retry_directory) =
            final_use(expected.clone(), "after-late-completion-cancel");
        assert!(
            reopened
                .execute_authorized_taskflow_effect_async(
                    &authority,
                    &mut retry,
                    AuthorizedEffectExecutionInput {
                        intent: &effect,
                        wire_payload: EFFECT_PAYLOAD,
                        fence: &owner,
                        signed_grant: &fresh,
                        expected_binding: &expected,
                        command_id: "in-flight-dispatch",
                        now_ms: 45,
                    }
                )
                .await
                .is_err()
        );
        assert_eq!(retry.adapter().dispatch_calls.load(Ordering::Relaxed), 0);
    } else {
        assert_eq!(
            terminal.expect("completed occurrence").final_outcome,
            Some(TaskFlowReconcileOutcome::Succeeded)
        );
    }
    assert_eq!(adapter.contacts.load(Ordering::Relaxed), 1);
}

#[tokio::test]
async fn taskflow_provider_receipt_late_dispatch_completion_after_lookup_is_retained() {
    late_dispatch_after_lookup(LateReply::Completed).await;
}

#[tokio::test]
async fn taskflow_provider_receipt_late_dispatch_preserves_original_unknown_and_cancellation() {
    late_dispatch_after_lookup(LateReply::CompletedAfterUnknownLookup).await;
    late_dispatch_after_lookup(LateReply::CompletedAfterCancel).await;
}

#[tokio::test]
async fn taskflow_provider_receipt_late_dispatch_cannot_replace_or_reject_accepted_operation() {
    late_dispatch_after_lookup(LateReply::DifferentOperation).await;
    late_dispatch_after_lookup(LateReply::Rejected).await;
}

#[tokio::test]
async fn taskflow_provider_receipt_late_dispatch_reopen_requires_binding_from_same_attempt() {
    let fixture = Fixture::new();
    let started = start(&fixture, ProviderEffectDispatch::Unknown).await;
    let accepted = provider_ack(
        &started.effect,
        b"prior-attempt-operation",
        ProviderEffectAckStatus::Accepted,
    );
    recover(
        &started,
        AuthorizedEffectProviderReceipt::from_provider_ack(
            accepted,
            ProviderEffectAckSource::StatusLookup,
        ),
    )
    .await
    .expect("bind the actual first attempt");
    let completed = provider_ack(
        &started.effect,
        b"prior-attempt-operation",
        ProviderEffectAckStatus::Completed,
    );
    let evidence = AuthorizedEffectProviderReceipt::from_provider_ack(
        completed.clone(),
        ProviderEffectAckSource::DispatchResponse,
    )
    .receipt_digest;
    let json = format!(
        "{{\"schema_version\":1,\"source\":\"dispatch_response\",\"ack\":{}}}",
        serde_json::to_string(&completed).expect("canonical receipt")
    );
    let pool = database(&started.store).await;
    sqlx::query(
        "INSERT INTO taskflow_effect_dispatch_attempts
         (owner_agent_id, run_id, step_id, attempt, intent_digest, payload_digest, binding_digest,
          destination_id, authority_epoch, grant_id, grant_nonce_digest, record_command_id,
          started_at_ms, provider_effect_key, wire_payload, append_profile_version)
         SELECT owner_agent_id, run_id, step_id, 2, intent_digest, payload_digest, binding_digest,
                destination_id, authority_epoch, 'later-import', ?, 'later-import',
                started_at_ms, provider_effect_key, wire_payload, 1 FROM taskflow_effect_dispatch_attempts WHERE attempt=1"
    ).bind(Sha256Digest::for_bytes(b"different-attempt-nonce").as_str()).execute(&pool).await.expect("import later historical attempt");
    sqlx::query(
        "INSERT INTO taskflow_effect_dispatch_observations
         (owner_agent_id, run_id, step_id, attempt, observation, evidence_digest, observed_at_ms, append_profile_version)
         SELECT owner_agent_id, run_id, step_id, 2, observation, evidence_digest, observed_at_ms, 1
         FROM taskflow_effect_dispatch_observations WHERE attempt=1",
    )
    .execute(&pool)
    .await
    .expect("later uncertainty");
    let before = started
        .store
        .authorized_taskflow_effect_attempt(
            &started.effect.run_id,
            &started.effect.step_id,
            /*attempt*/ 2,
        )
        .await
        .expect("imported history is readable before the bad reconciliation")
        .expect("imported attempt exists");
    assert_eq!(
        (before.attempt, before.provider_ack),
        (
            2,
            Some(provider_ack(
                &started.effect,
                b"prior-attempt-operation",
                ProviderEffectAckStatus::Accepted
            ))
        )
    );
    sqlx::query(
        "INSERT INTO taskflow_effect_dispatch_reconciliations
         (owner_agent_id, run_id, step_id, attempt, observation, evidence_digest, observed_at_ms, provider_receipt_json, append_profile_version)
         SELECT owner_agent_id, run_id, step_id, 2, 'succeeded', ?, 50, ?, 1
         FROM taskflow_effect_dispatch_attempts WHERE attempt=1"
    ).bind(evidence.as_str()).bind(json).execute(&pool).await.expect("import same-ID receipt from wrong attempt");
    pool.close().await;
    started.store.close().await;
    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(codex_hepta_automation::AutomationError::Corrupt)
    ));
}
