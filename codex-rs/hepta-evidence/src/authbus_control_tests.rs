use codex_hepta_authbus::AuthPolicy;
use codex_hepta_authbus::AuthorizationRequest;
use codex_hepta_authbus::Error as AuthBusError;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::PolicyDecisionKind;
use codex_hepta_authbus::PolicyDenyReason;
use codex_hepta_authbus::QuotaSpec;
use codex_hepta_authbus::ReservationRequest;
use codex_hepta_authbus::ReservationState;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

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
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::AuthBusAdmissionError;
use crate::AuthBusEffectError;
use crate::ObservedCostEvidence;
use crate::AuthBusControlError;
use crate::HeptaEvidenceStore;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture id")
}

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn policy(revision: u64, enabled: bool) -> AuthPolicy {
    AuthPolicy {
        policy_id: id("policy:authbus:test"),
        revision,
        principal_id: id("principal:test"),
        action: id("action:provider-effect"),
        resource_digest: Digest32::of_bytes(b"resource"),
        scope_digest: Digest32::of_bytes(b"scope"),
        audience: id("audience:provider"),
        quota_key: id("quota:provider"),
        max_reservation: 10,
        enabled,
    }
}

fn authorization(revision: u64, payload: Digest32) -> AuthorizationRequest {
    AuthorizationRequest {
        principal_id: id("principal:test"),
        action: id("action:provider-effect"),
        resource_digest: Digest32::of_bytes(b"resource"),
        scope_digest: Digest32::of_bytes(b"scope"),
        payload_digest: payload,
        audience: id("audience:provider"),
        policy_id: id("policy:authbus:test"),
        expected_policy_revision: revision,
    }
}

fn quota(capacity: u64) -> QuotaSpec {
    QuotaSpec {
        quota_key: id("quota:provider"),
        config_revision: 1,
        capacity,
        period_start_ms: 1,
        period_end_ms: u64::MAX,
    }
}

fn reservation(
    name: &str,
    operation: &str,
    amount: u64,
    quota_revision: u64,
    decision: &codex_hepta_authbus::AuthorizationDecision,
) -> ReservationRequest {
    ReservationRequest {
        reservation_id: id(name),
        operation_id: id(operation),
        quota_key: id("quota:provider"),
        amount,
        expected_quota_revision: quota_revision,
        expires_at_ms: 100,
        policy_digest: decision.policy_digest.expect("allowed policy digest"),
        authorization_digest: decision.request_digest,
    }
}

