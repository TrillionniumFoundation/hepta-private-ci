use std::collections::VecDeque;
use std::error::Error;
use std::fs;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MATRIX_BINDING_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::MatrixDeviceId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixHomeserverUrl;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixSyncBatchV2;
use codex_hepta_matrix_protocol::MatrixSyncDecisionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationBodyV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationV2;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_sdk::IngressDisposition;
use codex_hepta_matrix_sdk::IngressIgnoredReason;
use codex_hepta_matrix_sdk::MatrixIngress;
use codex_hepta_matrix_sdk::MatrixOutboundTransport;
use codex_hepta_matrix_sdk::MatrixSdkPaths;
use codex_hepta_matrix_sdk::MatrixSendFuture;
use codex_hepta_matrix_sdk::MatrixSidecarConfig;
use codex_hepta_matrix_sdk::MatrixSidecarConfigError;
use codex_hepta_matrix_sdk::MatrixTimelineEvent;
use codex_hepta_matrix_sdk::MatrixTransportError;
use codex_hepta_matrix_sdk::OutboxDispatchConfig;
use codex_hepta_matrix_sdk::dispatch_outbox_once;
use codex_hepta_matrix_sdk::run_outbox_sender;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDisposition;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::OutboxRecord;
use codex_hepta_matrix_store::OutboxState;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio_util::sync::CancellationToken;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

const FIRST_AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const SECOND_AGENT: &str = "019153a4-3088-7e03-a56a-9b1964f75dd3";
const AGENT_MXID: &str = "@agent:example.test";
const ALLOWED_SENDER: &str = "@owner:example.test";
const ALLOWED_ROOM: &str = "!allowed:example.test";

fn agent(value: &str) -> TestResult<AgentId> {
    Ok(AgentId::parse(value)?)
}

fn room(value: &str) -> TestResult<MatrixRoomId> {
    Ok(MatrixRoomId::parse(value)?)
}

fn user(value: &str) -> TestResult<MatrixUserId> {
    Ok(MatrixUserId::parse(value)?)
}

fn event(value: &str) -> TestResult<MatrixEventId> {
    Ok(MatrixEventId::parse(value)?)
}

fn layout(temp: &TempDir, agent_id: &AgentId) -> TestResult<HeptaAgentLayout> {
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root)?;
    let canonical = fleet_root.canonicalize()?;
    Ok(HeptaFleetRoot::parse(canonical)?.layout().agent(agent_id))
}

fn sidecar_config(agent_id: &AgentId) -> TestResult<MatrixSidecarConfig> {
    Ok(MatrixSidecarConfig {
        binding: MatrixBindingV1 {
            schema_version: MATRIX_BINDING_SCHEMA_VERSION,
            agent_id: agent_id.clone(),
            revision: 1,
            homeserver: MatrixHomeserverUrl::parse("https://example.test")?,
            expected_mxid: user(AGENT_MXID)?,
            expected_device_id: MatrixDeviceId::parse("DEVICE")?,
            allowed_rooms: vec![room(ALLOWED_ROOM)?],
            allowed_senders: vec![user(ALLOWED_SENDER)?],
            require_explicit_mention: true,
        },
        matrix_generation: 1,
        sync_timeline_limit: 32,
        sync_timeout: Duration::from_secs(1),
    })
}

async fn prepared_store(layout: &HeptaAgentLayout) -> TestResult<MatrixDurableStore> {
    let store = MatrixDurableStore::open(layout, MatrixDurableConfig::default()).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room(ALLOWED_ROOM)?,
            agent_user_id: user(AGENT_MXID)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    Ok(store)
}

fn timeline_event(
    event_id: &str,
    room_id: &str,
    sender: &str,
    mentions: Vec<MatrixUserId>,
) -> TestResult<MatrixTimelineEvent> {
    Ok(MatrixTimelineEvent {
        event_id: event(event_id)?,
        room_id: room(room_id)?,
        sender: user(sender)?,
        event_type: "m.room.message".to_string(),
        payload: br#"{"msgtype":"m.text","body":"hello"}"#.to_vec(),
        mentioned_user_ids: mentions,
        origin_server_ts_ms: 10,
        received_at_ms: 11,
    })
}

