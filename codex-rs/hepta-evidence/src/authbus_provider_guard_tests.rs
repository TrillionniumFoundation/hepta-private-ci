use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_authbus::AuthPolicyRule;
use codex_hepta_authbus::EffectAdmissionRequest;
use codex_hepta_authbus::PolicyEffect;
use codex_hepta_authbus::QuotaRegistryEntry;
use codex_hepta_authbus::ReservationState;
use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectFuture;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::RequestBindingId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::HeptaEvidenceStore;
use crate::store::now_millis;

#[derive(Clone)]
struct GuardProbeAdapter {
    store: Arc<HeptaEvidenceStore>,
    quota_key: StableId,
    expected_reserved: u64,
    dispatch_result: ProviderEffectDispatch,
    lookup_result: ProviderEffectLookup,
    saw_reserved_before_dispatch: Arc<AtomicBool>,
}

impl ProviderEffectAdapter for GuardProbeAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        let store = Arc::clone(&self.store);
        let quota_key = self.quota_key.clone();
        let expected = self.expected_reserved;
        let result = self.dispatch_result.clone();
        let observed = Arc::clone(&self.saw_reserved_before_dispatch);
        Box::pin(async move {
            let snapshot = store
                .quota_snapshot(&quota_key)
                .await
                .expect("quota snapshot");
            observed.store(snapshot.reserved == expected, Ordering::SeqCst);
            result
        })
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        let result = self.lookup_result.clone();
        Box::pin(async move { result })
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn request_binding_id() -> RequestBindingId {
    RequestBindingId::for_request(&ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: "thread-authbus-guard".to_string(),
        turn_id: "turn-authbus-guard".to_string(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-authbus-guard"),
        request_kind: ProviderRequestKind::Turn,
        provider_id: "provider-authbus-guard".to_string(),
        provider_config_sha256: Sha256Digest::for_bytes(b"config-authbus-guard"),
        model: "guard-model".to_string(),
        transport: ProviderTransport::Http,
        endpoint_sha256: Sha256Digest::for_bytes(b"/guard"),
        logical_request_sha256: Sha256Digest::for_bytes(b"logical-authbus-guard"),
        wire_semantic_sha256: Sha256Digest::for_bytes(b"wire-authbus-guard"),
        ephemeral_input_sha256: None,
        ephemeral_input_witness_sha256: None,
        previous_response_id_sha256: None,
        generate: true,
    })
}

fn intent(occurrence: &str) -> ProviderEffectIntent {
    let key = ProviderEffectKey::for_occurrence(
        "provider-authbus-guard/config-v1",
        occurrence,
        &request_binding_id(),
    )
    .expect("effect key");
    ProviderEffectIntent::new(key, Sha256Digest::for_bytes(b"guarded-payload"))
}

fn ack(intent: &ProviderEffectIntent, status: ProviderEffectAckStatus) -> ProviderEffectAck {
    ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"guarded-provider-operation"),
        status,
    )
}

async fn provision(store: &HeptaEvidenceStore) -> (StableId, StableId, StableId, Digest32, u64) {
    let principal = id("principal:guard");
    let action = id("action:provider");
    let quota = id("quota:guard");
    let scope = Digest32::of_bytes(b"guarded-provider-scope");
    store
        .put_auth_policy(&AuthPolicyRule {
            principal_id: principal.clone(),
            action_id: action.clone(),
            scope_digest: scope,
            revision: 1,
            effect: PolicyEffect::Allow,
            max_active_reservations: 4_096,
        })
        .await
        .expect("policy");
    let now = u64::try_from(now_millis().expect("clock")).expect("positive clock");
    let end = now + 60_000;
    store
        .put_quota_registry(&QuotaRegistryEntry {
            quota_key: quota.clone(),
            revision: 1,
            capacity: 10,
            period_start_ms: now.saturating_sub(1_000),
            period_end_ms: end,
        })
        .await
        .expect("quota");
    (principal, action, quota, scope, end)
}

fn admission(
    operation: &str,
    principal: StableId,
    action: StableId,
    quota: StableId,
    scope: Digest32,
    end: u64,
) -> EffectAdmissionRequest {
    EffectAdmissionRequest {
        operation_id: id(operation),
        principal_id: principal,
        action_id: action,
        scope_digest: scope,
        policy_revision: 1,
        quota_key: quota,
        quota_revision: 1,
        amount: 10,
        expires_at_ms: end - 1,
    }
}

