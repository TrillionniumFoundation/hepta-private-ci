#![cfg(unix)]
//! Exercise the real kernel verifier and SQLite owner with a lazy fake transport.
//! These are not homeserver, encrypted-session or production-key receipts.
use std::collections::BTreeSet;
use std::error::Error;
use std::fs;
use std::fs::File;
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixSyncBatchV2;
use codex_hepta_matrix_protocol::MatrixSyncDecisionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationBodyV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationV2;
use codex_hepta_matrix_protocol::MatrixSyncResultV2;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_sdk::MatrixAuthorityError;
use codex_hepta_matrix_sdk::MatrixFinalUseRequest;
use codex_hepta_matrix_sdk::MatrixGrantFuture;
use codex_hepta_matrix_sdk::MatrixOutboundAuthorizer;
use codex_hepta_matrix_sdk::MatrixOutboundIdentity;
use codex_hepta_matrix_sdk::MatrixOutboundTransport;
use codex_hepta_matrix_sdk::MatrixRawSendSeal;
use codex_hepta_matrix_sdk::MatrixSendFuture;
use codex_hepta_matrix_sdk::MatrixTransportError;
use codex_hepta_matrix_sdk::OutboxDispatchConfig;
use codex_hepta_matrix_sdk::dispatch_outbox_once;
use codex_hepta_matrix_store::MatrixAttemptFailureClass;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::OutboxRecord;
use codex_hepta_matrix_store::OutboxState;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio_util::sync::CancellationToken;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const ROOM_ID: &str = "!allowed:example.test";
const AGENT_USER_ID: &str = "@agent:example.test";
const ACCEPTED_EVENT_ID: &str = "$transport-accepted";

fn now_ms() -> TestResult<u64> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

fn test_material() -> TestResult<[u8; 32]> {
    let mut material = [0_u8; 32];
    File::open("/dev/urandom")?.read_exact(&mut material)?;
    Ok(material)
}

fn layout(temp: &TempDir) -> TestResult<codex_hepta_paths::HeptaAgentLayout> {
    let root = temp.path().join("fleet");
    let agent = AgentId::parse(AGENT_ID)?;
    Ok(HeptaFleetRoot::parse(root.canonicalize()?)?
        .layout()
        .agent(&agent))
}

async fn fixture(
    count: usize,
) -> TestResult<(TempDir, MatrixDurableStore, Vec<MatrixTransactionId>)> {
    let temp = TempDir::new()?;
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root)?;
    let agent = AgentId::parse(AGENT_ID)?;
    let layout = HeptaFleetRoot::parse(root.canonicalize()?)?
        .layout()
        .agent(&agent);
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room = MatrixRoomId::parse(ROOM_ID)?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room.clone(),
            agent_user_id: MatrixUserId::parse(AGENT_USER_ID)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    let mut ids = Vec::new();
    for index in 0..count {
        let logical = outbox_id(
            &agent,
            &room,
            "thread",
            "turn",
            &format!("item-{index}"),
            "final",
        );
        let txn = transaction_id(&logical, /*revision*/ 1)?;
        store
            .enqueue_outbox(&OutboxDraft {
                logical_outbox_id: logical,
                revision: 1,
                txn_id: txn.clone(),
                room_id: room.clone(),
                kind: OutboxKind::Final,
                payload: b"complete".to_vec(),
                binding_revision: 1,
                generation: 1,
                created_at_ms: 2,
            })
            .await?;
        ids.push(txn);
    }
    Ok((temp, store, ids))
}

async fn observe_outbound(
    store: &MatrixDurableStore,
    txn_id: MatrixTransactionId,
    event_id: MatrixEventId,
    observed_at_ms: u64,
) -> TestResult {
    let decision = MatrixSyncDecisionV2::Commit {
        batch: MatrixSyncBatchV2 {
            schema_version: 2,
            operation_id: format!("normal-send-observation-{observed_at_ms}"),
            checkpoint_revision: 1,
            checkpoint_generation: 1,
            expected_next_batch: None,
            next_batch: format!("normal-send-sync-{observed_at_ms}"),
            observed_at_ms,
            mutations: vec![MatrixSyncMutationV2 {
                source_event_id: event_id,
                room_id: MatrixRoomId::parse(ROOM_ID)?,
                sender: MatrixUserId::parse(AGENT_USER_ID)?,
                transaction_id: Some(txn_id),
                binding_revision: 1,
                generation: 1,
                origin_server_ts_ms: observed_at_ms,
                received_at_ms: observed_at_ms,
                body: MatrixSyncMutationBodyV2::Timeline {
                    event_type: "m.room.message".to_string(),
                    payload: br#"{"msgtype":"m.text","body":"observed outbound"}"#.to_vec(),
                },
            }],
        },
    };
    assert!(matches!(
        store.apply_sync_decision_v2(&decision).await?,
        MatrixSyncResultV2::Committed { .. }
    ));
    Ok(())
}