async fn enqueue_final(
    store: &MatrixDurableStore,
    agent_id: &AgentId,
    created_at_ms: u64,
) -> TestResult<OutboxRecord> {
    let room_id = room(ALLOWED_ROOM)?;
    let logical_outbox_id = outbox_id(agent_id, &room_id, "thread-1", "turn-1", "item-1", "final");
    let txn_id = transaction_id(&logical_outbox_id, 1)?;
    let disposition = store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id,
            revision: 1,
            txn_id,
            room_id,
            kind: OutboxKind::Final,
            payload: b"complete".to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms,
        })
        .await?;
    match disposition {
        OutboxDisposition::Enqueued(record) => Ok(record),
        OutboxDisposition::Coalesced(_) | OutboxDisposition::Duplicate(_) => {
            Err("fresh final outbox record was not enqueued".into())
        }
    }
}

struct FakeTransport {
    results: Mutex<VecDeque<Result<MatrixEventId, MatrixTransportError>>>,
    txn_ids: Mutex<Vec<MatrixTransactionId>>,
}

/// Models the exact response-loss window qualified against real Synapse: the
/// first PUT is accepted under the stable transaction ID, but its successful
/// response is hidden from the dispatcher before `mark_outbox_sent`.
struct PostSendAckLossTransport {
    accepted_event_id: MatrixEventId,
    txn_ids: Mutex<Vec<MatrixTransactionId>>,
}

impl PostSendAckLossTransport {
    fn new(accepted_event_id: MatrixEventId) -> Self {
        Self {
            accepted_event_id,
            txn_ids: Mutex::new(Vec::new()),
        }
    }

    fn txn_ids(&self) -> TestResult<Vec<MatrixTransactionId>> {
        Ok(self
            .txn_ids
            .lock()
            .map_err(|_| "post-send transaction log lock poisoned")?
            .clone())
    }
}

impl MatrixOutboundTransport for PostSendAckLossTransport {
    fn send<'a>(&'a self, record: &'a OutboxRecord) -> MatrixSendFuture<'a> {
        Box::pin(async move {
            let mut txn_ids = self
                .txn_ids
                .lock()
                .map_err(|_| MatrixTransportError::Permanent)?;
            txn_ids.push(record.stable_txn_id.clone());
            if txn_ids.len() == 1 {
                // The fake Synapse accepted `accepted_event_id`; only its
                // response is lost before the caller can mark the row sent.
                Err(MatrixTransportError::Retryable)
            } else {
                Ok(self.accepted_event_id.clone())
            }
        })
    }
}

impl FakeTransport {
    fn new(results: impl IntoIterator<Item = Result<MatrixEventId, MatrixTransportError>>) -> Self {
        Self {
            results: Mutex::new(results.into_iter().collect()),
            txn_ids: Mutex::new(Vec::new()),
        }
    }

    fn txn_ids(&self) -> TestResult<Vec<MatrixTransactionId>> {
        Ok(self
            .txn_ids
            .lock()
            .map_err(|_| "fake transaction log lock poisoned")?
            .clone())
    }
}

impl MatrixOutboundTransport for FakeTransport {
    fn send<'a>(&'a self, record: &'a OutboxRecord) -> MatrixSendFuture<'a> {
        Box::pin(async move {
            self.txn_ids
                .lock()
                .map_err(|_| MatrixTransportError::Permanent)?
                .push(record.stable_txn_id.clone());
            self.results
                .lock()
                .map_err(|_| MatrixTransportError::Permanent)?
                .pop_front()
                .unwrap_or(Err(MatrixTransportError::Permanent))
        })
    }
}

