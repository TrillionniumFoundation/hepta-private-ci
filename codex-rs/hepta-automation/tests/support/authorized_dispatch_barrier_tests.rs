use super::*;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;

async fn preclaim_second(
    store: &AutomationStore,
    owner: &TaskFlowFence,
    first: &AuthorizedEffectIntent,
) -> AuthorizedEffectIntent {
    let mut second = first.clone();
    second.attempt = 2;
    let digest = second.digest().expect("second intent");
    store
        .prepare_taskflow_step(
            &second.run_id,
            &second.step_id,
            2,
            owner,
            &digest,
            &second.payload_digest,
            "preclaim-second-prepare",
            24,
        )
        .await
        .expect("prepare second before first dispatch");
    store
        .claim_taskflow_step(
            &second.run_id,
            &second.step_id,
            2,
            owner,
            &digest,
            &second.payload_digest,
            "preclaim-second-claim",
            25,
        )
        .await
        .expect("preclaim second before first dispatch");
    second
}

#[tokio::test]
async fn taskflow_dispatch_barrier_preclaimed_attempt_cannot_repeat_unknown_or_accepted() {
    for accepted in [false, true] {
        let fixture = Fixture::new();
        let (store, owner, first, expected) = prepared_effect_store(&fixture).await;
        let second = preclaim_second(&store, &owner, &first).await;
        let dispatch = if accepted {
            ProviderEffectDispatch::Ack(provider_ack(
                &first,
                b"original-operation",
                ProviderEffectAckStatus::Accepted,
            ))
        } else {
            ProviderEffectDispatch::Unknown
        };
        let mut driver = ProviderEffectTaskFlowDriver::new(
            first.destination_id.clone(),
            RecordingProviderEffectAdapter::new(dispatch, ProviderEffectLookup::Unknown),
        )
        .expect("driver");
        let (authority, signed, _dir) = final_use(expected.clone(), "preclaimed-first");
        store
            .execute_authorized_taskflow_effect_async(
                &authority,
                &mut driver,
                AuthorizedEffectExecutionInput {
                    intent: &first,
                    wire_payload: EFFECT_PAYLOAD,
                    fence: &owner,
                    signed_grant: &signed,
                    expected_binding: &expected,
                    command_id: "preclaimed-first-dispatch",
                    now_ms: 30,
                },
            )
            .await
            .expect("first becomes indeterminate");
        let expected = binding(&second);
        let (authority, signed, _second_dir) = final_use(expected.clone(), "preclaimed-second");
        assert!(
            store
                .execute_authorized_taskflow_effect_async(
                    &authority,
                    &mut driver,
                    AuthorizedEffectExecutionInput {
                        intent: &second,
                        wire_payload: EFFECT_PAYLOAD,
                        fence: &owner,
                        signed_grant: &signed,
                        expected_binding: &expected,
                        command_id: "preclaimed-second-dispatch",
                        now_ms: 31,
                    },
                )
                .await
                .is_err()
        );
        assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 1);
        assert_eq!(
            store
                .authorized_taskflow_effect_attempt(&first.run_id, &first.step_id, 2)
                .await
                .expect("no half-committed attempt"),
            None
        );
        store.close().await;
        let reopened = AutomationStore::open(&fixture.layout)
            .await
            .expect("denial preserves reopen");
        assert_eq!(
            reopened
                .pending_authorized_taskflow_effects(8)
                .await
                .expect("original pending")
                .len(),
            1
        );
    }
}

struct PausedAdapter {
    entered: std::sync::Arc<Notify>,
    release: std::sync::Arc<Notify>,
    calls: AtomicUsize,
    result: ProviderEffectDispatch,
}

impl ProviderEffectAdapter for PausedAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::Relaxed);
            self.entered.notify_one();
            self.release.notified().await;
            self.result.clone()
        })
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async { ProviderEffectLookup::Unknown })
    }
}