struct Authorizer {
    authority: FinalUseAuthority,
    key: SigningKey,
    _directory: TempDir,
    sequence: AtomicU64,
    refreshes: AtomicU64,
    revoke_on_second_refresh: bool,
    revoke_on_third_refresh: bool,
    delay: Duration,
}

impl Authorizer {
    fn new() -> TestResult<Self> {
        let directory = TempDir::new()?;
        fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700))?;
        let key = SigningKey::from_bytes(&test_material()?);
        let authority = FinalUseAuthority::open_state_dir(
            directory.path(),
            "matrix-poll-test".to_string(),
            key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 17,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        Ok(Self {
            authority,
            key,
            _directory: directory,
            sequence: AtomicU64::new(0),
            refreshes: AtomicU64::new(0),
            revoke_on_second_refresh: false,
            revoke_on_third_refresh: false,
            delay: Duration::ZERO,
        })
    }
}

impl MatrixOutboundAuthorizer for Authorizer {
    fn authority(&self) -> &FinalUseAuthority {
        &self.authority
    }

    fn signed_grant<'a>(&'a self, request: &'a MatrixFinalUseRequest) -> MatrixGrantFuture<'a> {
        Box::pin(async move {
            tokio::time::sleep(self.delay).await;
            let sequence = self.sequence.fetch_add(1, Ordering::SeqCst) + 1;
            let now = now_ms().map_err(|_| MatrixAuthorityError::Unavailable)?;
            let nonce = test_material().map_err(|_| MatrixAuthorityError::Unavailable)?;
            let grant = FinalUseGrant {
                schema_version: 1,
                signer_id: "matrix-poll-test".to_string(),
                authority_epoch: 17,
                grant_id: format!("poll-grant-{sequence}"),
                nonce,
                binding: request.binding.clone(),
                not_before_unix_ms: now.saturating_sub(1_000),
                expires_at_unix_ms: now.saturating_add(60_000),
            };
            let bytes = grant
                .signing_bytes()
                .map_err(|_| MatrixAuthorityError::InvalidBinding)?;
            let signature = self.key.sign(&bytes).to_bytes().to_vec();
            Ok(SignedFinalUseGrant { grant, signature })
        })
    }

    fn refresh_revocations(&self) -> Result<(), MatrixAuthorityError> {
        let refresh = self.refreshes.fetch_add(1, Ordering::SeqCst) + 1;
        if (refresh == 2 && self.revoke_on_second_refresh)
            || (refresh == 3 && self.revoke_on_third_refresh)
        {
            self.authority
                .update_revocations(FinalUseRevocations {
                    authority_epoch: 17,
                    revision: 2,
                    revoked_grant_ids: BTreeSet::from(["poll-grant-1".to_string()]),
                })
                .map_err(|_| MatrixAuthorityError::Unavailable)?;
        }
        Ok(())
    }
}

struct Transport {
    polls: AtomicU64,
    identity_reads: AtomicU64,
    rotate_identity: bool,
    error: Option<MatrixTransportError>,
    wait_forever: bool,
    cancel_after_entry: Option<CancellationToken>,
}

impl Transport {
    fn new() -> Self {
        Self {
            polls: AtomicU64::new(0),
            identity_reads: AtomicU64::new(0),
            rotate_identity: false,
            error: None,
            wait_forever: false,
            cancel_after_entry: None,
        }
    }
}

impl MatrixOutboundTransport for Transport {
    fn identity(&self) -> Result<MatrixOutboundIdentity, MatrixTransportError> {
        let second = self.identity_reads.fetch_add(1, Ordering::SeqCst) > 0;
        Ok(MatrixOutboundIdentity {
            homeserver_id: "https://example.test".to_string(),
            matrix_user_id: AGENT_USER_ID.to_string(),
            device_id: if second && self.rotate_identity {
                "ROTATED"
            } else {
                "DEVICE"
            }
            .to_string(),
            session_generation: 1,
        })
    }