#[tokio::test]
async fn duplicate_sync_event_is_exactly_idempotent() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&layout).await?;
    let ingress = MatrixIngress::new(sidecar_config(&agent_id)?, store.clone());
    let event = timeline_event(
        "$same",
        ALLOWED_ROOM,
        ALLOWED_SENDER,
        vec![user(AGENT_MXID)?],
    )?;

    assert_eq!(
        ingress.ingest(event.clone()).await?,
        IngressDisposition::Accepted
    );
    assert_eq!(ingress.ingest(event).await?, IngressDisposition::Duplicate);
    assert_eq!(store.pending_inbox(10).await?.len(), 1);
    assert_eq!(ingress.metrics().accepted, 1);
    assert_eq!(ingress.metrics().duplicate, 1);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn exact_room_sender_and_mention_gate_precedes_persistence() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&layout).await?;
    let ingress = MatrixIngress::new(sidecar_config(&agent_id)?, store.clone());

    assert_eq!(
        ingress
            .ingest(timeline_event(
                "$wrong-room",
                "!other:example.test",
                ALLOWED_SENDER,
                vec![user(AGENT_MXID)?],
            )?)
            .await?,
        IngressDisposition::Ignored(IngressIgnoredReason::WrongRoom)
    );
    assert_eq!(
        ingress
            .ingest(timeline_event(
                "$wrong-sender",
                ALLOWED_ROOM,
                "@intruder:example.test",
                vec![user(AGENT_MXID)?],
            )?)
            .await?,
        IngressDisposition::Ignored(IngressIgnoredReason::WrongSender)
    );
    assert_eq!(
        ingress
            .ingest(timeline_event(
                "$missing-mention",
                ALLOWED_ROOM,
                ALLOWED_SENDER,
                Vec::new(),
            )?)
            .await?,
        IngressDisposition::Ignored(IngressIgnoredReason::MissingExplicitMention)
    );
    assert!(store.pending_inbox(10).await?.is_empty());
    assert_eq!(ingress.metrics().ignored, 3);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn malformed_remote_event_is_nonfatal_and_does_not_block_the_next_event() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&layout).await?;
    let ingress = MatrixIngress::new(sidecar_config(&agent_id)?, store.clone());

    assert_eq!(
        ingress.record_malformed_event(),
        IngressDisposition::Ignored(IngressIgnoredReason::MalformedEvent)
    );
    assert!(!ingress.fatal());
    assert_eq!(ingress.metrics().malformed, 1);
    assert_eq!(ingress.metrics().failed, 0);
    assert_eq!(
        ingress
            .ingest(timeline_event(
                "$valid-after-malformed",
                ALLOWED_ROOM,
                ALLOWED_SENDER,
                vec![user(AGENT_MXID)?],
            )?)
            .await?,
        IngressDisposition::Accepted
    );
    assert_eq!(store.pending_inbox(10).await?.len(), 1);
    assert!(!ingress.fatal());
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn expired_crash_lease_reuses_the_stable_transaction_after_reopen() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&layout).await?;
    let original = enqueue_final(&store, &agent_id, 10).await?;
    let claimed = store.claim_outbox(10, 20, 1).await?;
    assert_eq!(claimed.len(), 1);
    assert_eq!(claimed[0].stable_txn_id, original.stable_txn_id);
    store.close().await;

    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let sent_event = event("$sent-after-reopen")?;
    let transport = FakeTransport::new([Ok(sent_event.clone())]);
    let stats = dispatch_outbox_once(
        &reopened,
        &transport,
        &OutboxDispatchConfig {
            lease_ms: 20,
            retry_delay_ms: 10,
            max_retry_delay_ms: 40,
            max_attempts: 3,
            claim_limit: 1,
            idle_poll: Duration::from_millis(10),
        },
        &CancellationToken::new(),
        31,
    )
    .await?;
    assert_eq!(stats.sent, 1);
    assert_eq!(transport.txn_ids()?, vec![original.stable_txn_id.clone()]);
    let stored = reopened
        .outbox_for_txn(&original.stable_txn_id)
        .await?
        .ok_or("sent outbox record disappeared")?;
    assert_eq!(stored.state, OutboxState::Sent);
    assert_eq!(stored.sent_event_id, Some(sent_event));
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn retry_preserves_stable_transaction_and_shutdown_is_bounded() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&layout).await?;
    let original = enqueue_final(&store, &agent_id, 10).await?;
    let transport = FakeTransport::new([
        Err(MatrixTransportError::Retryable),
        Ok(event("$sent-after-retry")?),
    ]);
    let config = OutboxDispatchConfig {
        lease_ms: 20,
        retry_delay_ms: 10,
        max_retry_delay_ms: 40,
        max_attempts: 3,
        claim_limit: 1,
        idle_poll: Duration::from_millis(10),
    };
    let cancel = CancellationToken::new();

    assert_eq!(
        dispatch_outbox_once(&store, &transport, &config, &cancel, 10)
            .await?
            .retry_scheduled,
        1
    );
    let next_attempt_at_ms = store
        .outbox_for_txn(&original.stable_txn_id)
        .await?
        .ok_or("retry record disappeared")?
        .next_attempt_at_ms;
    assert_eq!(
        dispatch_outbox_once(&store, &transport, &config, &cancel, next_attempt_at_ms)
            .await?
            .sent,
        1
    );
    assert_eq!(
        transport.txn_ids()?,
        vec![
            original.stable_txn_id.clone(),
            original.stable_txn_id.clone()
        ]
    );

    cancel.cancel();
    tokio::time::timeout(
        Duration::from_millis(250),
        run_outbox_sender(&store, &transport, &config, &cancel),
    )
    .await??;
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn post_send_ack_loss_reuses_txn_and_commits_same_synapse_event_id() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&layout).await?;
    let original = enqueue_final(&store, &agent_id, 10).await?;
    let accepted_event_id = event("$synapse-accepted-before-ack-loss")?;
    let transport = PostSendAckLossTransport::new(accepted_event_id.clone());
    let config = OutboxDispatchConfig {
        lease_ms: 20,
        retry_delay_ms: 10,
        max_retry_delay_ms: 40,
        max_attempts: 3,
        claim_limit: 1,
        idle_poll: Duration::from_millis(10),
    };
    let cancel = CancellationToken::new();

    let first = dispatch_outbox_once(&store, &transport, &config, &cancel, 10).await?;
    assert_eq!(first.retry_scheduled, 1);
    let after_response_loss = store
        .outbox_for_txn(&original.stable_txn_id)
        .await?
        .ok_or("response-loss outbox row disappeared")?;
    assert_eq!(after_response_loss.state, OutboxState::RetryScheduled);
    assert_eq!(after_response_loss.sent_event_id, None);

    let second = dispatch_outbox_once(
        &store,
        &transport,
        &config,
        &cancel,
        after_response_loss.next_attempt_at_ms,
    )
    .await?;
    assert_eq!(second.sent, 1);
    assert_eq!(
        transport.txn_ids()?,
        vec![
            original.stable_txn_id.clone(),
            original.stable_txn_id.clone(),
        ]
    );
    let committed = store
        .outbox_for_txn(&original.stable_txn_id)
        .await?
        .ok_or("sent outbox row disappeared")?;
    assert_eq!(committed.state, OutboxState::Sent);
    assert_eq!(committed.attempts, 2);
    assert_eq!(committed.sent_event_id, Some(accepted_event_id));
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn unknown_send_result_exhausts_retry_budget_without_claiming_terminal_failure() -> TestResult
{
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&layout).await?;
    let original = enqueue_final(&store, &agent_id, 10).await?;
    let transport = FakeTransport::new([
        Err(MatrixTransportError::Retryable),
        Err(MatrixTransportError::Retryable),
        Err(MatrixTransportError::Retryable),
    ]);
    let config = OutboxDispatchConfig {
        lease_ms: 20,
        retry_delay_ms: 10,
        max_retry_delay_ms: 25,
        max_attempts: 3,
        claim_limit: 1,
        idle_poll: Duration::from_millis(10),
    };
    let cancel = CancellationToken::new();

    assert_eq!(
        dispatch_outbox_once(&store, &transport, &config, &cancel, 10)
            .await?
            .retry_scheduled,
        1
    );
    let first_retry = store
        .outbox_for_txn(&original.stable_txn_id)
        .await?
        .ok_or("first retry record disappeared")?;
    assert_eq!(
        first_retry.next_attempt_at_ms,
        first_retry.updated_at_ms + 10
    );
    assert_eq!(
        dispatch_outbox_once(
            &store,
            &transport,
            &config,
            &cancel,
            first_retry.next_attempt_at_ms
        )
        .await?
        .retry_scheduled,
        1
    );
    let second_retry = store
        .outbox_for_txn(&original.stable_txn_id)
        .await?
        .ok_or("second retry record disappeared")?;
    assert_eq!(
        second_retry.next_attempt_at_ms,
        second_retry.updated_at_ms + 20
    );
    assert_eq!(
        dispatch_outbox_once(
            &store,
            &transport,
            &config,
            &cancel,
            second_retry.next_attempt_at_ms
        )
        .await?
        .needs_reconciliation,
        1
    );
    let unresolved = store
        .outbox_for_txn(&original.stable_txn_id)
        .await?
        .ok_or("unresolved outbox record disappeared")?;
    assert_eq!(
        (
            unresolved.state,
            unresolved.attempts,
            unresolved.sent_event_id
        ),
        (OutboxState::InFlight, 3, None)
    );
    let markers = store.unresolved_outbox(/*limit*/ 10).await?;
    assert_eq!(markers.len(), 1);
    assert_eq!(
        (markers[0].stable_txn_id.clone(), markers[0].attempts),
        (original.stable_txn_id.clone(), 3)
    );
    assert_eq!(
        transport.txn_ids()?,
        vec![
            original.stable_txn_id.clone(),
            original.stable_txn_id.clone(),
            original.stable_txn_id.clone()
        ]
    );
    store.close().await;
    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    assert_eq!(reopened.unresolved_outbox(/*limit*/ 10).await?, markers);
    let after_reopen =
        dispatch_outbox_once(&reopened, &transport, &config, &cancel, 10_000).await?;
    assert_eq!((after_reopen.claimed, transport.txn_ids()?.len()), (0, 3));
    reopened.close().await;
    Ok(())
}

