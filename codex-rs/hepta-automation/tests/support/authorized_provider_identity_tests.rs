use super::*;
use pretty_assertions::assert_eq;

#[path = "authorized_provider_legacy_tests.rs"]
mod legacy_tests;

#[derive(Clone, Copy)]
enum ExecutionSeam {
    Sync,
    Async,
}

struct CapturingSyncDriver {
    seen: Vec<(AgentId, ProviderEffectIntent, Vec<u8>)>,
}

impl AuthorizedEffectDriver for CapturingSyncDriver {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        let intent = ProviderEffectIntent::new(
            request.provider_effect_key.clone(),
            request.intent.payload_digest.clone(),
        );
        self.seen.push((
            request.owner_agent_id.clone(),
            intent.clone(),
            request.wire_payload.to_vec(),
        ));
        Ok(AuthorizedEffectProviderReceipt::from_provider_ack(
            completed_ack(&intent),
            ProviderEffectAckSource::DispatchResponse,
        ))
    }
}

struct CapturingAdapter {
    seen: Mutex<Vec<(ProviderEffectIntent, Vec<u8>)>>,
}

impl ProviderEffectAdapter for CapturingAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async {
            ProviderEffectDispatch::NotDispatched {
                reason_code: "exact_wire_required".to_string(),
            }
        })
    }

    fn dispatch_with_payload<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        wire: &'a [u8],
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        self.seen
            .lock()
            .expect("capture")
            .push((intent.clone(), wire.to_vec()));
        Box::pin(async move { ProviderEffectDispatch::Ack(completed_ack(intent)) })
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async { ProviderEffectLookup::Unknown })
    }
}

fn completed_ack(intent: &ProviderEffectIntent) -> ProviderEffectAck {
    ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(intent.key.as_str().as_bytes()),
        ProviderEffectAckStatus::Completed,
    )
}

async fn dispatch_key(
    seam: ExecutionSeam,
    owner: &str,
    run: &str,
    step: &str,
) -> ProviderEffectKey {
    let owner = AgentId::parse(owner).expect("owner");
    let fixture = Fixture::for_agent(owner.clone());
    let mut effect = intent();
    effect.run_id = run.to_string();
    effect.step_id = step.to_string();
    // Identical untrusted subjects do not identify the durable store owner.
    effect.subject_id = "shared-caller-subject".to_string();
    let (store, fence, effect, expected) = prepared_effect_store_for(&fixture, effect).await;
    let (authority, signed, _directory) = final_use(expected.clone(), "owner-key");
    let input = AuthorizedEffectExecutionInput {
        intent: &effect,
        wire_payload: EFFECT_PAYLOAD,
        fence: &fence,
        signed_grant: &signed,
        expected_binding: &expected,
        command_id: "owner-key-dispatch",
        now_ms: 30,
    };
    let (receipt, captured) = match seam {
        ExecutionSeam::Sync => {
            let mut driver = CapturingSyncDriver { seen: Vec::new() };
            let receipt = store
                .execute_authorized_taskflow_effect(&authority, &mut driver, input)
                .await
                .expect("sync dispatch");
            assert_eq!(driver.seen.len(), 1);
            let (actual_owner, actual, bytes) = driver.seen.remove(0);
            assert_eq!(actual_owner, owner);
            assert_eq!(bytes, EFFECT_PAYLOAD);
            (receipt, actual)
        }
        ExecutionSeam::Async => {
            let adapter = CapturingAdapter {
                seen: Mutex::new(Vec::new()),
            };
            let mut driver =
                ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter)
                    .expect("async driver");
            let receipt = store
                .execute_authorized_taskflow_effect_async(&authority, &mut driver, input)
                .await
                .expect("async dispatch");
            let captures = driver.adapter().seen.lock().expect("capture");
            assert_eq!(captures.len(), 1);
            let (actual, bytes) = captures[0].clone();
            assert_eq!(bytes, EFFECT_PAYLOAD);
            (receipt, actual)
        }
    };
    assert_eq!(
        (receipt.state, receipt.observation, receipt.final_outcome),
        (
            TaskFlowStepState::Recorded,
            Some(TaskFlowStepObservation::Succeeded),
            None
        )
    );
    assert_eq!(
        store
            .taskflow_run(run)
            .await
            .expect("run")
            .expect("run exists")
            .state,
        TaskFlowRunState::Succeeded
    );
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen dispatched key");
    let stored = reopened
        .authorized_taskflow_effect_attempt(run, step, /*attempt*/ 1)
        .await
        .expect("stored attempt")
        .expect("attempt");
    assert_eq!(
        (
            stored.owner_agent_id,
            stored.provider_effect_key,
            stored.wire_payload
        ),
        (
            owner.clone(),
            Some(captured.key.clone()),
            Some(EFFECT_PAYLOAD.to_vec())
        )
    );
    assert_eq!(
        captured.key,
        ProviderEffectKey::for_taskflow_v2(&effect.destination_id, &owner, run, step)
            .expect("v2 key")
    );
    captured.key
}