#[tokio::test]
async fn guarded_dispatch_reserves_before_adapter_and_holds_completed_cost_until_settlement() {
    let temp = TempDir::new().expect("temp");
    let store = Arc::new(
        HeptaEvidenceStore::open(&config(&temp))
            .await
            .expect("store"),
    );
    let (principal, action, quota, scope, end) = provision(&store).await;
    let intent = intent("guarded-completed");
    let completed = ack(&intent, ProviderEffectAckStatus::Completed);
    let observed = Arc::new(AtomicBool::new(false));
    let adapter = GuardProbeAdapter {
        store: Arc::clone(&store),
        quota_key: quota.clone(),
        expected_reserved: 10,
        dispatch_result: ProviderEffectDispatch::Ack(completed.clone()),
        lookup_result: ProviderEffectLookup::Ack(completed),
        saw_reserved_before_dispatch: Arc::clone(&observed),
    };
    let request = admission(
        intent.key.as_str(),
        principal,
        action,
        quota.clone(),
        scope,
        end,
    );

    let receipt = store
        .dispatch_provider_effect_guarded_qualification(&adapter, &intent, &request)
        .await
        .expect("guarded dispatch");
    assert!(observed.load(Ordering::SeqCst));
    assert_eq!(receipt.reservation.state, ReservationState::Quarantined);
    let held = store.quota_snapshot(&quota).await.expect("held quota");
    assert_eq!((held.reserved, held.consumed), (10, 0));

    let settled = store
        .reconcile_provider_effect_guarded_qualification(
            &adapter,
            &intent.key,
            receipt.reservation.reservation_id,
            Some(7),
            Digest32::of_bytes(b"observed-cost-terminal-evidence"),
        )
        .await
        .expect("settled reconciliation");
    assert_eq!(settled.state, ReservationState::Settled);
    let final_quota = store.quota_snapshot(&quota).await.expect("final quota");
    assert_eq!((final_quota.reserved, final_quota.consumed), (0, 7));
}

#[tokio::test]
async fn terminal_rejected_ack_releases_reserved_quota_without_consumption() {
    let temp = TempDir::new().expect("temp");
    let store = Arc::new(
        HeptaEvidenceStore::open(&config(&temp))
            .await
            .expect("store"),
    );
    let (principal, action, quota, scope, end) = provision(&store).await;
    let intent = intent("guarded-rejected");
    let rejected = ack(&intent, ProviderEffectAckStatus::Rejected);
    let observed = Arc::new(AtomicBool::new(false));
    let adapter = GuardProbeAdapter {
        store: Arc::clone(&store),
        quota_key: quota.clone(),
        expected_reserved: 10,
        dispatch_result: ProviderEffectDispatch::Ack(rejected.clone()),
        lookup_result: ProviderEffectLookup::Ack(rejected),
        saw_reserved_before_dispatch: Arc::clone(&observed),
    };
    let request = admission(
        intent.key.as_str(),
        principal,
        action,
        quota.clone(),
        scope,
        end,
    );

    let receipt = store
        .dispatch_provider_effect_guarded_qualification(&adapter, &intent, &request)
        .await
        .expect("guarded dispatch");
    assert!(observed.load(Ordering::SeqCst));
    assert_eq!(receipt.reservation.state, ReservationState::Cancelled);
    let quota = store.quota_snapshot(&quota).await.expect("quota released");
    assert_eq!(
        (quota.reserved, quota.consumed, quota.available()),
        (0, 0, 10)
    );
}


#[tokio::test]
async fn guarded_dispatch_rejects_operation_identity_drift_before_reserving_or_sending() {
    let temp = TempDir::new().expect("temp");
    let store = Arc::new(
        HeptaEvidenceStore::open(&config(&temp))
            .await
            .expect("store"),
    );
    let (principal, action, quota, scope, end) = provision(&store).await;
    let intent = intent("guarded-identity-drift");
    let observed = Arc::new(AtomicBool::new(false));
    let adapter = GuardProbeAdapter {
        store: Arc::clone(&store),
        quota_key: quota.clone(),
        expected_reserved: 10,
        dispatch_result: ProviderEffectDispatch::Unknown,
        lookup_result: ProviderEffectLookup::Unknown,
        saw_reserved_before_dispatch: Arc::clone(&observed),
    };
    let request = admission(
        "operation:different-provider-effect",
        principal,
        action,
        quota.clone(),
        scope,
        end,
    );

    assert!(matches!(
        store
            .dispatch_provider_effect_guarded_qualification(&adapter, &intent, &request)
            .await,
        Err(crate::AuthBusProviderEffectError::OperationBindingMismatch)
    ));
    assert!(!observed.load(Ordering::SeqCst));
    let quota = store.quota_snapshot(&quota).await.expect("quota unchanged");
    assert_eq!(
        (quota.reserved, quota.consumed, quota.available()),
        (0, 0, 10)
    );
}