async fn configured(
    temp: &TempDir,
    capacity: u64,
) -> (
    HeptaEvidenceStore,
    codex_hepta_authbus::AuthorizationDecision,
    u64,
) {
    let store = HeptaEvidenceStore::open(&config(temp)).await.expect("open");
    store
        .install_authbus_policy(&policy(1, true))
        .await
        .expect("policy");
    let quota = store.install_authbus_quota(&quota(capacity)).await.expect("quota");
    let decision = store
        .authorize_authbus(&authorization(1, Digest32::of_bytes(b"payload")))
        .await
        .expect("authorize");
    assert_eq!(decision.kind, PolicyDecisionKind::Allowed);
    (store, decision, quota.ledger_revision)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn bus_01_simultaneous_last_unit_reservations_cannot_both_succeed() {
    let temp = TempDir::new().expect("temp");
    let (first, decision, revision) = configured(&temp, 1).await;
    let second = HeptaEvidenceStore::open(&config(&temp)).await.expect("second handle");
    let left = reservation("reservation:left", "operation:left", 1, revision, &decision);
    let right = reservation("reservation:right", "operation:right", 1, revision, &decision);

    let (left_result, right_result) = tokio::join!(
        first.reserve_authbus_quota(&decision, &left, 10),
        second.reserve_authbus_quota(&decision, &right, 10),
    );
    assert_eq!(
        usize::from(left_result.is_ok()) + usize::from(right_result.is_ok()),
        1
    );
    let rejected = left_result.err().or_else(|| right_result.err()).expect("one reject");
    assert!(matches!(
        rejected,
        AuthBusControlError::StaleQuotaRevision | AuthBusControlError::QuotaExceeded
    ));
    let state = first
        .authbus_quota_state(&id("quota:provider"))
        .await
        .expect("state")
        .expect("quota");
    assert_eq!((state.reserved, state.consumed, state.available()), (1, 0, Some(0)));
}

#[tokio::test]
async fn bus_02_duplicate_settlement_is_idempotent_and_changed_cost_conflicts() {
    let temp = TempDir::new().expect("temp");
    let (store, decision, revision) = configured(&temp, 10).await;
    let request = reservation("reservation:settle", "operation:settle", 5, revision, &decision);
    let held = store
        .reserve_authbus_quota(&decision, &request, 10)
        .await
        .expect("reserve");
    let evidence = Digest32::of_bytes(b"provider completed");
    let first = store
        .settle_authbus_reservation(&held.reservation_id, 3, evidence)
        .await
        .expect("settle");
    let replay = store
        .settle_authbus_reservation(&held.reservation_id, 3, evidence)
        .await
        .expect("idempotent replay");
    assert_eq!(first, replay);
    assert_eq!(first.state, ReservationState::Settled);
    assert!(matches!(
        store
            .settle_authbus_reservation(
                &held.reservation_id,
                4,
                Digest32::of_bytes(b"changed provider cost")
            )
            .await,
        Err(AuthBusControlError::ReservationConflict)
    ));
    let quota = store
        .authbus_quota_state(&id("quota:provider"))
        .await
        .expect("quota")
        .expect("present");
    assert_eq!((quota.reserved, quota.consumed, quota.available()), (0, 3, Some(7)));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn bus_03_expiry_racing_terminal_result_never_double_refunds() {
    let temp = TempDir::new().expect("temp");
    let (first, decision, revision) = configured(&temp, 10).await;
    let second = HeptaEvidenceStore::open(&config(&temp)).await.expect("second");
    let mut request =
        reservation("reservation:race", "operation:race", 5, revision, &decision);
    request.expires_at_ms = 20;
    let held = first
        .reserve_authbus_quota(&decision, &request, 10)
        .await
        .expect("reserve");

    let evidence = Digest32::of_bytes(b"late terminal provider result");
    let (expiry, settlement) = tokio::join!(
        first.expire_authbus_reservations(20, 128),
        second.settle_authbus_reservation(&held.reservation_id, 4, evidence),
    );
    assert!(expiry.is_ok());
    let settled = settlement.expect("terminal result must settle even after expiry");
    assert_eq!(settled.state, ReservationState::Settled);

    first.pool.close().await;
    second.pool.close().await;
    let reopened = HeptaEvidenceStore::open(&config(&temp)).await.expect("reopen");
    let quota = reopened
        .authbus_quota_state(&id("quota:provider"))
        .await
        .expect("quota")
        .expect("present");
    assert_eq!((quota.reserved, quota.consumed, quota.available()), (0, 4, Some(6)));
    let state: String = sqlx::query_scalar(
        "SELECT state FROM authbus_quota_reservations WHERE reservation_id = ?",
    )
    .bind(held.reservation_id.as_str())
    .fetch_one(&reopened.pool)
    .await
    .expect("reservation state");
    assert_eq!(state, "settled");
}

#[tokio::test]
async fn bus_04_stale_or_disabled_policy_cannot_reserve_effect_quota() {
    let temp = TempDir::new().expect("temp");
    let (store, decision, revision) = configured(&temp, 10).await;
    store
        .install_authbus_policy(&policy(2, false))
        .await
        .expect("disable policy");
    let request = reservation("reservation:stale", "operation:stale", 1, revision, &decision);
    assert!(matches!(
        store
            .reserve_authbus_quota(&decision, &request, 10)
            .await,
        Err(AuthBusControlError::StalePolicyRevision)
    ));
    let disabled = store
        .authorize_authbus(&authorization(2, Digest32::of_bytes(b"payload")))
        .await
        .expect("disabled decision");
    assert_eq!(disabled.kind, PolicyDecisionKind::Denied);
    assert_eq!(disabled.deny_reason, Some(PolicyDenyReason::Disabled));
    let quota = store
        .authbus_quota_state(&id("quota:provider"))
        .await
        .expect("quota")
        .expect("present");
    assert_eq!((quota.reserved, quota.consumed), (0, 0));
}

#[tokio::test]
async fn external_checkpoint_detects_a_stale_or_restored_rollback_guard() {
    let temp = TempDir::new().expect("temp");
    let (store, decision, revision) = configured(&temp, 10).await;
    let before = store.authbus_rollback_checkpoint().await.expect("checkpoint");
    let request = reservation(
        "reservation:checkpoint",
        "operation:checkpoint",
        1,
        revision,
        &decision,
    );
    store
        .reserve_authbus_quota(&decision, &request, 10)
        .await
        .expect("reserve");
    let after = store.authbus_rollback_checkpoint().await.expect("after");
    assert!(after.generation > before.generation);
    store
        .verify_authbus_rollback_checkpoint(&after)
        .await
        .expect("current checkpoint");
    assert!(matches!(
        store.verify_authbus_rollback_checkpoint(&before).await,
        Err(AuthBusControlError::RollbackDetected)
    ));

    sqlx::query(
        "UPDATE authbus_rollback_guard SET generation = ?, chain_digest = ? WHERE singleton = 1",
    )
    .bind(before.generation.to_be_bytes().as_slice())
    .bind(before.chain_digest.as_array().as_slice())
    .execute(&store.pool)
    .await
    .expect("simulate restored guard");
    assert!(matches!(
        store.verify_authbus_rollback_checkpoint(&after).await,
        Err(AuthBusControlError::RollbackDetected)
    ));
}

fn signed_fixture(
    key: &SigningKey,
    epoch: u64,
    sequence: u64,
) -> (IssuerRegistration, SignedMessage) {
    let issuer = IssuerRegistration {
        issuer_id: id("issuer:managed"),
        key_epoch: Generation::new(epoch).expect("epoch"),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: id(&format!("message:managed:{epoch}:{sequence}")),
        subject_id: id("subject:managed"),
        scope_digest: Digest32::of_bytes(b"managed scope"),
        payload_digest: Digest32::of_bytes(b"managed payload"),
        sequence,
        expires_at_ms: u64::MAX,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    (issuer, SignedMessage { claims, signature })
}

#[tokio::test]
async fn retired_replay_epoch_frees_capacity_without_reopening_replay() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp)).await.expect("store");
    let key_one = SigningKey::from_bytes(&[41; 32]);
    let (issuer_one, first) = signed_fixture(&key_one, 1, 1);
    store
        .install_authbus_issuer(&issuer_one)
        .await
        .expect("install epoch one");
    store
        .admit_authbus_message(
            &issuer_one,
            &first,
            first.claims.scope_digest,
            first.claims.payload_digest,
        )
        .await
        .expect("consume replay sequence");

    store
        .revoke_authbus_issuer(&issuer_one.issuer_id, issuer_one.key_epoch)
        .await
        .expect("revoke old epoch");
    let key_two = SigningKey::from_bytes(&[42; 32]);
    let (issuer_two, _) = signed_fixture(&key_two, 2, 1);
    store
        .install_authbus_issuer(&issuer_two)
        .await
        .expect("install newer epoch");
    let checkpoint = store.authbus_rollback_checkpoint().await.expect("checkpoint");
    let retired = store
        .retire_authbus_replay_epoch(&issuer_one.issuer_id, issuer_one.key_epoch, &checkpoint)
        .await
        .expect("retire old replay epoch");
    assert!(retired.generation > checkpoint.generation);

    let epoch = issuer_one.key_epoch.get().to_be_bytes();
    let replay_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM authbus_replay_sequences WHERE issuer_id = ? AND key_epoch = ?",
    )
    .bind(issuer_one.issuer_id.as_str())
    .bind(epoch.as_slice())
    .fetch_one(&store.pool)
    .await
    .expect("replay count");
    assert_eq!(replay_rows, 0);

    let (_, replay) = signed_fixture(&key_one, 1, 2);
    assert!(matches!(
        store
            .admit_authbus_message(
                &issuer_one,
                &replay,
                replay.claims.scope_digest,
                replay.claims.payload_digest,
            )
            .await,
        Err(AuthBusAdmissionError::Authentication(AuthBusError::RetiredIssuer))
    ));
}