    fn send<'a>(
        &'a self,
        _record: &'a OutboxRecord,
        _seal: MatrixRawSendSeal,
    ) -> MatrixSendFuture<'a> {
        Box::pin(async move {
            self.polls.fetch_add(1, Ordering::SeqCst);
            if let Some(cancel) = &self.cancel_after_entry {
                cancel.cancel();
            }
            if self.wait_forever {
                return std::future::pending().await;
            }
            match self.error {
                Some(error) => Err(error),
                None => MatrixEventId::parse(ACCEPTED_EVENT_ID)
                    .map_err(|_| MatrixTransportError::ResponseLost),
            }
        })
    }
}

fn config() -> OutboxDispatchConfig {
    OutboxDispatchConfig {
        lease_ms: 5_000,
        max_attempts: 1,
        ..OutboxDispatchConfig::default()
    }
}

#[tokio::test]
async fn revocation_after_persistence_prevents_first_transport_poll_and_releases_batch()
-> TestResult {
    let (_temp, store, _) = fixture(/*count*/ 3).await?;
    let mut authority = Authorizer::new()?;
    authority.revoke_on_second_refresh = true;
    let transport = Transport::new();
    let result = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &config(),
        &CancellationToken::new(),
        now_ms()?,
    )
    .await;
    assert!(result.is_err());
    assert_eq!(transport.polls.load(Ordering::SeqCst), 0);
    assert_eq!(authority.refreshes.load(Ordering::SeqCst), 2);
    let remaining = store
        .claim_outbox_fenced(now_ms()?, /*lease_ms*/ 5_000, /*limit*/ 3)
        .await?;
    assert_eq!(remaining.len(), 3);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn revocation_after_entered_use_is_indeterminate_and_never_released_as_pre_entry()
