use super::*;
use codex_hepta_automation::AuthorizedProviderDispatchStatus;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn lookup_acceptance_survives_reopen_and_cannot_become_rejection_or_absence() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "lookup-admission");
    let ack = |status, operation: &[u8]| {
        ProviderEffectAck::new(
            provider_key(&effect),
            effect.payload_digest.clone(),
            Sha256Digest::for_bytes(operation),
            status,
        )
    };
    let adapter = RecordingProviderEffectAdapter::new(
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::Ack(ack(ProviderEffectAckStatus::Accepted, b"first-operation")),
    );
    let mut driver =
        ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter).expect("driver");
    store
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "admission-dispatch",
            30,
        )
        .await
        .expect("dispatch unknown");
    let pending = store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending")
        .remove(0);
    assert_eq!(
        pending.provider_dispatch_status,
        Some(AuthorizedProviderDispatchStatus::Unknown)
    );
    assert_eq!(
        driver
            .lookup(&store, &pending, &owner, 40)
            .await
            .expect("accepted lookup"),
        AuthorizedProviderEffectLookup::Unresolved
    );
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let pending = reopened
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending")
        .remove(0);
    assert_eq!(
        pending.provider_dispatch_status,
        Some(AuthorizedProviderDispatchStatus::Accepted)
    );
    driver.adapter_mut().lookup_result = ProviderEffectLookup::Ack(ack(
        ProviderEffectAckStatus::Rejected,
        b"rejected-operation",
    ));
    assert_eq!(
        driver
            .lookup(&reopened, &pending, &owner, 50)
            .await
            .expect("rejected lookup quarantined"),
        AuthorizedProviderEffectLookup::Unresolved
    );
    assert!(matches!(
        reopened
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner,
                AuthorizedEffectRecovery::ProvenAbsent {
                    proof_digest: Sha256Digest::for_bytes(b"contradictory-absence")
                },
                51
            )
            .await,
        Err(AuthorizedEffectError::TaskFlow(
            codex_hepta_automation::TaskFlowError::Conflict(_)
        ))
    ));
    assert_eq!(
        reopened
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("still pending"),
        vec![pending.clone()]
    );
    // The quarantined producer contract permits authoritative completion with
    // a changed operation id; admission alone must not reject that refinement.
    driver.adapter_mut().lookup_result = ProviderEffectLookup::Ack(ack(
        ProviderEffectAckStatus::Completed,
        b"authoritative-operation",
    ));
    assert!(matches!(
        driver
            .lookup(&reopened, &pending, &owner, 60)
            .await
            .expect("completed lookup"),
        AuthorizedProviderEffectLookup::Observed(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Succeeded,
            ..
        })
    ));
    assert!(
        reopened
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("settled")
            .is_empty()
    );
    assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 1);
}

#[tokio::test]
async fn rejected_lookup_distinguishes_unknown_accepted_and_legacy_dispatch() {
    for initial in [
        Some(AuthorizedProviderDispatchStatus::Unknown),
        Some(AuthorizedProviderDispatchStatus::Accepted),
        None,
    ] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        let (authority, signed, _authority_dir) = final_use(expected.clone(), "initial-admission");
        let ack = |status| {
            ProviderEffectAck::new(
                provider_key(&effect),
                effect.payload_digest.clone(),
                Sha256Digest::for_bytes(b"operation"),
                status,
            )
        };
        let adapter = RecordingProviderEffectAdapter::new(
            if initial == Some(AuthorizedProviderDispatchStatus::Accepted) {
                ProviderEffectDispatch::Ack(ack(ProviderEffectAckStatus::Accepted))
            } else {
                ProviderEffectDispatch::Unknown
            },
            ProviderEffectLookup::Ack(ack(ProviderEffectAckStatus::Rejected)),
        );
        let mut driver = ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter)
            .expect("driver");
        if initial.is_some() {
            store
                .execute_authorized_taskflow_effect_async(
                    &authority,
                    &mut driver,
                    &effect,
                    EFFECT_PAYLOAD,
                    &owner,
                    &signed,
                    &expected,
                    "initial-dispatch",
                    30,
                )
                .await
                .expect("typed dispatch");
        } else {
            let mut legacy =
                RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"opaque-legacy");
            store
                .execute_authorized_taskflow_effect(
                    &authority,
                    &mut legacy,
                    &effect,
                    EFFECT_PAYLOAD,
                    &owner,
                    &signed,
                    &expected,
                    "initial-dispatch",
                    30,
                )
                .await
                .expect("opaque legacy dispatch");
        }
        let pending = store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("pending")
            .remove(0);
        assert_eq!(pending.provider_dispatch_status, initial);
        let result = driver
            .lookup(&store, &pending, &owner, 40)
            .await
            .expect("lookup");
        if initial == Some(AuthorizedProviderDispatchStatus::Unknown) {
            assert!(matches!(
                result,
                AuthorizedProviderEffectLookup::Observed(AuthorizedEffectProviderReceipt {
                    outcome: AuthorizedEffectOutcome::Failed,
                    ..
                })
            ));
            assert!(
                store
                    .pending_authorized_taskflow_effects(8)
                    .await
                    .expect("settled")
                    .is_empty()
            );
        } else {
            assert_eq!(result, AuthorizedProviderEffectLookup::Unresolved);
            assert_eq!(
                store
                    .pending_authorized_taskflow_effects(8)
                    .await
                    .expect("still pending"),
                vec![pending]
            );
            // A generic owner failure can mean an admitted execution failed;
            // only typed provider rejection is prohibited after acceptance.
            assert!(matches!(
                store
                    .recover_authorized_taskflow_effect(
                        &effect.run_id,
                        &effect.step_id,
                        effect.attempt,
                        &owner,
                        AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                            outcome: AuthorizedEffectOutcome::Failed,
                            receipt_digest: Sha256Digest::for_bytes(b"execution-failed")
                        }),
                        50
                    )
                    .await
                    .expect("execution failure"),
                AuthorizedEffectRecoveryResult::Observed(_)
            ));
        }
    }
}