#[derive(Clone)]
struct CountingEffectAdapter {
    dispatches: Arc<AtomicUsize>,
    dispatch: ProviderEffectDispatch,
}

impl ProviderEffectAdapter for CountingEffectAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        self.dispatches.fetch_add(1, Ordering::Relaxed);
        let value = self.dispatch.clone();
        Box::pin(async move { value })
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async { ProviderEffectLookup::Unknown })
    }
}

fn provider_effect(payload: &[u8], occurrence: &str) -> ProviderEffectIntent {
    let binding = RequestBindingId::for_request(&ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: "thread-authbus".to_string(),
        turn_id: "turn-authbus".to_string(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-authbus"),
        request_kind: ProviderRequestKind::Turn,
        provider_id: "provider-authbus".to_string(),
        provider_config_sha256: Sha256Digest::for_bytes(b"provider-config"),
        model: "authbus-model".to_string(),
        transport: ProviderTransport::Http,
        endpoint_sha256: Sha256Digest::for_bytes(b"/authbus-effect"),
        logical_request_sha256: Sha256Digest::for_bytes(b"logical-authbus"),
        wire_semantic_sha256: Sha256Digest::for_bytes(b"wire-authbus"),
        ephemeral_input_sha256: None,
        ephemeral_input_witness_sha256: None,
    })
    .expect("binding");
    ProviderEffectIntent::new(
        ProviderEffectKey::for_occurrence("provider-authbus", occurrence, &binding)
            .expect("effect key"),
        Sha256Digest::for_bytes(payload),
    )
}

