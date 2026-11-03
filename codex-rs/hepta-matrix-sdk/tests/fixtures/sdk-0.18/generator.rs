//! Reusable port of the original Matrix SDK 0.18.0 fixture generator.
//! See README.md for the original generator SHA256 and source provenance.
//! Usage: generate-old-fixture generate OUTPUT SOURCE_COMMIT
//!        generate-old-fixture verify OUTPUT
//! This program performs no HTTP requests.
use std::error::Error;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use matrix_sdk::SessionMeta;
use matrix_sdk::SessionTokens;
use matrix_sdk::authentication::matrix::MatrixSession;
use matrix_sdk_base::RoomInfo;
use matrix_sdk_base::RoomState;
use matrix_sdk_base::store::StateChanges;
use matrix_sdk_base::store::StateStore;
use matrix_sdk_base::store::StateStoreDataKey;
use matrix_sdk_base::store::StateStoreDataValue;
use matrix_sdk_crypto::DecryptionSettings;
use matrix_sdk_crypto::LocalTrust;
use matrix_sdk_crypto::OlmMachine;
use matrix_sdk_crypto::TrustRequirement;
use matrix_sdk_crypto::olm::InboundGroupSession;
use matrix_sdk_crypto::olm::SenderData;
use matrix_sdk_crypto::store::CryptoStore;
use matrix_sdk_crypto::types::EventEncryptionAlgorithm;
use matrix_sdk_sqlite::SqliteCryptoStore;
use matrix_sdk_sqlite::SqliteEventCacheStore;
use matrix_sdk_sqlite::SqliteMediaStore;
use matrix_sdk_sqlite::SqliteStateStore;
use ruma::device_id;
use ruma::room_id;
use ruma::user_id;
use serde_json::Value;
use serde_json::json;

type Result<T> = std::result::Result<T, Box<dyn Error>>;

const PASS: &str = "matrix-sdk-018-fixture-passphrase";
const TOKEN: &str = "hepta-matrix-018-fixture-sync-token";

fn require(condition: bool, message: &'static str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(message.into())
    }
}

async fn generate(root: &Path, source_commit: &str) -> Result<()> {
    require(
        matrix_sdk_crypto::VERSION == "0.18.0",
        "wrong crypto SDK linked",
    )?;
    require(
        !root.join("state").exists(),
        "refusing to replace an existing fixture",
    )?;
    fs::create_dir_all(root)?;
    let user = user_id!("@fixture-matrix-018:example.invalid");
    let device = device_id!("HEPTA018FIXTURE");
    let room = room_id!("!fixture-room-018:example.invalid");

    let crypto = SqliteCryptoStore::open(root.join("state"), Some(PASS)).await?;
    let state = SqliteStateStore::open(root.join("state"), Some(PASS)).await?;
    let _event_cache = SqliteEventCacheStore::open(root.join("cache"), Some(PASS)).await?;
    let _media_cache = SqliteMediaStore::open(root.join("cache"), Some(PASS)).await?;
    let machine = OlmMachine::with_store(user, device, Arc::new(crypto.clone()), None).await?;
    let keys = machine.identity_keys();
    let own_device = machine
        .get_device(user, device, None)
        .await?
        .ok_or("missing own device")?;
    own_device.set_local_trust(LocalTrust::Verified).await?;
    let device_data = CryptoStore::get_device(&crypto, user, device)
        .await?
        .ok_or("device was not persisted")?;
    require(
        device_data.local_trust_state() == LocalTrust::Verified,
        "wrong device trust",
    )?;

    let mut group =
        vodozemac::megolm::GroupSession::new(vodozemac::megolm::SessionConfig::version_1());
    let incoming = InboundGroupSession::new(
        keys.curve25519,
        keys.ed25519,
        room,
        &group.session_key(),
        SenderData::unknown(),
        None,
        EventEncryptionAlgorithm::MegolmV1AesSha2,
        None,
        false,
    )?;
    let imported = machine
        .store()
        .import_room_keys(vec![incoming.export().await], None, |_, _| {})
        .await?;
    require(
        imported.imported_count == 1 && imported.total_count == 1,
        "Megolm import failed",
    )?;
    let room_keys = machine.store().export_room_keys(|_| true).await?;
    require(room_keys.len() == 1, "unexpected Megolm export count")?;
    let plaintext = json!({
        "room_id": room,
        "type": "m.room.message",
        "content": {"msgtype": "m.text", "body": "Old Matrix SDK 0.18 Megolm fixture"}
    });
    let encrypted_event = json!({
        "event_id": "$fixture-megolm-018:example.invalid",
        "origin_server_ts": 1700000000000_u64,
        "sender": user,
        "type": "m.room.encrypted",
        "content": {
            "algorithm": "m.megolm.v1.aes-sha2",
            "ciphertext": group.encrypt(serde_json::to_vec(&plaintext)?).to_base64(),
            "sender_key": keys.curve25519.to_base64(),
            "device_id": device,
            "session_id": group.session_id()
        }
    });

    let mut changes = StateChanges::new(TOKEN.to_owned());
    changes.add_room(RoomInfo::new(room, RoomState::Joined));
    state.save_changes(&changes).await?;

    let session = MatrixSession {
        meta: SessionMeta {
            user_id: user.to_owned(),
            device_id: device.to_owned(),
        },
        tokens: SessionTokens {
            access_token: "fixture-access-token-not-valid".to_owned(),
            refresh_token: None,
        },
    };
    let session_bytes = serde_json::to_vec_pretty(&session)?;
    let session_again: MatrixSession = serde_json::from_slice(&session_bytes)?;
    require(
        session == session_again,
        "old MatrixSession serde roundtrip failed",
    )?;
    fs::write(root.join("session.json"), session_bytes)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root.join("session.json"), fs::Permissions::from_mode(0o600))?;
    }

    let expected = json!({
        "sdk_version": "0.18.0",
        "old_repo_commit": source_commit,
        "generator_rust_toolchain": "1.95.0",
        "sqlite_dependency_note": "Actual old Hepta matrix-sdk-sqlite 0.18.0 vendor with its preexisting rusqlite 0.39 manifest patch",
        "synthetic_test_data": true,
        "user_id": user,
        "device_id": device,
        "homeserver": "https://matrix-fixture.example.invalid",
        "passphrase": PASS,
        "sync_token": TOKEN,
        "room_id": room,
        "room_state": "Joined",
        "identity_keys": {"ed25519": keys.ed25519.to_base64(), "curve25519": keys.curve25519.to_base64()},
        "device": serde_json::to_value(&device_data)?,
        "local_trust": "Verified",
        "exported_room_keys": room_keys,
        "encrypted_event": encrypted_event,
        "plaintext_event": plaintext,
        "scope": {
            "cache": "Real old SDK schemas initialized without cache rows",
            "owner_database": "Not created or modified by this generator",
            "network": "No HTTP requests or real credentials",
            "cross_signing_or_backup_keys": "Not populated",
            "olm_peer_sessions": "Not populated"
        }
    });
    fs::write(
        root.join("expected.json"),
        serde_json::to_vec_pretty(&expected)?,
    )?;
    println!(
        "GENERATE PASS: account, verified device, 1 Megolm key, encrypted message, Joined room, sync token, old MatrixSession serde; cache schemas only"
    );
    Ok(())
}

