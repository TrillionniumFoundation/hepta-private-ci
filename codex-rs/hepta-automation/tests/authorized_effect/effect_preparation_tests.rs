use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::VerifiedUseBoundaryV1;
use std::sync::Arc;

struct AsyncReceiptDriver {
    calls: usize,
    outcome: Option<AuthorizedEffectOutcome>,
}
impl AsyncAuthorizedEffectDriver for AsyncReceiptDriver {
    fn dispatch<'a>(
        &'a mut self,
        _request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        self.calls += 1;
        let outcome = self.outcome;
        Box::pin(async move {
            outcome
                .map(|outcome| AuthorizedEffectProviderReceipt {
                    outcome,
                    receipt_digest: Sha256Digest::for_bytes(b"preparation-outcome"),
                })
                .ok_or(AuthorizedEffectDriverError::BeforeProviderContact)
        })
    }
}

#[tokio::test]
async fn both_bridges_keep_preparation_for_success_failure_and_absence_without_resend() {
    for asynchronous in [false, true] {
        for outcome in [
            Some(AuthorizedEffectOutcome::Succeeded),
            Some(AuthorizedEffectOutcome::Failed),
            None,
        ] {
            let fixture = Fixture::new();
            let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
            let (authority, signed, _directory) = final_use(expected.clone(), "preparation-effect");
            let mut asynchronous_driver = AsyncReceiptDriver { calls: 0, outcome };
            let mut synchronous_driver = match outcome {
                Some(outcome) => RecordingDriver::receipt(outcome, b"preparation-outcome"),
                None => RecordingDriver::before_provider_contact(),
            };
            for replay in [false, true] {
                let request = AuthorizedEffectDispatchRequest {
                    intent: &effect,
                    wire_payload: EFFECT_PAYLOAD,
                    fence: &owner,
                    signed_grant: &signed,
                    expected_binding: &expected,
                    command_id: "preparation-record",
                    now_ms: 24,
                };
                let result = if asynchronous {
                    store
                        .execute_authorized_taskflow_effect_async(
                            &authority,
                            &mut asynchronous_driver,
                            request,
                        )
                        .await
                } else {
                    store
                        .execute_authorized_taskflow_effect(
                            &authority,
                            &mut synchronous_driver,
                            request,
                        )
                        .await
                };
                match (outcome, replay) {
                    (Some(_), false) => {
                        result.expect("immutable outcome");
                    }
                    (None, false) => {
                        assert!(matches!(result, Err(AuthorizedEffectError::Driver(_))))
                    }
                    (_, true) => {
                        // Existing execution APIs require Claimed. Terminal replay
                        // uses the separate observation-only receipt reader.
                        assert!(result.is_err(), "settled step must not re-enter execution");
                        let receipt = store
                            .read_authorized_taskflow_effect_receipt(&effect, "preparation-record")
                            .await
                            .expect("exact terminal observation");
                        assert_eq!(receipt.is_some(), outcome.is_some());
                    }
                }
            }
            let witness = store
                .authorized_taskflow_effect_preparation_witness(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                )
                .await
                .expect("audit read")
                .expect("preparation");
            assert_eq!(witness.boundary, VerifiedUseBoundaryV1::PreparationEntry);
            assert_eq!(asynchronous_driver.calls + synchronous_driver.calls, 1);
            store.close().await;
            let reopened = AutomationStore::open(&fixture.layout)
                .await
                .expect("reopen");
            assert_eq!(
                reopened
                    .authorized_taskflow_effect_preparation_witness(
                        &effect.run_id,
                        &effect.step_id,
                        effect.attempt
                    )
                    .await
                    .expect("audit after restart"),
                Some(witness)
            );
            reopened.close().await;
        }
    }
}

#[derive(Debug)]
struct ExpireAfterPreparation {
    samples: AtomicUsize,
    live: u64,
    expired: u64,
}
impl AuthorityClock for ExpireAfterPreparation {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        // Open, claim-before-persist, claim-after-persist, active entry,
        // preparation entry, then the final post-preparation check.
        Ok(if self.samples.fetch_add(1, Ordering::SeqCst) < 5 {
            self.live
        } else {
            self.expired
        })
    }
}