#[tokio::test]
async fn bus_04_effect_adapter_is_never_called_after_policy_revision_changes() {
    let temp = TempDir::new().expect("temp");
    let (store, decision, revision) = configured(&temp, 10).await;
    let auth = authorization(1, Digest32::of_bytes(b"payload"));
    let intent = provider_effect(b"payload", "bus-04-denied");
    let request = reservation(
        "reservation:effect-denied",
        intent.key.as_str(),
        1,
        revision,
        &decision,
    );
    store
        .install_authbus_policy(&policy(2, false))
        .await
        .expect("disable policy");
    let dispatches = Arc::new(AtomicUsize::new(0));
    let adapter = CountingEffectAdapter {
        dispatches: dispatches.clone(),
        dispatch: ProviderEffectDispatch::Unknown,
    };
    assert!(matches!(
        store
            .dispatch_provider_effect_with_authbus_qualification(
                &adapter, &auth, &request, &intent, 10
            )
            .await,
        Err(AuthBusEffectError::AuthorizationDenied)
    ));
    assert_eq!(dispatches.load(Ordering::Relaxed), 0);
    let quota = store
        .authbus_quota_state(&id("quota:provider"))
        .await
        .expect("quota")
        .expect("present");
    assert_eq!((quota.reserved, quota.consumed), (0, 0));
}

#[tokio::test]
async fn completed_provider_effect_settles_only_from_observed_cost_evidence() {
    let temp = TempDir::new().expect("temp");
    let (store, decision, revision) = configured(&temp, 10).await;
    let auth = authorization(1, Digest32::of_bytes(b"payload"));
    let intent = provider_effect(b"payload", "settlement");
    let request = reservation(
        "reservation:provider-complete",
        intent.key.as_str(),
        5,
        revision,
        &decision,
    );
    let ack = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"provider-operation"),
        ProviderEffectAckStatus::Completed,
    );
    let adapter = CountingEffectAdapter {
        dispatches: Arc::new(AtomicUsize::new(0)),
        dispatch: ProviderEffectDispatch::Ack(ack),
    };
    let dispatched = store
        .dispatch_provider_effect_with_authbus_qualification(
            &adapter, &auth, &request, &intent, 10
        )
        .await
        .expect("dispatch");
    assert_eq!(dispatched.provider.state, codex_hepta_contracts::ProviderEffectState::Completed);
    assert_eq!(dispatched.reservation.state, ReservationState::Quarantined);
    let held = store
        .authbus_quota_state(&id("quota:provider"))
        .await
        .expect("quota")
        .expect("present");
    assert_eq!((held.reserved, held.consumed), (5, 0));

    let cost = ObservedCostEvidence {
        amount: 3,
        evidence_digest: Digest32::of_bytes(b"provider usage meter"),
    };
    let reconciled = store
        .reconcile_authbus_provider_effect(
            &adapter,
            &intent.key,
            &request.reservation_id,
            Some(&cost),
        )
        .await
        .expect("settle");
    assert_eq!(reconciled.reservation.state, ReservationState::Settled);
    let settled = store
        .authbus_quota_state(&id("quota:provider"))
        .await
        .expect("quota")
        .expect("present");
    assert_eq!((settled.reserved, settled.consumed, settled.available()), (0, 3, Some(7)));
}