async fn distinct_keys(seam: ExecutionSeam) {
    let a = dispatch_key(seam, AGENT_ID, "a:b", "c").await;
    let b = dispatch_key(seam, AGENT_ID, "a", "b:c").await;
    let first_owner = dispatch_key(seam, AGENT_ID, "shared-run", "shared-step").await;
    let second_owner = dispatch_key(
        seam,
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13",
        "shared-run",
        "shared-step",
    )
    .await;
    assert_ne!(a, b, "separately parsed run/step cannot alias");
    assert_ne!(
        first_owner, second_owner,
        "owner-local run names cannot alias"
    );
}

#[tokio::test]
async fn taskflow_provider_identity_sync_uses_durable_owner_and_separate_fields() {
    distinct_keys(ExecutionSeam::Sync).await;
}

#[tokio::test]
async fn taskflow_provider_identity_async_uses_durable_owner_and_separate_fields() {
    distinct_keys(ExecutionSeam::Async).await;
}

#[tokio::test]
async fn taskflow_provider_identity_mixed_history_is_rejected_before_lookup_and_reopen() {
    let fixture = Fixture::new();
    let started = start(&fixture, ProviderEffectDispatch::Unknown).await;
    let pool = database(&started.store).await;
    let legacy_key = ProviderEffectKey::for_logical_effect(
        &started.effect.destination_id,
        &format!(
            "taskflow:{}:{}",
            started.effect.run_id, started.effect.step_id
        ),
    )
    .expect("legacy key");
    sqlx::query(
        "INSERT INTO taskflow_effect_dispatch_attempts
         (owner_agent_id, run_id, step_id, attempt, intent_digest, payload_digest, binding_digest,
          destination_id, authority_epoch, grant_id, grant_nonce_digest, record_command_id,
          started_at_ms, provider_effect_key, wire_payload)
         SELECT owner_agent_id, run_id, step_id, 2, intent_digest, payload_digest, binding_digest,
                destination_id, authority_epoch, 'imported-second-attempt', ?, 'imported-second-attempt',
                started_at_ms, ?, wire_payload FROM taskflow_effect_dispatch_attempts WHERE attempt=1"
    ).bind(Sha256Digest::for_bytes(b"independent-imported-nonce").as_str())
        .bind(legacy_key.as_str()).execute(&pool).await.expect("import contradictory historical row");
    pool.close().await;
    assert!(
        started
            .store
            .authorized_taskflow_effect_attempt(
                &started.effect.run_id,
                &started.effect.step_id,
                /*attempt*/ 1
            )
            .await
            .is_err()
    );
    assert!(
        started
            .store
            .read_terminal_authorized_taskflow_effect(
                &started.effect.run_id,
                &started.effect.step_id,
                /*attempt*/ 1
            )
            .await
            .is_err()
    );
    assert!(
        started
            .store
            .pending_authorized_taskflow_effects(8)
            .await
            .is_err()
    );
    assert!(
        started
            .driver
            .adapter()
            .lookups
            .lock()
            .expect("lookups")
            .is_empty()
    );
    started.store.close().await;
    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(codex_hepta_automation::AutomationError::Corrupt)
    ));
}

#[tokio::test]
async fn taskflow_provider_identity_missing_material_and_changed_scope_never_query() {
    let fixture = Fixture::new();
    let started = start(&fixture, ProviderEffectDispatch::Unknown).await;
    let pending = started
        .store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending")
        .remove(0);
    let mut no_wire = pending.clone();
    no_wire.wire_payload = None;
    let mut no_key = pending.clone();
    no_key.provider_effect_key = None;
    for partial in [no_wire, no_key] {
        assert_eq!(
            started.driver.lookup(&partial).await,
            AuthorizedProviderEffectLookup::Unresolved
        );
    }
    let wrong_scope = ProviderEffectTaskFlowDriver::new(
        "provider:changed".to_string(),
        RecordingProviderEffectAdapter::new(
            ProviderEffectDispatch::Unknown,
            ProviderEffectLookup::Unknown,
        ),
    )
    .expect("changed driver");
    assert_eq!(
        wrong_scope.lookup(&pending).await,
        AuthorizedProviderEffectLookup::Unresolved
    );
    assert!(
        started
            .driver
            .adapter()
            .lookups
            .lock()
            .expect("lookups")
            .is_empty()
    );
    assert!(
        wrong_scope
            .adapter()
            .lookups
            .lock()
            .expect("lookups")
            .is_empty()
    );
}