#[tokio::test]
async fn taskflow_dispatch_barrier_preclaimed_race_allows_one_physical_contact() {
    let fixture = Fixture::new();
    let (store, owner, first, expected_first) = prepared_effect_store(&fixture).await;
    let second = preclaim_second(&store, &owner, &first).await;
    let expected_second = binding(&second);
    let (authority_first, signed_first, _dir_first) =
        final_use(expected_first.clone(), "racing-first");
    let (authority_second, signed_second, _dir_second) =
        final_use(expected_second.clone(), "racing-second");
    let entered = std::sync::Arc::new(Notify::new());
    let release = std::sync::Arc::new(Notify::new());
    let mut first_driver = ProviderEffectTaskFlowDriver::new(
        first.destination_id.clone(),
        PausedAdapter {
            entered: entered.clone(),
            release: release.clone(),
            calls: AtomicUsize::new(0),
            result: ProviderEffectDispatch::Unknown,
        },
    )
    .expect("paused provider");
    let mut second_driver = ProviderEffectTaskFlowDriver::new(
        second.destination_id.clone(),
        RecordingProviderEffectAdapter::new(
            ProviderEffectDispatch::Unknown,
            ProviderEffectLookup::Unknown,
        ),
    )
    .expect("second provider");
    let first_dispatch = store.execute_authorized_taskflow_effect_async(
        &authority_first,
        &mut first_driver,
        AuthorizedEffectExecutionInput {
            intent: &first,
            wire_payload: EFFECT_PAYLOAD,
            fence: &owner,
            signed_grant: &signed_first,
            expected_binding: &expected_first,
            command_id: "racing-first-dispatch",
            now_ms: 30,
        },
    );
    let second_dispatch = async {
        entered.notified().await;
        let result = store
            .execute_authorized_taskflow_effect_async(
                &authority_second,
                &mut second_driver,
                AuthorizedEffectExecutionInput {
                    intent: &second,
                    wire_payload: EFFECT_PAYLOAD,
                    fence: &owner,
                    signed_grant: &signed_second,
                    expected_binding: &expected_second,
                    command_id: "racing-second-dispatch",
                    now_ms: 31,
                },
            )
            .await;
        release.notify_one();
        result
    };
    let (first_result, second_result) = tokio::time::timeout(Duration::from_secs(10), async {
        tokio::join!(first_dispatch, second_dispatch)
    })
    .await
    .expect("bounded dispatch race");
    assert!(first_result.is_ok());
    assert!(second_result.is_err());
    assert_eq!(
        (
            first_driver.adapter().calls.load(Ordering::Relaxed),
            second_driver
                .adapter()
                .dispatch_calls
                .load(Ordering::Relaxed)
        ),
        (1, 0)
    );
    assert_eq!(
        store
            .authorized_taskflow_effect_attempt(&first.run_id, &first.step_id, 2)
            .await
            .expect("second barrier absent"),
        None
    );
    store.close().await;
    AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen raced history");
}

