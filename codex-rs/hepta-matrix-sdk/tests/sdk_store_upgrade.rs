use std::fs;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MATRIX_BINDING_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::MatrixDeviceId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixHomeserverUrl;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_sdk::MatrixSdkClient;
use codex_hepta_matrix_sdk::MatrixSdkPaths;
use codex_hepta_matrix_sdk::MatrixSession;
use codex_hepta_matrix_sdk::MatrixSidecarConfig;
use codex_hepta_matrix_store::InboxDraft;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaFleetRoot;
use matrix_sdk::Client;
use matrix_sdk::ruma::RoomId;
use matrix_sdk::ruma::events::room::encrypted::OriginalSyncRoomEncryptedEvent;
use matrix_sdk::ruma::serde::Raw;
use matrix_sdk::store::StateStoreDataKey;
use matrix_sdk::store::StateStoreDataValue;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use tempfile::TempDir;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[derive(Deserialize)]
struct LegacyFixture {
    homeserver: String,
    passphrase: String,
    sync_token: String,
    room_id: String,
    identity_keys: IdentityKeys,
    device: Value,
    encrypted_event: Value,
    plaintext_event: Value,
}

#[derive(Debug, Deserialize, Eq, PartialEq)]
struct IdentityKeys {
    ed25519: String,
    curve25519: String,
}

#[tokio::test]
async fn sdk_018_store_upgrades_without_losing_keys_session_or_owner_cursor() -> TestResult {
    let started = std::time::Instant::now();
    let fixture: LegacyFixture =
        serde_json::from_str(include_str!("fixtures/sdk-0.18/expected.json"))?;
    let expected_session: MatrixSession =
        serde_json::from_str(include_str!("fixtures/sdk-0.18/session.json"))?;
    let temp = TempDir::new()?;
    let fleet_root = temp.path().join("fleet");
    fs::create_dir(&fleet_root)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = HeptaFleetRoot::parse(fleet_root.canonicalize()?)?
        .layout()
        .agent(&agent_id);
    let owner = MatrixUserId::parse("@owner:example.invalid")?;
    let room_id = MatrixRoomId::parse(&fixture.room_id)?;
    let config = MatrixSidecarConfig {
        binding: MatrixBindingV1 {
            schema_version: MATRIX_BINDING_SCHEMA_VERSION,
            agent_id,
            revision: 1,
            homeserver: MatrixHomeserverUrl::parse(&fixture.homeserver)?,
            expected_mxid: MatrixUserId::parse(expected_session.meta.user_id.as_str())?,
            expected_device_id: MatrixDeviceId::parse(expected_session.meta.device_id.as_str())?,
            allowed_rooms: vec![room_id.clone()],
            allowed_senders: vec![owner.clone()],
            require_explicit_mention: true,
        },
        matrix_generation: 1,
        sync_timeline_limit: 32,
        sync_timeout: Duration::from_secs(1),
    };
    let paths = MatrixSdkPaths::prepare(&layout, &config)?;
    fs::write(
        paths.state().join("matrix-sdk-state.sqlite3"),
        include_bytes!("fixtures/sdk-0.18/matrix-sdk-state.sqlite3"),
    )?;
    fs::write(
        paths.state().join("matrix-sdk-crypto.sqlite3"),
        include_bytes!("fixtures/sdk-0.18/matrix-sdk-crypto.sqlite3"),
    )?;
    fs::write(
        paths.cache().join("matrix-sdk-event-cache.sqlite3"),
        include_bytes!("fixtures/sdk-0.18/matrix-sdk-event-cache.sqlite3"),
    )?;
    fs::write(
        paths.cache().join("matrix-sdk-media.sqlite3"),
        include_bytes!("fixtures/sdk-0.18/matrix-sdk-media.sqlite3"),
    )?;
    fs::write(
        paths.session(),
        include_bytes!("fixtures/sdk-0.18/session.json"),
    )?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(paths.session(), fs::Permissions::from_mode(0o600))?;
    }

    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: config.binding.expected_mxid.clone(),
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    store
        .commit_sync_batch(
            /*binding_revision*/ 1,
            /*generation*/ 1,
            /*expected_next_batch*/ None,
            "hepta-owner-before-sdk-upgrade",
            &[InboxDraft {
                event_id: MatrixEventId::parse("$before-sdk-upgrade")?,
                room_id,
                sender: owner,
                event_type: "m.room.message".to_string(),
                payload: serde_json::to_vec(&json!({
                    "msgtype": "m.text",
                    "body": "Retain the admitted message during the SDK upgrade"
                }))?,
                binding_revision: 1,
                generation: 1,
                origin_server_ts_ms: 10,
                received_at_ms: 11,
            }],
            /*updated_at_ms*/ 20,
        )
        .await?;
    let snapshot = store.snapshot(/*now_ms*/ 20, /*limit*/ 10).await?;
    let checkpoint = store
        .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
        .await?;

    // Open the bytes written by 0.18 before the Hepta adapter deliberately
    // clears the SDK cursor. This exercises the real upstream migrations.
    eprintln!(
        "matrix_upgrade phase=upstream-open start_ms={}",
        started.elapsed().as_millis()
    );
    let migrated = Client::builder()
        .homeserver_url(&fixture.homeserver)
        .sqlite_store_with_cache_path(paths.state(), paths.cache(), Some(&fixture.passphrase))
        .build()
        .await?;
    assert_eq!(
        migrated
            .state_store()
            .get_kv_data(StateStoreDataKey::SyncToken)
            .await?
            .and_then(StateStoreDataValue::into_sync_token),
        Some(fixture.sync_token.clone())
    );
    drop(migrated);
    eprintln!(
        "matrix_upgrade phase=upstream-open-complete elapsed_ms={}",
        started.elapsed().as_millis()
    );

    // Verify both the initial restoration and a subsequent reopen of the
    // upgraded stores. No test-only TLS provider initialization is performed.
    for reopen in 0..2 {
        eprintln!(
            "matrix_upgrade phase=adapter-open reopen={reopen} start_ms={}",
            started.elapsed().as_millis()
        );
        let (upgraded, restored_session) = MatrixSdkClient::login_or_restore(
            &layout,
            config.clone(),
            "unused-password-local-session-must-restore",
            Some(&fixture.passphrase),
            /*device_display_name*/ None,
        )
        .await?;
        eprintln!(
            "matrix_upgrade phase=adapter-open-complete reopen={reopen} elapsed_ms={}",
            started.elapsed().as_millis()
        );
        assert_eq!(restored_session, expected_session);
        assert_restored_client(upgraded.client(), &fixture, &expected_session).await?;
        eprintln!(
            "matrix_upgrade phase=restored-keys-verified reopen={reopen} elapsed_ms={}",
            started.elapsed().as_millis()
        );
        assert_eq!(
            serde_json::from_slice::<MatrixSession>(&fs::read(paths.session())?)?,
            expected_session
        );
        assert_eq!(store.snapshot(/*now_ms*/ 20, /*limit*/ 10).await?, snapshot);
        assert_eq!(
            store
                .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
                .await?,
            checkpoint
        );
    }
    store.close().await;
    Ok(())
}

