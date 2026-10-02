//! Generates disposable historical state with the actual pinned SDK 0.18 engine.
//! No network, live accounts, supplied databases or advisory-triggering API is used.
use matrix_sdk_crypto::{EncryptionSettings, GossipRequest, OlmMachine, SecretInfo};
use matrix_sdk_crypto::store::{CryptoStore, types::Changes};
use matrix_sdk_sqlite::SqliteCryptoStore;
use ruma::{device_id, room_id, user_id, TransactionId};
use ruma::events::{room::message::RoomMessageEventContent, secret::request::SecretName};
use serde_json::json;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let output = std::path::PathBuf::from(std::env::args_os().nth(1).ok_or("fresh fixture path required")?);
    std::fs::create_dir(&output)?;
    let crypto = output.join("crypto");
    let user = user_id!("@alice:legacy-fixture.invalid");
    let device = device_id!("LEGACYALICE");
    let room = room_id!("!legacy:fixture.invalid");
    let store = SqliteCryptoStore::open(&crypto, Some("isolated-fixture-passphrase")).await?;
    let machine = OlmMachine::with_store(user, device, store.clone(), None).await?;
    machine.bootstrap_cross_signing(false).await?;
    machine.share_room_key(room, std::iter::empty(), EncryptionSettings { sharing_strategy: matrix_sdk_crypto::CollectStrategy::AllDevices, ..EncryptionSettings::default() }).await?;
    let encrypted = machine.encrypt_room_event(room, RoomMessageEventContent::text_plain("real SDK 0.18 migration payload")).await?;
    let request_id = TransactionId::new();
    store.save_changes(Changes {
        key_requests: vec![GossipRequest {
            request_recipient: user.to_owned(), request_id: request_id.clone(),
            info: SecretInfo::SecretRequest(SecretName::RecoveryKey), sent_out: false,
        }], ..Changes::default()
    }).await?;
    let sliding_key = format!("sliding_sync_store::room-list::{user}::instance");
    store.set_custom_value(&sliding_key, b"old-sliding-sync-position".to_vec()).await?;
    store.set_custom_value("hepta-fixture-unrelated", b"preserve-other-metadata".to_vec()).await?;
    let db = rusqlite::Connection::open(crypto.join("matrix-sdk-crypto.sqlite3"))?;
    let schema: Vec<u8> = db.query_row("SELECT value FROM kv WHERE key='version'", [], |row| row.get(0))?;
    assert_eq!(schema, vec![17]);
    let private_keys = machine.export_cross_signing_keys().await?.ok_or("private cross-signing keys missing")?;
    let private_bytes = serde_json::to_vec(&json!([
        private_keys.master_key.as_ref().ok_or("master key missing")?,
        private_keys.self_signing_key.as_ref().ok_or("self signing key missing")?,
        private_keys.user_signing_key.as_ref().ok_or("user signing key missing")?,
    ]))?;
    let private_digest = blake3::hash(&private_bytes).to_hex().to_string();
    let manifest = json!({
        "sdk_version": matrix_sdk_crypto::VERSION, "schema": schema,
        "user_id": user, "device_id": device, "room_id": room,
        "identity_keys": machine.identity_keys(), "gossip_request_id": request_id,
        "cross_signing": machine.cross_signing_status().await, "cross_signing_digest": private_digest,
        "event": {"type":"m.room.encrypted", "event_id":"$legacy-fixture-event", "sender":user, "origin_server_ts":1, "content":encrypted.content},
        "expected_body":"real SDK 0.18 migration payload", "sliding_sync_key": sliding_key
    });
    std::fs::write(output.join("manifest.json"), serde_json::to_vec_pretty(&manifest)?)?;
    Ok(())
}