-> TestResult {
    let (_temp, store, ids) = fixture(/*count*/ 1).await?;
    let mut authority = Authorizer::new()?;
    authority.revoke_on_third_refresh = true;
    let transport = Transport::new();
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &config(),
        &CancellationToken::new(),
        now_ms()?,
    )
    .await?;
    assert_eq!(authority.refreshes.load(Ordering::SeqCst), 3);
    assert_eq!(transport.polls.load(Ordering::SeqCst), 0);
    assert_eq!(stats.indeterminate, 1);
    assert_eq!(stats.permanent_failure, 0);
    let record = store
        .dispatch_for_txn(&ids[0])
        .await?
        .ok_or("missing ledger")?;
    assert_eq!(record.state, MatrixDispatchState::Indeterminate);
    let events = store.dispatch_attempt_events(&ids[0]).await?;
    assert!(
        events
            .iter()
            .any(|event| { event.failure_class == Some(MatrixAttemptFailureClass::ResponseLost) })
    );
    let reclaim = store.claim_outbox_fenced(now_ms()?, 5_000, 1).await?;
    assert!(reclaim.is_empty());
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn identity_rotation_during_authorization_prevents_adapter_entry() -> TestResult {
    let (_temp, store, _) = fixture(/*count*/ 1).await?;
    let authority = Authorizer::new()?;
    let mut transport = Transport::new();
    transport.rotate_identity = true;
    assert!(
        dispatch_outbox_once(
            &store,
            &transport,
            &authority,
            &config(),
            &CancellationToken::new(),
            now_ms()?,
        )
        .await
        .is_err()
    );
    assert_eq!(transport.polls.load(Ordering::SeqCst), 0);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn canceled_before_claim_does_not_consume_a_lease() -> TestResult {
    let (_temp, store, _) = fixture(/*count*/ 1).await?;
    let authority = Authorizer::new()?;
    let transport = Transport::new();
    let cancel = CancellationToken::new();
    cancel.cancel();
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &config(),
        &cancel,
        now_ms()?,
    )
    .await?;
    assert!(stats.cancelled);
    assert_eq!(stats.claimed, 0);
    assert_eq!(transport.polls.load(Ordering::SeqCst), 0);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn broker_wait_consumes_the_existing_lease_not_a_fresh_timeout() -> TestResult {
    let (_temp, store, _) = fixture(/*count*/ 1).await?;
    let mut authority = Authorizer::new()?;
    authority.delay = Duration::from_secs(10);
    let transport = Transport::new();
    let config = OutboxDispatchConfig {
        lease_ms: 1_000,
        ..config()
    };
    let result = tokio::time::timeout(
        Duration::from_secs(3),
        dispatch_outbox_once(
            &store,
            &transport,
            &authority,
            &config,
            &CancellationToken::new(),
            now_ms()?,
        ),
    )
    .await?;
    assert!(result.is_err());
    assert_eq!(transport.polls.load(Ordering::SeqCst), 0);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn transport_acceptance_alone_never_counts_as_confirmed_delivery() -> TestResult {
    let (_temp, store, ids) = fixture(/*count*/ 1).await?;
    let authority = Authorizer::new()?;
    let transport = Transport::new();
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &config(),
        &CancellationToken::new(),
        now_ms()?,
    )
    .await?;
    assert_eq!(stats.transport_accepted, 1);
    assert_eq!(stats.sent, 0);
    assert_eq!(
        store
            .dispatch_for_txn(&ids[0])
            .await?
            .ok_or("missing ledger")?
            .state,
        MatrixDispatchState::Accepted
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn normal_send_confirms_only_after_sync_and_survives_reopen() -> TestResult {
    let (temp, store, ids) = fixture(/*count*/ 1).await?;
    let authority = Authorizer::new()?;
    let transport = Transport::new();
    let accepted_at_ms = now_ms()?;
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &config(),
        &CancellationToken::new(),
        accepted_at_ms,
    )
    .await?;
    assert_eq!(stats.transport_accepted, 1);
    assert_eq!(stats.sent, 0);
    assert_eq!(
        store
            .dispatch_for_txn(&ids[0])
            .await?
            .ok_or("missing accepted dispatch")?
            .state,
        MatrixDispatchState::Accepted
    );

    let accepted = store
        .outbox_for_txn(&ids[0])
        .await?
        .ok_or("missing accepted outbox")?;
    let event_id = MatrixEventId::parse(ACCEPTED_EVENT_ID)?;
    observe_outbound(
        &store,
        ids[0].clone(),
        event_id.clone(),
        accepted.updated_at_ms.saturating_add(1),
    )
    .await?;
    assert_eq!(
        store
            .dispatch_for_txn(&ids[0])
            .await?
            .ok_or("missing confirmed dispatch")?
            .state,
        MatrixDispatchState::Succeeded
    );
    let settled = store
        .outbox_for_txn(&ids[0])
        .await?
        .ok_or("missing settled outbox")?;
    assert_eq!(settled.state, OutboxState::Sent);
    assert_eq!(settled.sent_event_id, Some(event_id.clone()));
    store.close().await;

    let reopened = MatrixDurableStore::open(&layout(&temp)?, MatrixDurableConfig::default()).await?;
    assert_eq!(
        reopened
            .dispatch_for_txn(&ids[0])
            .await?
            .ok_or("confirmed dispatch did not survive reopen")?
            .state,
        MatrixDispatchState::Succeeded
    );
    let reopened_outbox = reopened
        .outbox_for_txn(&ids[0])
        .await?
        .ok_or("settled outbox did not survive reopen")?;
    assert_eq!(reopened_outbox.state, OutboxState::Sent);
    assert_eq!(reopened_outbox.sent_event_id, Some(event_id));
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn cancellation_after_first_poll_stays_indeterminate() -> TestResult {
    let (_temp, store, ids) = fixture(/*count*/ 1).await?;
    let authority = Authorizer::new()?;
    let cancel = CancellationToken::new();
    let mut transport = Transport::new();
    transport.wait_forever = true;
    transport.cancel_after_entry = Some(cancel.clone());
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &config(),
        &cancel,
        now_ms()?,
    )
    .await?;
    assert_eq!(transport.polls.load(Ordering::SeqCst), 1);
    assert_eq!(stats.permanent_failure, 0);
    assert!(stats.cancelled);
    assert_eq!(
        store
            .dispatch_for_txn(&ids[0])
            .await?
            .ok_or("missing ledger")?
            .state,
        MatrixDispatchState::Indeterminate
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn read_timeout_parks_the_same_transaction_and_retains_the_error_class() -> TestResult {
    let (_temp, store, ids) = fixture(/*count*/ 1).await?;
    let authority = Authorizer::new()?;
    let mut transport = Transport::new();
    transport.wait_forever = true;
    let config = OutboxDispatchConfig {
        lease_ms: 1_000,
        ..config()
    };
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &config,
        &CancellationToken::new(),
        now_ms()?,
    )
    .await?;
    assert_eq!(stats.indeterminate, 1);
    assert_eq!(stats.permanent_failure, 0);
    assert_eq!(transport.polls.load(Ordering::SeqCst), 1);
    let events = store.dispatch_attempt_events(&ids[0]).await?;
    assert!(
        events
            .iter()
            .any(|event| event.failure_class == Some(MatrixAttemptFailureClass::ReadTimeout))
    );
    assert_eq!(
        store
            .dispatch_for_txn(&ids[0])
            .await?
            .ok_or("missing ledger")?
            .state,
        MatrixDispatchState::Indeterminate
    );
    store.close().await;
    Ok(())
}

#[path = "final_poll_regressions/optimization.rs"]
mod optimization;
