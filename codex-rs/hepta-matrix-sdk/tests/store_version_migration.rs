use std::collections::BTreeMap;
use std::error::Error;
use std::fs;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MATRIX_BINDING_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::MatrixDeviceId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixHomeserverUrl;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_sdk::MatrixSdkClient;
use codex_hepta_matrix_sdk::MatrixSdkPaths;
use codex_hepta_matrix_sdk::MatrixSession;
use codex_hepta_matrix_sdk::MatrixSidecarConfig;
use codex_hepta_matrix_store::InboxDraft;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use matrix_sdk::SessionMeta;
use matrix_sdk::SessionTokens;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;
const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const USER: &str = "@migration:example.test";
const ROOM: &str = "!migration:example.test";
const PASSPHRASE: &str = "human passphrase for the migration fixture";
const CUSTOM_KEY: &[u8] = b"hepta-migration-state";
const CUSTOM_VALUE: &[u8] = b"persisted before the SDK dependency update";

fn fixture_config(root: &Path) -> TestResult<(HeptaAgentLayout, MatrixSidecarConfig)> {
    let fleet = root.join("fleet");
    fs::create_dir_all(&fleet)?;
    let agent = AgentId::parse(AGENT)?;
    let layout = HeptaFleetRoot::parse(fleet.canonicalize()?)?
        .layout()
        .agent(&agent);
    let config = MatrixSidecarConfig {
        binding: MatrixBindingV1 {
            schema_version: MATRIX_BINDING_SCHEMA_VERSION,
            agent_id: agent,
            revision: 1,
            homeserver: MatrixHomeserverUrl::parse("https://example.test")?,
            expected_mxid: MatrixUserId::parse(USER)?,
            expected_device_id: MatrixDeviceId::parse("MIGRATION")?,
            allowed_rooms: vec![MatrixRoomId::parse(ROOM)?],
            allowed_senders: vec![MatrixUserId::parse("@owner:example.test")?],
            require_explicit_mention: true,
        },
        matrix_generation: 1,
        sync_timeline_limit: 32,
        sync_timeout: Duration::from_secs(1),
    };
    Ok((layout, config))
}

fn fixture_session() -> TestResult<MatrixSession> {
    Ok(MatrixSession {
        meta: SessionMeta {
            user_id: USER.try_into()?,
            device_id: "MIGRATION".into(),
        },
        tokens: SessionTokens {
            access_token: "local-fixture-access-token".to_owned(),
            refresh_token: Some("local-fixture-refresh-token".to_owned()),
        },
    })
}

fn inbox_event() -> TestResult<InboxDraft> {
    Ok(InboxDraft {
        event_id: MatrixEventId::parse("$migration-event")?,
        room_id: MatrixRoomId::parse(ROOM)?,
        sender: MatrixUserId::parse("@owner:example.test")?,
        event_type: "m.room.message".to_owned(),
        payload: br#"{"msgtype":"m.text","body":"durable migration input"}"#.to_vec(),
        binding_revision: 1,
        generation: 1,
        origin_server_ts_ms: 10,
        received_at_ms: 11,
    })
}

fn outbox_draft() -> TestResult<OutboxDraft> {
    let room = MatrixRoomId::parse(ROOM)?;
    let logical_id = outbox_id(
        &AgentId::parse(AGENT)?,
        &room,
        "thread-migration",
        "turn-migration",
        "item-migration",
        "final",
    );
    Ok(OutboxDraft {
        txn_id: transaction_id(&logical_id, /*revision*/ 1)?,
        logical_outbox_id: logical_id,
        revision: 1,
        room_id: room,
        kind: OutboxKind::Final,
        payload: b"durable migration output".to_vec(),
        binding_revision: 1,
        generation: 1,
        created_at_ms: 12,
    })
}

async fn stored_values(
    client: &matrix_sdk::Client,
    store: &MatrixDurableStore,
) -> TestResult<Value> {
    let device = client
        .encryption()
        .get_own_device()
        .await?
        .ok_or("missing persisted encryption identity")?;
    let device_keys: BTreeMap<_, _> = device
        .keys()
        .iter()
        .map(|(key_id, key)| (key_id.to_string(), key.to_base64()))
        .collect();
    assert!(!device_keys.is_empty(), "missing persisted encryption keys");
    let checkpoint = store
        .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
        .await?
        .ok_or("missing durable sync cursor")?;
    let outbox = store
        .outbox_for_txn(&outbox_draft()?.txn_id)
        .await?
        .ok_or("missing pending outbox")?;
    Ok(json!({
        "session": client.matrix_auth().session(),
        "device_keys": device_keys,
        "custom_value": client.state_store().get_custom_value(CUSTOM_KEY).await?,
        "checkpoint": {
            "owner": checkpoint.owner_agent_id,
            "binding_revision": checkpoint.binding_revision,
            "generation": checkpoint.generation,
            "next_batch": checkpoint.next_batch,
            "updated_at_ms": checkpoint.updated_at_ms,
        },
        "outbox": {
            "id": outbox.outbox_id,
            "txn": outbox.stable_txn_id,
            "room": outbox.room_id,
            "kind": outbox.kind,
            "payload": outbox.payload,
            "logical_txn_count": outbox.logical_txn_count,
            "binding_revision": outbox.binding_revision,
            "generation": outbox.generation,
            "state": outbox.state,
            "attempts": outbox.attempts,
            "next_attempt_at_ms": outbox.next_attempt_at_ms,
            "lease_until_ms": outbox.lease_until_ms,
            "created_at_ms": outbox.created_at_ms,
            "updated_at_ms": outbox.updated_at_ms,
            "sent_event_id": outbox.sent_event_id,
            "replaces_event_id": outbox.replaces_event_id,
        },
    }))
}