async fn verify(root: &Path) -> Result<()> {
    let expected: Value = serde_json::from_slice(&fs::read(root.join("expected.json"))?)?;
    let session: MatrixSession = serde_json::from_slice(&fs::read(root.join("session.json"))?)?;
    let user = user_id!("@fixture-matrix-018:example.invalid");
    let device = device_id!("HEPTA018FIXTURE");
    let room = room_id!("!fixture-room-018:example.invalid");
    require(
        session.meta.user_id == user && session.meta.device_id == device,
        "session identity mismatch",
    )?;
    let crypto = SqliteCryptoStore::open(root.join("state"), Some(PASS)).await?;
    let state = SqliteStateStore::open(root.join("state"), Some(PASS)).await?;
    let machine = OlmMachine::with_store(user, device, Arc::new(crypto.clone()), None).await?;
    let keys = machine.identity_keys();
    require(
        expected["identity_keys"]["ed25519"] == keys.ed25519.to_base64(),
        "ed25519 changed after reopen",
    )?;
    require(
        expected["identity_keys"]["curve25519"] == keys.curve25519.to_base64(),
        "curve25519 changed after reopen",
    )?;
    let device_data = CryptoStore::get_device(&crypto, user, device)
        .await?
        .ok_or("missing persisted device")?;
    require(
        serde_json::to_value(device_data)? == expected["device"],
        "device or trust changed after reopen",
    )?;
    let room_keys = machine.store().export_room_keys(|_| true).await?;
    require(
        serde_json::to_value(room_keys)? == expected["exported_room_keys"],
        "Megolm export changed after reopen",
    )?;
    require(
        matches!(state.get_kv_data(StateStoreDataKey::SyncToken).await?, Some(StateStoreDataValue::SyncToken(t)) if t == TOKEN),
        "sync token missing after reopen",
    )?;
    let rooms = state.get_room_infos(&Default::default()).await?;
    require(
        rooms
            .iter()
            .any(|info| info.room_id() == room && info.state() == RoomState::Joined),
        "Joined room missing after reopen",
    )?;
    let raw = serde_json::from_value(expected["encrypted_event"].clone())?;
    let decrypted = machine
        .decrypt_room_event(
            &raw,
            room,
            &DecryptionSettings {
                sender_device_trust_requirement: TrustRequirement::Untrusted,
            },
        )
        .await?;
    let clear: Value = serde_json::from_str(decrypted.event.json().get())?;
    require(
        clear["type"] == expected["plaintext_event"]["type"]
            && clear["content"] == expected["plaintext_event"]["content"],
        "old SDK Megolm decryption mismatch",
    )?;
    drop(machine);
    drop(crypto);
    drop(state);
    // Let async pool connection closures complete before the runtime exits.
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    println!(
        "REOPEN PASS: original identity keys, full DeviceData/trust, full Megolm export, sync token, Joined room, session serde, real old SDK message decryption"
    );
    Ok(())
}

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let command = args.next().ok_or("expected generate or verify command")?;
    let root = PathBuf::from(args.next().ok_or("expected output directory")?);
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    match command.as_str() {
        "generate" => {
            let source_commit = args.next().ok_or("expected old source commit")?;
            require(args.next().is_none(), "unexpected extra argument")?;
            runtime.block_on(generate(&root, &source_commit))
        }
        "verify" => {
            require(args.next().is_none(), "unexpected extra argument")?;
            runtime.block_on(verify(&root))
        }
        _ => Err("expected generate or verify command".into()),
    }
}
