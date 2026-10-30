use super::*;
use pretty_assertions::assert_eq;

// Reproduce the old async namespace at the original synchronous owner seam.
// This driver persists and sends the old bytes before the upgraded reader runs;
// no newly dispatched v2 row is relabeled as a legacy occurrence.
struct LegacyTaskFlowDriver {
    before_contact: bool,
    sent: Vec<(ProviderEffectKey, Vec<u8>)>,
}

impl AuthorizedEffectDriver for LegacyTaskFlowDriver {
    fn recovery_key(
        &self,
        _owner_agent_id: &AgentId,
        intent: &AuthorizedEffectIntent,
    ) -> Result<ProviderEffectKey, AuthorizedEffectDriverError> {
        ProviderEffectKey::for_logical_effect(
            &intent.destination_id,
            &format!("taskflow:{}:{}", intent.run_id, intent.step_id),
        )
        .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)
    }

    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        assert_eq!(
            request.provider_effect_key,
            &self.recovery_key(request.owner_agent_id, request.intent)?
        );
        if self.before_contact {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        self.sent.push((
            request.provider_effect_key.clone(),
            request.wire_payload.to_vec(),
        ));
        Ok(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Indeterminate,
            receipt_digest: Sha256Digest::for_bytes(b"legacy-contact-lost-ack"),
            provider_ack: None,
        })
    }
}

#[tokio::test]
async fn taskflow_provider_identity_legacy_lookup_retains_original_key_wire_without_dispatch() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let mut legacy = LegacyTaskFlowDriver {
        before_contact: false,
        sent: Vec::new(),
    };
    let original_key = legacy
        .recovery_key(store.owner_agent_id(), &effect)
        .expect("legacy key");
    let (authority, signed, _directory) = final_use(expected.clone(), "legacy-lost-ack");
    store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut legacy,
            AuthorizedEffectExecutionInput {
                intent: &effect,
                wire_payload: EFFECT_PAYLOAD,
                fence: &owner,
                signed_grant: &signed,
                expected_binding: &expected,
                command_id: "legacy-dispatch",
                now_ms: 30,
            },
        )
        .await
        .expect("old physical dispatch");
    assert_eq!(
        legacy.sent,
        vec![(original_key.clone(), EFFECT_PAYLOAD.to_vec())]
    );
    assert_ne!(
        original_key,
        ProviderEffectKey::for_taskflow_v2(
            &effect.destination_id,
            store.owner_agent_id(),
            &effect.run_id,
            &effect.step_id
        )
        .expect("new key")
    );
    store.close().await;
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("upgrade reopen");
    let pending = store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("old pending")
        .remove(0);
    assert_eq!(
        (
            &pending.provider_effect_key,
            pending.wire_payload.as_deref()
        ),
        (&Some(original_key.clone()), Some(EFFECT_PAYLOAD))
    );
    let provider_intent = ProviderEffectIntent::new(original_key, effect.payload_digest.clone());
    let completed = completed_ack(&provider_intent);
    let adapter = RecordingProviderEffectAdapter::new(
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::Ack(completed),
    );
    let driver = ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter)
        .expect("upgraded driver");
    let AuthorizedProviderEffectLookup::Observed(receipt) = driver.lookup(&pending).await else {
        panic!("legacy lookup must preserve exact identity");
    };
    let terminal = store
        .recover_authorized_taskflow_effect(
            &effect.run_id,
            &effect.step_id,
            /*attempt*/ 1,
            &owner,
            AuthorizedEffectRecovery::Observed(receipt),
            /*now_ms*/ 40,
        )
        .await
        .expect("reconcile original occurrence");
    assert!(
        matches!(terminal, AuthorizedEffectRecoveryResult::Observed(receipt)
        if receipt.observation == Some(TaskFlowStepObservation::Indeterminate)
        && receipt.final_outcome == Some(TaskFlowReconcileOutcome::Succeeded))
    );
    assert_eq!(
        *driver.adapter().lookups.lock().expect("lookup capture"),
        vec![(provider_intent, Some(EFFECT_PAYLOAD.to_vec()))]
    );
    assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 0);
    store.close().await;
    AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen recovered legacy receipt");
}

#[derive(Clone, Copy)]
enum RetryMaterial {
    Original,
    ChangedPayload,
    ChangedDestination,
}