#[tokio::test]
async fn grant_expiry_after_preparation_commit_blocks_both_driver_entries() {
    for asynchronous in [false, true] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        let (initial, signed, directory) = final_use(expected.clone(), "expiry-effect");
        drop(initial);
        let clock = Arc::new(ExpireAfterPreparation {
            samples: AtomicUsize::new(0),
            live: signed.grant.not_before_unix_ms + 1_000,
            expired: signed.grant.expires_at_unix_ms,
        });
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            directory.path(),
            "security-owner".into(),
            SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            clock.clone(),
        )
        .expect("current trusted clock");
        let mut asynchronous_driver = AsyncReceiptDriver {
            calls: 0,
            outcome: Some(AuthorizedEffectOutcome::Succeeded),
        };
        let mut synchronous_driver =
            RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"must-not-send");
        let request = AuthorizedEffectDispatchRequest {
            intent: &effect,
            wire_payload: EFFECT_PAYLOAD,
            fence: &owner,
            signed_grant: &signed,
            expected_binding: &expected,
            command_id: "expiry-record",
            now_ms: 24,
        };
        let result = if asynchronous {
            store
                .execute_authorized_taskflow_effect_async(
                    &authority,
                    &mut asynchronous_driver,
                    request,
                )
                .await
        } else {
            store
                .execute_authorized_taskflow_effect(&authority, &mut synchronous_driver, request)
                .await
        };
        assert!(
            matches!(
                result,
                Err(AuthorizedEffectError::FinalUse(FinalUseError::Expired))
            ),
            "{result:?}"
        );
        assert_eq!(asynchronous_driver.calls + synchronous_driver.calls, 0);
        assert_eq!(clock.samples.load(Ordering::SeqCst), 6);
        let witness = store
            .authorized_taskflow_effect_preparation_witness(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
            )
            .await
            .expect("audit read")
            .expect("preparation committed");
        assert_eq!(witness.verified_at_unix_ms, clock.live);
        assert_eq!(witness.boundary, VerifiedUseBoundaryV1::PreparationEntry);
        assert!(
            store
                .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 10)
                .await
                .expect("absence settled")
                .effects
                .is_empty()
        );
        store.close().await;
    }
}

struct PendingDriver {
    entered: Option<tokio::sync::oneshot::Sender<()>>,
    calls: usize,
}
impl AsyncAuthorizedEffectDriver for PendingDriver {
    fn dispatch<'a>(
        &'a mut self,
        _request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        self.calls += 1;
        let entered = self.entered.take();
        Box::pin(async move {
            if let Some(entered) = entered {
                let _ = entered.send(());
            }
            std::future::pending().await
        })
    }
}

#[tokio::test]
async fn cancellation_after_preparation_never_makes_the_witness_a_retry_permit() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _directory) = final_use(expected.clone(), "cancel-effect");
    let (entered, receiver) = tokio::sync::oneshot::channel();
    let mut driver = PendingDriver {
        entered: Some(entered),
        calls: 0,
    };
    {
        let dispatch = store.execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            AuthorizedEffectDispatchRequest {
                intent: &effect,
                wire_payload: EFFECT_PAYLOAD,
                fence: &owner,
                signed_grant: &signed,
                expected_binding: &expected,
                command_id: "cancel-record",
                now_ms: 24,
            },
        );
        tokio::pin!(dispatch);
        tokio::time::timeout(Duration::from_secs(5), async {
            tokio::select! {
                entered = receiver => entered.expect("consumer entered"),
                result = &mut dispatch => panic!("unexpected completion: {result:?}"),
            }
        })
        .await
        .expect("bounded consumer entry");
    }
    assert_eq!(driver.calls, 1);
    let witness = store
        .authorized_taskflow_effect_preparation_witness(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
        )
        .await
        .expect("audit read")
        .expect("preparation retained");
    assert!(
        store
            .settle_authorized_taskflow_effect_observation(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner
            )
            .await
            .expect("not terminal")
            .is_none()
    );
    let replay = tokio::time::timeout(
        Duration::from_secs(5),
        store.execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            AuthorizedEffectDispatchRequest {
                intent: &effect,
                wire_payload: EFFECT_PAYLOAD,
                fence: &owner,
                signed_grant: &signed,
                expected_binding: &expected,
                command_id: "cancel-record",
                now_ms: 24,
            },
        ),
    )
    .await
    .expect("bounded no-resend refusal");
    assert!(matches!(
        replay,
        Err(AuthorizedEffectError::RecoveryRequired)
    ));
    assert_eq!(driver.calls, 1);
    assert_eq!(
        store
            .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 10)
            .await
            .expect("pending")
            .effects
            .len(),
        1
    );
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    assert_eq!(
        reopened
            .authorized_taskflow_effect_preparation_witness(
                &effect.run_id,
                &effect.step_id,
                effect.attempt
            )
            .await
            .expect("audit after restart"),
        Some(witness)
    );
    assert_eq!(
        reopened
            .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 10)
            .await
            .expect("still pending")
            .effects
            .len(),
        1
    );
    reopened.close().await;
}