async fn prepare_fixture(root: &Path) -> TestResult {
    let expected_path = root.join("expected.json");
    assert!(
        !expected_path.exists(),
        "refuse to overwrite a baseline fixture"
    );
    let (layout, config) = fixture_config(root)?;
    // Produce the old SDK's real encrypted format independently of the
    // host's cold-start deadline. The old source and production timeout are
    // unchanged; this fixture qualifies migration, not cold-start latency.
    let paths = MatrixSdkPaths::prepare(&layout, &config)?;
    let client = tokio::time::timeout(
        Duration::from_secs(120),
        matrix_sdk::Client::builder()
            .homeserver_url(config.binding.homeserver.as_str())
            .sqlite_store_with_cache_path(paths.state(), paths.cache(), Some(PASSPHRASE))
            .handle_refresh_tokens()
            .build(),
    )
    .await??;
    let session = fixture_session()?;
    tokio::time::timeout(
        Duration::from_secs(120),
        client.restore_session(session.clone()),
    )
    .await??;
    assert_eq!(
        serde_json::to_value(client.matrix_auth().session())?,
        serde_json::to_value(&session)?,
    );
    client.event_cache().subscribe()?;
    // A fresh owner-only authentication file accompanies the real SDK stores.
    // The candidate must reopen it through production login_or_restore;
    // the deliberately invalid password cannot create a replacement login.
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut session_file = options.open(paths.session())?;
    session_file.write_all(&serde_json::to_vec(&session)?)?;
    session_file.sync_all()?;
    client
        .state_store()
        .set_custom_value(CUSTOM_KEY, CUSTOM_VALUE.to_vec())
        .await?;
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: MatrixRoomId::parse(ROOM)?,
            agent_user_id: MatrixUserId::parse(USER)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    let commit = store
        .commit_sync_batch(
            /*binding_revision*/ 1,
            /*generation*/ 1,
            /*expected_next_batch*/ None,
            "before-sdk-upgrade",
            &[inbox_event()?],
            /*updated_at_ms*/ 11,
        )
        .await?;
    assert_eq!((commit.accepted, commit.duplicates), (1, 0));
    store.enqueue_outbox(&outbox_draft()?).await?;
    let expected = stored_values(&client, &store).await?;
    fs::write(expected_path, serde_json::to_vec_pretty(&expected)?)?;
    Ok(())
}

async fn reopen_fixture(root: &Path) -> TestResult {
    let expected: Value = serde_json::from_slice(&fs::read(root.join("expected.json"))?)?;
    let (layout, config) = fixture_config(root)?;
    let (client, session) = MatrixSdkClient::login_or_restore(
        &layout,
        config,
        "a password that cannot log in to this nonexistent server",
        Some(PASSPHRASE),
        /*device_display_name*/ None,
    )
    .await?;
    assert_eq!(serde_json::to_value(session)?, expected["session"]);
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    assert_eq!(stored_values(client.client(), &store).await?, expected);
    assert!(client.client().event_cache().has_subscribed());
    // The SDK may rebuild its event cache. The authoritative Hepta cursor and
    // inbox must still accept a continuation and deduplicate the old event.
    let continuation = store
        .commit_sync_batch(
            /*binding_revision*/ 1,
            /*generation*/ 1,
            Some("before-sdk-upgrade"),
            "after-sdk-upgrade",
            &[inbox_event()?],
            /*updated_at_ms*/ 20,
        )
        .await?;
    assert_eq!((continuation.accepted, continuation.duplicates), (0, 1));
    assert_eq!(continuation.checkpoint.next_batch, "after-sdk-upgrade");
    Ok(())
}

#[tokio::test]
async fn encrypted_state_identity_session_and_queues_survive_restart() -> TestResult {
    let temp = tempfile::tempdir()?;
    prepare_fixture(temp.path()).await?;
    reopen_fixture(temp.path()).await
}

fn external_fixture_directory() -> TestResult<PathBuf> {
    let path = PathBuf::from(std::env::var("HEPTA_MATRIX_MIGRATION_FIXTURE")?);
    if !path.is_absolute() || !path.is_dir() {
        return Err("migration fixture must be an existing absolute directory".into());
    }
    Ok(path)
}

// The candidate runner must invoke these two phases explicitly in separate
// processes, binding the first phase to the original 0.18 Cargo.lock and the
// second phase to the 0.19 candidate. Ordinary tests only prove same-version
// restart; they are not evidence that an old store migrated.
#[tokio::test]
#[ignore = "requires the source-bound old-version fixture producer"]
async fn prepare_old_version_fixture() -> TestResult {
    prepare_fixture(&external_fixture_directory()?).await
}

#[tokio::test]
#[ignore = "requires the independently retained old-version fixture"]
async fn reopen_old_version_fixture() -> TestResult {
    reopen_fixture(&external_fixture_directory()?).await
}