#[tokio::test]
async fn existing_step_command_ids_reject_before_contact_and_preserve_grant() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "existing-step-command");
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"success");
    let mut async_driver = ContractBoundDriver {
        store: store.clone(),
        binding: Sha256Digest::for_bytes(b"command-guard-contract"),
        calls: 0,
    };
    for command_id in ["authorized-effect-prepare", "authorized-effect-claim"] {
        assert!(matches!(
            store
                .execute_authorized_taskflow_effect(
                    &authority,
                    &mut driver,
                    &effect,
                    EFFECT_PAYLOAD,
                    &owner,
                    &signed,
                    &expected,
                    command_id,
                    30
                )
                .await,
            Err(AuthorizedEffectError::TaskFlow(
                codex_hepta_automation::TaskFlowError::Conflict(_)
            ))
        ));
        assert_eq!(
            driver.calls, 0,
            "existing outbox command must reject before provider contact"
        );
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
                    command_id,
                    30
                )
                .await,
            Err(AuthorizedEffectError::TaskFlow(
                codex_hepta_automation::TaskFlowError::Conflict(_)
            ))
        ));
        assert_eq!(async_driver.calls, 0);
    }
    assert!(
        store
            .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("attempt read")
            .is_none()
    );
    store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut driver,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "fresh-effect-record",
            31,
        )
        .await
        .expect("rejected command must preserve grant for valid dispatch");
    assert_eq!(driver.calls, 1);
}

#[tokio::test]
async fn terminal_step_evidence_rejects_conflicting_recovery_without_poisoning_ledger() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "terminal-step-evidence");
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"unknown");
    store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut driver,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "terminal-step-dispatch",
            30,
        )
        .await
        .expect("dispatch");
    let terminal = Sha256Digest::for_bytes(b"independent-owner-terminal");
    store
        .reconcile_taskflow_step(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &owner,
            &effect.digest().expect("intent"),
            &effect.payload_digest,
            "independent-step-terminal",
            &terminal,
            TaskFlowReconcileOutcome::Succeeded,
            31,
        )
        .await
        .expect("settle step first");
    for (outcome, receipt_digest) in [
        (AuthorizedEffectOutcome::Failed, terminal.clone()),
        (
            AuthorizedEffectOutcome::Succeeded,
            Sha256Digest::for_bytes(b"substituted-evidence"),
        ),
    ] {
        assert!(matches!(
            store
                .recover_authorized_taskflow_effect(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                    &owner,
                    AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                        outcome,
                        receipt_digest,
                    }),
                    32
                )
                .await,
            Err(AuthorizedEffectError::TaskFlow(
                codex_hepta_automation::TaskFlowError::Conflict(_)
            ))
        ));
        assert_eq!(
            store
                .pending_authorized_taskflow_effects(1)
                .await
                .expect("pending")
                .len(),
            1
        );
    }
    let recovered = store
        .recover_authorized_taskflow_effect(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &owner,
            AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: terminal,
            }),
            33,
        )
        .await
        .expect("matching evidence remains recoverable");
    assert!(
        matches!(recovered, AuthorizedEffectRecoveryResult::Observed(receipt)
        if receipt.final_outcome == Some(TaskFlowReconcileOutcome::Succeeded))
    );
    assert_eq!(driver.calls, 1);
}

#[tokio::test]
async fn unpinned_bridge_cannot_observe_a_pinned_driver_attempt() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "pinned-driver-lookup");
    let mut pinned = ContractBoundDriver {
        store: store.clone(),
        binding: Sha256Digest::for_bytes(b"registered-provider-contract"),
        calls: 0,
    };
    store
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut pinned,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "pinned-dispatch",
            30,
        )
        .await
        .expect("pinned dispatch");
    let pending = store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending")
        .remove(0);
    let adapter = RecordingProviderEffectAdapter::new(
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::Ack(ProviderEffectAck::new(
            provider_key(&effect),
            effect.payload_digest.clone(),
            Sha256Digest::for_bytes(b"wrong-provider-operation"),
            ProviderEffectAckStatus::Completed,
        )),
    );
    let bridge =
        ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter).expect("bridge");
    assert_eq!(
        bridge
            .lookup(&store, &pending, &owner, 40)
            .await
            .expect("foreign contract remains unresolved"),
        AuthorizedProviderEffectLookup::Unresolved
    );
    assert!(
        bridge
            .adapter()
            .seen_key
            .lock()
            .expect("lookup key")
            .is_none(),
        "provider was never contacted"
    );
    let mut forged = pending.clone();
    forged.provider_contract_binding = None;
    assert_eq!(
        bridge
            .lookup(&store, &forged, &owner, 41)
            .await
            .expect("forged pin remains unresolved"),
        AuthorizedProviderEffectLookup::Unresolved
    );
    assert!(
        bridge
            .adapter()
            .seen_key
            .lock()
            .expect("lookup key")
            .is_none()
    );
    assert_eq!(
        store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("still pending"),
        vec![pending]
    );
}
