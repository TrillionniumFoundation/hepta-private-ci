use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::SystemAuthorityClock;
use pretty_assertions::assert_eq;
use std::sync::Arc;

#[tokio::test]
async fn sync_effect_writer_wait_cannot_backdate_lease_admission() {
    effect_writer_wait_cannot_backdate_lease_admission(/*async_dispatch*/ false).await;
}

#[tokio::test]
async fn async_effect_writer_wait_cannot_backdate_lease_admission() {
    effect_writer_wait_cannot_backdate_lease_admission(/*async_dispatch*/ true).await;
}

async fn effect_writer_wait_cannot_backdate_lease_admission(async_dispatch: bool) {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "writer-wait-effect");
    let mut sync_driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"success");
    let mut async_driver = ContractBoundDriver {
        store: store.clone(),
        binding: Sha256Digest::for_bytes(b"writer-wait-contract"),
        calls: 0,
    };
    let blocker = codex_state::SqliteConfig::from_sqlite_home(
        codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
            fixture.layout.automation_root(),
        )
        .expect("SQLite home"),
    )
    .open_durable_evidence_pool(store.path())
    .await
    .expect("second SQLite pool");
    let reservation = blocker
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("hold writer");
    // The fixture lease expires at logical 1020. This entry is live, but the
    // writer reservation spans its remaining 250ms before any physical send.
    let result = {
        let dispatch = async {
            if async_dispatch {
                store
                    .execute_authorized_taskflow_effect_async(
                        &authority,
                        &mut async_driver,
                        &effect,
                        EFFECT_PAYLOAD,
                        &owner,
                        &signed,
                        &expected,
                        "writer-wait-record",
                        770,
                    )
                    .await
            } else {
                store
                    .execute_authorized_taskflow_effect(
                        &authority,
                        &mut sync_driver,
                        &effect,
                        EFFECT_PAYLOAD,
                        &owner,
                        &signed,
                        &expected,
                        "writer-wait-record",
                        770,
                    )
                    .await
            }
        };
        tokio::pin!(dispatch);
        let early = tokio::select! {
            biased;
            result = &mut dispatch => Some(result),
            () = tokio::time::sleep(Duration::from_millis(350)) => None,
        };
        reservation.commit().await.expect("release writer");
        match early {
            Some(result) => result,
            None => dispatch.await,
        }
    };
    assert!(matches!(
        result,
        Err(AuthorizedEffectError::TaskFlow(
            codex_hepta_automation::TaskFlowError::StaleFence
        ))
    ));
    assert_eq!(sync_driver.calls, 0);
    assert_eq!(async_driver.calls, 0);
    assert!(
        store
            .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("attempt")
            .is_none()
    );
    blocker.close().await;
    store.close().await;
}

struct BlockingConsumerClock {
    calls: AtomicUsize,
    consumer_waits: AtomicUsize,
}

impl AuthorityClock for BlockingConsumerClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        // Constructor samples once and claim samples twice. Block only the
        // final-use consumer entry, after TaskFlow's database admission.
        if self.calls.fetch_add(1, Ordering::SeqCst) == 3 {
            self.consumer_waits.fetch_add(1, Ordering::SeqCst);
            thread::sleep(Duration::from_millis(350));
        }
        SystemAuthorityClock.now_unix_ms()
    }
}

#[tokio::test]
async fn sync_effect_checks_lease_inside_the_authorized_consumer() {
    effect_checks_lease_inside_the_authorized_consumer(/*async_dispatch*/ false).await;
}

#[tokio::test]
async fn async_effect_checks_lease_inside_the_authorized_consumer() {
    effect_checks_lease_inside_the_authorized_consumer(/*async_dispatch*/ true).await;
}

async fn effect_checks_lease_inside_the_authorized_consumer(async_dispatch: bool) {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (_, signed, authority_dir) = final_use(expected.clone(), "consumer-clock-effect");
    let clock = Arc::new(BlockingConsumerClock {
        calls: AtomicUsize::new(0),
        consumer_waits: AtomicUsize::new(0),
    });
    let authority = FinalUseAuthority::open_state_dir_with_clock(
        authority_dir.path(),
        "security-owner".to_string(),
        SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        clock.clone(),
    )
    .expect("clock-injected authority");
    let mut sync_driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"success");
    let mut async_driver = ContractBoundDriver {
        store: store.clone(),
        binding: Sha256Digest::for_bytes(b"consumer-clock-contract"),
        calls: 0,
    };
    // Logical770 is live until1020. The grant remains valid for30s while the
    // authority's350ms wait expires only the TaskFlow admission lease.
    let result = if async_dispatch {
        store
            .execute_authorized_taskflow_effect_async(
                &authority,
                &mut async_driver,
                &effect,
                EFFECT_PAYLOAD,
                &owner,
                &signed,
                &expected,
                "consumer-clock-record",
                770,
            )
            .await
    } else {
        store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut sync_driver,
                &effect,
                EFFECT_PAYLOAD,
                &owner,
                &signed,
                &expected,
                "consumer-clock-record",
                770,
            )
            .await
    };
    assert!(matches!(
        result,
        Err(AuthorizedEffectError::TaskFlow(
            codex_hepta_automation::TaskFlowError::StaleFence
        ))
    ));
    assert_eq!(clock.consumer_waits.load(Ordering::SeqCst), 1);
    assert_eq!(sync_driver.calls, 0);
    assert_eq!(async_driver.calls, 0);
    assert!(
        store
            .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("attempt")
            .is_some()
    );
    assert!(
        store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("settled absence")
            .is_empty()
    );
    let step = store
        .read_taskflow_step(&effect.run_id, &effect.step_id, effect.attempt, &owner)
        .await
        .expect("step")
        .expect("cancelled step");
    assert_eq!(
        step.final_outcome,
        Some(TaskFlowReconcileOutcome::Cancelled)
    );
    assert_eq!(
        store
            .taskflow_run(&effect.run_id)
            .await
            .expect("run")
            .expect("requeued run")
            .state,
        TaskFlowRunState::Queued
    );
    store.close().await;
}