#[tokio::test]
async fn taskflow_dispatch_barrier_post_send_cancel_retains_ack_without_redispatch() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _dir) = final_use(expected.clone(), "cancel-after-send");
    let completed = provider_ack(
        &effect,
        b"completed-before-local-cancel-observation",
        ProviderEffectAckStatus::Completed,
    );
    let entered = std::sync::Arc::new(Notify::new());
    let release = std::sync::Arc::new(Notify::new());
    let mut driver = ProviderEffectTaskFlowDriver::new(
        effect.destination_id.clone(),
        PausedAdapter {
            entered: entered.clone(),
            release: release.clone(),
            calls: AtomicUsize::new(0),
            result: ProviderEffectDispatch::Ack(completed.clone()),
        },
    )
    .expect("paused provider");
    let dispatch = store.execute_authorized_taskflow_effect_async(
        &authority,
        &mut driver,
        AuthorizedEffectExecutionInput {
            intent: &effect,
            wire_payload: EFFECT_PAYLOAD,
            fence: &owner,
            signed_grant: &signed,
            expected_binding: &expected,
            command_id: "cancel-after-send-dispatch",
            now_ms: 30,
        },
    );
    let cancellation = async {
        entered.notified().await;
        let run = store
            .taskflow_run(&effect.run_id)
            .await
            .expect("run")
            .expect("present");
        let result = store
            .apply_taskflow_command(
                &TaskFlowCommand::new(
                    &effect.run_id,
                    "cancel-after-physical-contact",
                    owner.clone(),
                    run.revision,
                    TaskFlowTransition::Cancel {
                        reason: "cancelled after physical contact".to_string(),
                    },
                    31,
                )
                .expect("cancel command"),
            )
            .await;
        release.notify_one();
        result
    };
    let (dispatch_result, cancel_result) = tokio::time::timeout(Duration::from_secs(10), async {
        tokio::join!(dispatch, cancellation)
    })
    .await
    .expect("bounded cancel and ACK race");
    cancel_result.expect("legitimate cancellation");
    assert!(
        dispatch_result.is_err(),
        "cancelled TaskFlow must not advance"
    );
    assert_eq!(driver.adapter().calls.load(Ordering::Relaxed), 1);
    let retained = store
        .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, 1)
        .await
        .expect("retained physical fact")
        .expect("original attempt");
    assert_eq!(retained.provider_ack, Some(completed.clone()));
    assert_eq!(
        store
            .taskflow_run(&effect.run_id)
            .await
            .expect("run")
            .expect("present")
            .state,
        TaskFlowRunState::Cancelled
    );
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen after late ACK");
    assert_eq!(
        reopened
            .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, 1)
            .await
            .expect("retained ACK after reopen")
            .expect("original attempt")
            .provider_ack,
        Some(completed)
    );
    let (authority, signed, _retry_dir) = final_use(expected.clone(), "fresh-grant-after-cancel");
    let mut retry = ProviderEffectTaskFlowDriver::new(
        effect.destination_id.clone(),
        RecordingProviderEffectAdapter::new(
            ProviderEffectDispatch::Unknown,
            ProviderEffectLookup::Unknown,
        ),
    )
    .expect("retry fixture");
    assert!(
        reopened
            .execute_authorized_taskflow_effect_async(
                &authority,
                &mut retry,
                AuthorizedEffectExecutionInput {
                    intent: &effect,
                    wire_payload: EFFECT_PAYLOAD,
                    fence: &owner,
                    signed_grant: &signed,
                    expected_binding: &expected,
                    command_id: "cancel-after-send-dispatch",
                    now_ms: 32,
                },
            )
            .await
            .is_err()
    );
    assert_eq!(retry.adapter().dispatch_calls.load(Ordering::Relaxed), 0);
}

#[tokio::test]
async fn taskflow_dispatch_barrier_cancelled_or_expired_claim_never_contacts_provider() {
    for cancelled in [false, true] {
        for asynchronous in [false, true] {
            let fixture = Fixture::new();
            let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
            if cancelled {
                let run = store
                    .taskflow_run(&effect.run_id)
                    .await
                    .expect("run")
                    .expect("present");
                store
                    .apply_taskflow_command(
                        &TaskFlowCommand::new(
                            &effect.run_id,
                            "cancel-before-contact",
                            owner.clone(),
                            run.revision,
                            TaskFlowTransition::Cancel {
                                reason: "explicit cancellation".to_string(),
                            },
                            24,
                        )
                        .expect("cancel command"),
                    )
                    .await
                    .expect("legitimate cancellation");
            }
            let (authority, signed, _dir) = final_use(expected.clone(), "stale-dispatch");
            let input = AuthorizedEffectExecutionInput {
                intent: &effect,
                wire_payload: EFFECT_PAYLOAD,
                fence: &owner,
                signed_grant: &signed,
                expected_binding: &expected,
                command_id: "stale-dispatch",
                now_ms: if cancelled { 30 } else { 2_000 },
            };
            if asynchronous {
                let mut driver = ProviderEffectTaskFlowDriver::new(
                    effect.destination_id.clone(),
                    RecordingProviderEffectAdapter::new(
                        ProviderEffectDispatch::Unknown,
                        ProviderEffectLookup::Unknown,
                    ),
                )
                .expect("async provider");
                assert!(
                    store
                        .execute_authorized_taskflow_effect_async(&authority, &mut driver, input)
                        .await
                        .is_err()
                );
                assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 0);
            } else {
                let mut driver =
                    RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"stale");
                assert!(
                    store
                        .execute_authorized_taskflow_effect(&authority, &mut driver, input)
                        .await
                        .is_err()
                );
                assert_eq!(driver.calls, 0);
            }
            assert_eq!(
                store
                    .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, 1)
                    .await
                    .expect("no stale barrier"),
                None
            );
            store.close().await;
            AutomationStore::open(&fixture.layout)
                .await
                .expect("reopen after stale denial");
        }
    }
}
