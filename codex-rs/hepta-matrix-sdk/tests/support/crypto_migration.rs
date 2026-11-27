use std::error::Error;
use std::path::Path;

use matrix_sdk::SqliteCryptoStore;
use matrix_sdk::ruma::OwnedRoomId;
use matrix_sdk::ruma::device_id;
use matrix_sdk::ruma::events::room::message::RoomMessageEventContent;
use matrix_sdk::ruma::serde::Raw;
use matrix_sdk::ruma::user_id;
use matrix_sdk_crypto::Account;
use matrix_sdk_crypto::DeviceData;
use matrix_sdk_crypto::olm::EncryptionSettings;
use matrix_sdk_crypto::olm::SenderData;
use matrix_sdk_crypto::store::CryptoStore;
use matrix_sdk_crypto::store::types::Changes;
use matrix_sdk_crypto::store::types::PendingChanges;
use matrix_sdk_crypto::types::events::room::encrypted::EncryptedEvent;
use matrix_sdk_crypto::types::events::room::encrypted::ToDeviceEncryptedEventContent;
use matrix_sdk_crypto::vodozemac::olm::OlmMessage;
use matrix_sdk_crypto::vodozemac::olm::SessionConfig;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;
const OLM_MARKER: &str = "Olm plaintext encrypted by the original SDK";
const MEGOLM_MARKER: &str = "Megolm plaintext encrypted by the original SDK";

fn olm_message(content: Raw<ToDeviceEncryptedEventContent>) -> TestResult<OlmMessage> {
    match content.deserialize()? {
        ToDeviceEncryptedEventContent::OlmV1Curve25519AesSha2(content) => Ok(content.ciphertext),
        _ => Err("fixture requires the existing Olm v1 algorithm".into()),
    }
}

// Only the old-version producer creates sessions. The consumer must retrieve
// these exact persisted sessions and decrypt ciphertext produced before migration.
pub async fn prepare(path: &Path, passphrase: &str, room: &str) -> TestResult<Value> {
    let store = SqliteCryptoStore::open(path, Some(passphrase)).await?;
    let mut recipient = store
        .load_account()
        .await?
        .ok_or("missing old SDK account")?;
    let recipient_device = DeviceData::from_account(&recipient);
    let peer = Account::with_device_id(user_id!("@old-sender:example.test"), device_id!("OLDPEER"));
    let peer_device = DeviceData::from_account(&peer);
    recipient.generate_one_time_keys(/*count*/ 1);
    let one_time_key = *recipient
        .one_time_keys()
        .values()
        .next()
        .ok_or("missing one-time key")?;
    let peer_key = peer.identity_keys().curve25519;
    let mut outbound = peer.create_outbound_session_helper(
        SessionConfig::version_1(),
        recipient.identity_keys().curve25519,
        one_time_key,
        /*fallback_used*/ false,
        peer.device_keys(),
    )?;
    let handshake = olm_message(
        outbound
            .encrypt(
                &recipient_device,
                "m.dummy",
                json!({"marker": "handshake"}),
                /*message_id*/ None,
            )
            .await?,
    )?;
    let OlmMessage::PreKey(prekey) = handshake else {
        return Err("expected an initial Olm pre-key message".into());
    };
    let created = recipient.create_inbound_session(peer_key, recipient.device_keys(), &prekey)?;
    let initial: Value = serde_json::from_str(&created.plaintext)?;
    assert_eq!(initial["content"]["marker"], "handshake");
    let mut inbound = created.session;
    let reply = olm_message(
        inbound
            .encrypt(
                &peer_device,
                "m.dummy",
                json!({"marker": "reply"}),
                /*message_id*/ None,
            )
            .await?,
    )?;
    let reply_plaintext: Value = serde_json::from_str(&outbound.decrypt(&reply).await?)?;
    assert_eq!(reply_plaintext["content"]["marker"], "reply");
    let pending = olm_message(
        outbound
            .encrypt(
                &recipient_device,
                "m.dummy",
                json!({"marker": OLM_MARKER}),
                /*message_id*/ None,
            )
            .await?,
    )?;
    assert!(
        matches!(pending, OlmMessage::Normal(_)),
        "fixture must retain an established ratchet"
    );
    let room: OwnedRoomId = room.try_into()?;
    let (group_outbound, group_inbound) = recipient
        .create_group_session_pair(&room, EncryptionSettings::default(), SenderData::unknown())
        .await?;
    group_outbound.mark_as_shared();
    let group_result = group_outbound
        .encrypt(
            "m.room.message",
            &Raw::new(&RoomMessageEventContent::text_plain(MEGOLM_MARKER))?.cast(),
        )
        .await;
    let ciphertexts = json!({
        "olm_sender_key": peer_key.to_base64(),
        "olm_session_id": inbound.session_id(),
        "olm_message": pending,
        "megolm_session_id": group_inbound.session_id(),
        "megolm_event": {
            "sender": recipient.user_id(),
            "event_id": "$old-megolm-message",
            "origin_server_ts": 15,
            "room_id": room,
            "type": "m.room.encrypted",
            "content": group_result.content,
        },
    });
    store
        .save_pending_changes(PendingChanges {
            account: Some(recipient),
        })
        .await?;
    store
        .save_changes(Changes {
            sessions: vec![inbound],
            inbound_group_sessions: vec![group_inbound],
            ..Default::default()
        })
        .await?;
    Ok(ciphertexts)
}

pub async fn reopen(path: &Path, passphrase: &str, room: &str, ciphertexts: Value) -> TestResult {
    let store = SqliteCryptoStore::open(path, Some(passphrase)).await?;
    // load_account also initializes the backend's static-account cache. It must
    // find the migrated account; creating a new account would hide key loss.
    let _account = store
        .load_account()
        .await?
        .ok_or("missing migrated SDK account")?;
    let sender_key = ciphertexts["olm_sender_key"]
        .as_str()
        .ok_or("missing sender key")?;
    let session_id = ciphertexts["olm_session_id"]
        .as_str()
        .ok_or("missing Olm session ID")?;
    let mut sessions = store
        .get_sessions(sender_key)
        .await?
        .ok_or("missing migrated Olm sessions")?;
    let session = sessions
        .iter_mut()
        .find(|s| s.session_id() == session_id)
        .ok_or("old Olm session was not retained")?;
    let message: OlmMessage = serde_json::from_value(ciphertexts["olm_message"].clone())?;
    assert!(matches!(message, OlmMessage::Normal(_)));
    let plaintext: Value = serde_json::from_str(&session.decrypt(&message).await?)?;
    assert_eq!(plaintext["content"]["marker"], OLM_MARKER);
    assert_eq!(plaintext["sender"], "@old-sender:example.test");
    assert_eq!(plaintext["recipient"], "@migration:example.test");
    drop(sessions);
    let room: OwnedRoomId = room.try_into()?;
    let group_id = ciphertexts["megolm_session_id"]
        .as_str()
        .ok_or("missing Megolm session ID")?;
    let group = store
        .get_inbound_group_session(&room, group_id)
        .await?
        .ok_or("old Megolm session was not retained")?;
    assert_eq!(group.session_id(), group_id);
    let event: EncryptedEvent = serde_json::from_value(ciphertexts["megolm_event"].clone())?;
    let (plaintext, index) = group.decrypt(&event).await?;
    assert_eq!(index, 0);
    assert_eq!(plaintext["content"]["body"], MEGOLM_MARKER);
    assert_eq!(plaintext["room_id"], room.as_str());
    Ok(())
}