async fn legacy_absence_retry(material: RetryMaterial) {
    let fixture = Fixture::new();
    let (store, first_owner, mut effect, expected) = prepared_effect_store(&fixture).await;
    let mut legacy = LegacyTaskFlowDriver {
        before_contact: true,
        sent: Vec::new(),
    };
    let original_key = legacy
        .recovery_key(store.owner_agent_id(), &effect)
        .expect("legacy key");
    let (authority, signed, _directory) = final_use(expected.clone(), "legacy-before-contact");
    let initial = store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut legacy,
            AuthorizedEffectExecutionInput {
                intent: &effect,
                wire_payload: EFFECT_PAYLOAD,
                fence: &first_owner,
                signed_grant: &signed,
                expected_binding: &expected,
                command_id: "legacy-absent-dispatch",
                now_ms: 30,
            },
        )
        .await;
    assert!(matches!(
        initial,
        Err(AuthorizedEffectError::Driver(
            AuthorizedEffectDriverError::BeforeProviderContact
        ))
    ));
    assert!(legacy.sent.is_empty());
    store.close().await;
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen settled legacy absence");
    effect.attempt = 2;
    let wire: &[u8] = match material {
        RetryMaterial::Original => EFFECT_PAYLOAD,
        RetryMaterial::ChangedPayload => b"changed-effect-payload",
        RetryMaterial::ChangedDestination => {
            effect.destination_id = "provider:changed".to_string();
            EFFECT_PAYLOAD
        }
    };
    effect.payload_digest = Sha256Digest::for_bytes(wire);
    let second_owner = TaskFlowFence::new(
        store.owner_agent_id().clone(),
        "authorized-effect-owner",
        /*owner_epoch*/ 1,
        /*generation*/ 2,
        "legacy-retry-fence",
    )
    .expect("new fence");
    let claimed = store
        .claim_taskflow_run(
            &effect.run_id,
            &second_owner,
            /*now_ms*/ 40,
            /*lease_duration_ms*/ 1_000,
        )
        .await
        .expect("claim retry");
    store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &effect.run_id,
                "legacy-retry-start",
                second_owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                /*now_ms*/ 41,
            )
            .expect("start command"),
        )
        .await
        .expect("start retry");
    let digest = effect.digest().expect("retry digest");
    store
        .prepare_taskflow_step(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &second_owner,
            &digest,
            &effect.payload_digest,
            "legacy-retry-prepare",
            /*now_ms*/ 42,
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
            "legacy-retry-claim",
            /*now_ms*/ 43,
        )
        .await
        .expect("claim retry step");
    let provider_intent =
        ProviderEffectIntent::new(original_key.clone(), effect.payload_digest.clone());
    let adapter = RecordingProviderEffectAdapter::new(
        ProviderEffectDispatch::Ack(completed_ack(&provider_intent)),
        ProviderEffectLookup::Unknown,
    );
    let mut driver = ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter)
        .expect("upgraded driver");
    let expected = binding(&effect);
    let (authority, signed, _retry_directory) = final_use(expected.clone(), "legacy-retry");
    let result = store
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            AuthorizedEffectExecutionInput {
                intent: &effect,
                wire_payload: wire,
                fence: &second_owner,
                signed_grant: &signed,
                expected_binding: &expected,
                command_id: "legacy-retry-dispatch",
                now_ms: 50,
            },
        )
        .await;
    match material {
        RetryMaterial::Original => {
            assert_eq!(
                result
                    .expect("original bytes retain old occurrence")
                    .observation,
                Some(TaskFlowStepObservation::Succeeded)
            );
            assert_eq!(
                store
                    .taskflow_run(&effect.run_id)
                    .await
                    .expect("run")
                    .expect("run exists")
                    .state,
                TaskFlowRunState::Succeeded
            );
            assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 1);
            assert_eq!(
                *driver.adapter().seen_key.lock().expect("seen key"),
                Some(original_key.as_str().to_string())
            );
            let first = store
                .authorized_taskflow_effect_attempt(
                    &effect.run_id,
                    &effect.step_id,
                    /*attempt*/ 1,
                )
                .await
                .expect("first")
                .expect("first row");
            let second = store
                .authorized_taskflow_effect_attempt(
                    &effect.run_id,
                    &effect.step_id,
                    /*attempt*/ 2,
                )
                .await
                .expect("second")
                .expect("second row");
            assert_eq!(
                (first.provider_effect_key, first.wire_payload),
                (second.provider_effect_key, second.wire_payload)
            );
            assert_eq!(second.provider_ack, Some(completed_ack(&provider_intent)));
        }
        RetryMaterial::ChangedPayload | RetryMaterial::ChangedDestination => {
            assert!(
                result.is_err(),
                "a new grant cannot replace the original occurrence material"
            );
            assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 0);
            assert!(
                store
                    .authorized_taskflow_effect_attempt(
                        &effect.run_id,
                        &effect.step_id,
                        /*attempt*/ 2
                    )
                    .await
                    .expect("no new barrier")
                    .is_none()
            );
        }
    }
    store.close().await;
    AutomationStore::open(&fixture.layout)
        .await
        .expect("retry leaves valid immutable history");
}

#[tokio::test]
async fn taskflow_provider_identity_legacy_absence_retry_keeps_first_key_and_wire() {
    legacy_absence_retry(RetryMaterial::Original).await;
}

#[tokio::test]
async fn taskflow_provider_identity_legacy_absence_retry_rejects_replacement_payload_or_scope() {
    legacy_absence_retry(RetryMaterial::ChangedPayload).await;
    legacy_absence_retry(RetryMaterial::ChangedDestination).await;
}