async fn assert_restored_client(
    client: &Client,
    fixture: &LegacyFixture,
    expected_session: &MatrixSession,
) -> TestResult {
    assert_eq!(
        client.matrix_auth().session(),
        Some(expected_session.clone())
    );
    let account_identity = IdentityKeys {
        ed25519: client
            .encryption()
            .ed25519_key()
            .await
            .ok_or("account Ed25519 key is missing")?,
        curve25519: client
            .encryption()
            .curve25519_key()
            .await
            .ok_or("account Curve25519 key is missing")?
            .to_base64(),
    };
    assert_eq!(account_identity, fixture.identity_keys);
    let device = client
        .encryption()
        .get_own_device()
        .await?
        .ok_or("the existing device must survive the upgrade")?;
    assert_eq!(
        IdentityKeys {
            ed25519: device
                .ed25519_key()
                .ok_or("device Ed25519 key is missing")?
                .to_base64(),
            curve25519: device
                .curve25519_key()
                .ok_or("device Curve25519 key is missing")?
                .to_base64(),
        },
        fixture.identity_keys
    );
    assert_eq!(serde_json::to_value(&*device)?, fixture.device);
    assert!(
        client
            .state_store()
            .get_kv_data(StateStoreDataKey::SyncToken)
            .await?
            .is_none()
    );

    let room = client
        .get_room(RoomId::parse(&fixture.room_id)?.as_ref())
        .ok_or("the existing joined room must survive the upgrade")?;
    let encrypted: Raw<OriginalSyncRoomEncryptedEvent> =
        Raw::from_json_string(serde_json::to_string(&fixture.encrypted_event)?)?;
    let decrypted = room.decrypt_event(&encrypted, /*push_ctx*/ None).await?;
    assert!(decrypted.encryption_info().is_some());
    let plaintext: Value = serde_json::from_str(decrypted.raw().json().get())?;
    assert_eq!(
        json!({
            "room_id": fixture.room_id,
            "type": plaintext["type"],
            "content": plaintext["content"]
        }),
        fixture.plaintext_event
    );
    Ok(())
}
