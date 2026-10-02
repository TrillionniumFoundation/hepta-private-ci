#![cfg(feature = "synapse-sdk-qualification")]

//! Isolated Linux SDK protocol qualification, separate from paired-host admission.
use matrix_sdk::Client;
use matrix_sdk::config::SyncSettings;
use matrix_sdk::ruma::OwnedRoomId;
use matrix_sdk::ruma::OwnedTransactionId;
use matrix_sdk::ruma::events::AnySyncMessageLikeEvent;
use matrix_sdk::ruma::events::AnySyncTimelineEvent;
use matrix_sdk::ruma::events::SyncMessageLikeEvent;
use matrix_sdk::ruma::events::room::message::MessageType;
use matrix_sdk::ruma::events::room::message::RoomMessageEventContent;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::time::Duration;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

async fn receive(client: &Client, room: &OwnedRoomId, body: &str) -> TestResult<String> {
    let result = tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            let sync = client
                .sync_once(SyncSettings::new().timeout(Duration::from_millis(100)))
                .await?;
            if let Some(joined) = sync.rooms.joined.get(room) {
                for event in &joined.timeline.events {
                    if let AnySyncTimelineEvent::MessageLike(AnySyncMessageLikeEvent::RoomMessage(
                        SyncMessageLikeEvent::Original(event),
                    )) = event.raw().deserialize()?
                        && let MessageType::Text(text) = event.content.msgtype
                        && text.body == body
                    {
                        return Ok::<_, Box<dyn std::error::Error>>(event.event_id.to_string());
                    }
                }
            }
        }
    })
    .await??;
    Ok(result)
}

#[tokio::test]
async fn encrypted_send_sync_and_sqlite_reopen_against_isolated_synapse() -> TestResult {
    let homeserver = std::env::var("HEPTA_SDK_SYNAPSE_URL")?;
    let url = url::Url::parse(&homeserver)?;
    assert_eq!(url.host_str(), Some("127.0.0.1"));
    assert_eq!(url.scheme(), "http");
    let alice_dir = tempfile::tempdir()?;
    let bob_dir = tempfile::tempdir()?;
    let alice = Client::builder()
        .homeserver_url(&homeserver)
        .sqlite_store(alice_dir.path(), /*passphrase*/ None)
        .build()
        .await?;
    let bob = Client::builder()
        .homeserver_url(&homeserver)
        .sqlite_store(bob_dir.path(), /*passphrase*/ None)
        .build()
        .await?;
    for (client, username) in [(&alice, "alice"), (&bob, "bob")] {
        let mut registration = matrix_sdk::ruma::api::client::account::register::v3::Request::new();
        registration.username = Some(username.into());
        registration.password = Some("isolated-fixture-password".into());
        registration.auth = Some(serde_json::from_value(json!({"type": "m.login.dummy"}))?);
        client.matrix_auth().register(registration).await?;
    }
    let bob_session = bob.matrix_auth().session().ok_or("missing Bob session")?;
    let room = alice
        .create_dm(bob.user_id().ok_or("missing Bob identity")?)
        .await?;
    let room_id = room.room_id().to_owned();
    bob.join_room_by_id(&room_id).await?;
    alice
        .sync_once(SyncSettings::new().timeout(Duration::from_millis(100)))
        .await?;
    bob.sync_once(SyncSettings::new().timeout(Duration::from_millis(100)))
        .await?;
    assert!(room.latest_encryption_state().await?.is_encrypted());
    let sent = room
        .send(RoomMessageEventContent::text_plain("before reopen"))
        .with_transaction_id(OwnedTransactionId::from("fixture-txn-1"))
        .await?;
    assert!(sent.encryption_info.is_some());
    let event_id = sent.response.event_id;
    assert_eq!(
        receive(&bob, &room_id, "before reopen").await?,
        event_id.as_str()
    );
    let raw_response = alice
        .send(
            matrix_sdk::ruma::api::client::room::get_room_event::v3::Request::new(
                room_id.clone(),
                event_id.clone(),
            ),
        )
        .await?;
    let raw: Value = serde_json::from_str(raw_response.event.json().get())?;
    assert_eq!(raw["type"], "m.room.encrypted");
    drop(bob);
    let reopened = Client::builder()
        .homeserver_url(&homeserver)
        .sqlite_store(bob_dir.path(), /*passphrase*/ None)
        .build()
        .await?;
    reopened.restore_session(bob_session).await?;
    let sent = room
        .send(RoomMessageEventContent::text_plain("after reopen"))
        .with_transaction_id(OwnedTransactionId::from("fixture-txn-2"))
        .await?;
    assert!(sent.encryption_info.is_some());
    assert_eq!(
        receive(&reopened, &room_id, "after reopen").await?,
        sent.response.event_id.as_str()
    );
    Ok(())
}
