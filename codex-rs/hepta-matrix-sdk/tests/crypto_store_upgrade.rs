#![cfg(feature = "crypto-migration-qualification")]
//! Opens state emitted by the separately pinned real 0.18 SDK fixture producer.
use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MATRIX_BINDING_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::MatrixDeviceId;
use codex_hepta_matrix_protocol::MatrixHomeserverUrl;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_sdk::MatrixSdkPaths;
use codex_hepta_matrix_sdk::MatrixSidecarConfig;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_paths::HeptaFleetRoot;
use matrix_sdk::ruma::OwnedDeviceId;
use matrix_sdk::ruma::OwnedRoomId;
use matrix_sdk::ruma::OwnedUserId;
use matrix_sdk::ruma::events::secret::request::SecretName;
use matrix_sdk_crypto::DecryptionSettings;
use matrix_sdk_crypto::OlmMachineBuilder;
use matrix_sdk_crypto::SecretInfo;
use matrix_sdk_crypto::TrustRequirement;
use matrix_sdk_crypto::store::CryptoStore;
use matrix_sdk_sqlite::SqliteCryptoStore;
use pretty_assertions::assert_eq;
use serde_json::Value;

#[tokio::test]
async fn real_018_crypto_state_migrates_without_rotating_keys_or_hepta_cursor()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = std::path::PathBuf::from(
        std::env::var_os("HEPTA_LEGACY_CRYPTO_FIXTURE")
            .ok_or("source-generated legacy fixture required")?,
    );
    let manifest: Value = serde_json::from_slice(&std::fs::read(fixture.join("manifest.json"))?)?;
    assert_eq!(manifest["sdk_version"], "0.18.0");
    assert_eq!(manifest["schema"], serde_json::json!([17]));
    let original_crypto = fixture.join("crypto");
    let original_database = original_crypto.join("matrix-sdk-crypto.sqlite3");
    let schema: Vec<u8> = rusqlite::Connection::open(&original_database)?.query_row(
        "SELECT value FROM kv WHERE key='version'",
        [],
        |row| row.get(0),
    )?;
    assert_eq!(schema, vec![17]);
    let user = OwnedUserId::try_from(manifest["user_id"].as_str().ok_or("user")?)?;
    let device = OwnedDeviceId::from(manifest["device_id"].as_str().ok_or("device")?);
    let room = OwnedRoomId::try_from(manifest["room_id"].as_str().ok_or("room")?)?;
    let event = matrix_sdk::ruma::serde::Raw::from_json(serde_json::value::to_raw_value(
        &manifest["event"],
    )?);
    let temp = tempfile::tempdir()?;
    let layout = HeptaFleetRoot::parse(temp.path().canonicalize()?)?
        .layout()
        .agent(&AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?);
    let old_root = layout.matrix_root().join("matrix-sdk-0.18");
    let old_state = old_root.join("state");
    std::fs::create_dir_all(&old_state)?;
    for entry in std::fs::read_dir(&original_crypto)? {
        let entry = entry?;
        assert!(entry.file_type()?.is_file());
        std::fs::copy(entry.path(), old_state.join(entry.file_name()))?;
    }
    let session_bytes = serde_json::to_vec(&serde_json::json!({
        "user_id": user,
        "device_id": device,
        "access_token": "isolated-legacy-session-token",
        "refresh_token": "isolated-legacy-refresh-token",
    }))?;
    std::fs::write(old_root.join("session.json"), &session_bytes)?;
    let config = MatrixSidecarConfig {
        binding: MatrixBindingV1 {
            schema_version: MATRIX_BINDING_SCHEMA_VERSION,
            agent_id: layout.agent_id().clone(),
            revision: 1,
            homeserver: MatrixHomeserverUrl::parse("https://legacy-fixture.invalid")?,
            expected_mxid: MatrixUserId::parse(user.as_str())?,
            expected_device_id: MatrixDeviceId::parse(device.as_str())?,
            allowed_rooms: vec![MatrixRoomId::parse(room.as_str())?],
            allowed_senders: vec![MatrixUserId::parse(user.as_str())?],
            require_explicit_mention: true,
        },
        matrix_generation: 1,
        sync_timeline_limit: 32,
        sync_timeout: std::time::Duration::from_secs(1),
    };
    let paths = MatrixSdkPaths::prepare(&layout, &config)?;
    let crypto = paths.state();
    let database = crypto.join("matrix-sdk-crypto.sqlite3");
    let owner = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let before = owner
        .commit_sync_batch(
            /*binding_revision*/ 1,
            /*generation*/ 1,
            /*expected_next_batch*/ None,
            "authoritative-hepta-sync-cursor",
            &[],
            /*updated_at_ms*/ 10,
        )
        .await?
        .checkpoint;
    for _ in 0..2 {
        let store = SqliteCryptoStore::open(
            crypto,
            /*passphrase*/ Some("isolated-fixture-passphrase"),
        )
        .await?;
        let machine = OlmMachineBuilder::new(&user, &device)
            .with_crypto_store(store.clone())
            .build()
            .await?;
        assert_eq!(
            serde_json::to_value(machine.identity_keys())?,
            manifest["identity_keys"]
        );
        assert_eq!(
            serde_json::to_value(machine.cross_signing_status().await)?,
            manifest["cross_signing"]
        );
        let private_keys = machine
            .export_cross_signing_keys()
            .await?
            .ok_or("private keys lost")?;
        let private_bytes = serde_json::to_vec(&serde_json::json!([
            private_keys.master_key.as_ref().ok_or("master key lost")?,
            private_keys
                .self_signing_key
                .as_ref()
                .ok_or("self signing key lost")?,
            private_keys
                .user_signing_key
                .as_ref()
                .ok_or("user signing key lost")?,
        ]))?;
        assert_eq!(
            blake3::hash(&private_bytes).to_hex().as_str(),
            manifest["cross_signing_digest"]
                .as_str()
                .ok_or("key digest")?
        );
        let decrypted = machine
            .decrypt_room_event(
                &event,
                &room,
                &DecryptionSettings {
                    sender_device_trust_requirement: TrustRequirement::Untrusted,
                },
            )
            .await?;
        let plaintext: Value = serde_json::from_str(decrypted.event.json().get())?;
        assert_eq!(plaintext["content"]["body"], manifest["expected_body"]);
        let request = store
            .get_secret_request_by_info(&SecretInfo::SecretRequest(SecretName::RecoveryKey))
            .await?
            .ok_or("pending gossip lost")?;
        assert_eq!(
            request.request_id.as_str(),
            manifest["gossip_request_id"].as_str().ok_or("request")?
        );
        assert!(!request.sent_out);
        assert!(
            store
                .get_custom_value(manifest["sliding_sync_key"].as_str().ok_or("sliding key")?)
                .await?
                .is_none()
        );
        assert_eq!(
            store.get_custom_value("hepta-fixture-unrelated").await?,
            Some(b"preserve-other-metadata".to_vec())
        );
        assert_eq!(
            owner
                .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
                .await?,
            Some(before.clone())
        );
        assert_eq!(std::fs::read(paths.session())?, session_bytes);
        store.close().await?;
        drop(machine);
        drop(store);
        let db = rusqlite::Connection::open(&database)?;
        let version: Vec<u8> =
            db.query_row("SELECT value FROM kv WHERE key='version'", [], |row| {
                row.get(0)
            })?;
        assert_eq!(version, vec![19]);
        assert_eq!(
            db.query_row("PRAGMA integrity_check", [], |row| row.get::<_, String>(0))?,
            "ok"
        );
    }
    owner.close().await;
    drop(owner);
    let reopened_owner = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    assert_eq!(
        reopened_owner
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?,
        Some(before)
    );
    reopened_owner.close().await;
    Ok(())
}