#[test]
fn sdk_store_paths_are_private_and_per_agent() -> TestResult {
    let temp = TempDir::new()?;
    let first = agent(FIRST_AGENT)?;
    let second = agent(SECOND_AGENT)?;
    let first_layout = layout(&temp, &first)?;
    let second_layout = layout(&temp, &second)?;
    let first_paths = MatrixSdkPaths::prepare(&first_layout, &sidecar_config(&first)?)?;
    let second_paths = MatrixSdkPaths::prepare(&second_layout, &sidecar_config(&second)?)?;

    assert_ne!(first_paths.root(), second_paths.root());
    assert!(first_paths.root().starts_with(first_layout.matrix_root()));
    assert!(second_paths.root().starts_with(second_layout.matrix_root()));
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        assert_eq!(
            fs::metadata(first_paths.root())?.permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(
            fs::metadata(first_paths.state())?.permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(
            fs::metadata(first_paths.cache())?.permissions().mode() & 0o777,
            0o700
        );
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn sdk_store_directory_links_cannot_redirect_creation_or_permissions() -> TestResult {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    for component in ["matrix", "matrix-sdk-0.18", "state", "cache"] {
        let temp = TempDir::new()?;
        let owner = agent(FIRST_AGENT)?;
        let agent_layout = layout(&temp, &owner)?;
        let sdk_root = agent_layout.matrix_root().join("matrix-sdk-0.18");
        let blocked = match component {
            "matrix" => agent_layout.matrix_root().to_path_buf(),
            "matrix-sdk-0.18" => sdk_root,
            "state" | "cache" => sdk_root.join(component),
            _ => unreachable!(),
        };
        fs::create_dir_all(blocked.parent().ok_or("missing parent")?)?;
        let outside = temp.path().join("other-agent-store");
        fs::create_dir(&outside)?;
        fs::set_permissions(&outside, fs::Permissions::from_mode(0o755))?;
        fs::write(outside.join("sentinel"), b"other Agent state")?;
        symlink(&outside, &blocked)?;

        assert_eq!(
            MatrixSdkPaths::prepare(&agent_layout, &sidecar_config(&owner)?),
            Err(MatrixSidecarConfigError::Unavailable),
            "must reject linked {component} before creating or chmodding targets"
        );
        assert_eq!(
            (
                fs::read(outside.join("sentinel"))?,
                fs::read_dir(&outside)?.count(),
                fs::metadata(&outside)?.permissions().mode() & 0o777
            ),
            (b"other Agent state".to_vec(), 1, 0o755)
        );
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn sdk_database_and_journal_links_are_rejected_before_sqlite_open() -> TestResult {
    use std::os::unix::fs::symlink;

    for (directory, database) in [
        ("state", "matrix-sdk-state.sqlite3"),
        ("state", "matrix-sdk-crypto.sqlite3"),
        ("cache", "matrix-sdk-event-cache.sqlite3"),
    ] {
        for suffix in ["", "-wal", "-shm", "-journal"] {
            for hard_link in [false, true] {
                let temp = TempDir::new()?;
                let owner = agent(FIRST_AGENT)?;
                let agent_layout = layout(&temp, &owner)?;
                let config = sidecar_config(&owner)?;
                let paths = MatrixSdkPaths::prepare(&agent_layout, &config)?;
                let outside = temp.path().join("other-agent.sqlite3");
                fs::write(&outside, b"other Agent database")?;
                let blocked = paths
                    .root()
                    .join(directory)
                    .join(format!("{database}{suffix}"));
                if hard_link {
                    fs::hard_link(&outside, &blocked)?;
                } else {
                    symlink(&outside, &blocked)?;
                }
                assert_eq!(
                    MatrixSdkPaths::prepare(&agent_layout, &config),
                    Err(MatrixSidecarConfigError::Unavailable),
                    "linked database/journal must not enter SQLite"
                );
                assert_eq!(fs::read(&outside)?, b"other Agent database");
            }
        }
    }
    Ok(())
}

#[path = "support/outbound_boundaries.rs"]
mod outbound_boundaries;
