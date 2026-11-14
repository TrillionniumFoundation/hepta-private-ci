use std::error::Error;
use std::sync::Arc;

use matrix_sdk::Client;
use matrix_sdk::SessionMeta;
use matrix_sdk::SessionTokens;
use matrix_sdk::authentication::matrix::MatrixSession;
use matrix_sdk::config::SyncSettings;
use matrix_sdk::event_handler::Ctx;
use matrix_sdk::ruma::api::MatrixVersion;
use matrix_sdk::ruma::events::room::message::OriginalSyncRoomMessageEvent;
use pretty_assertions::assert_eq;
use serde_json::json;
use tokio::sync::Mutex;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

#[derive(Clone)]
struct Label(String);

#[derive(Clone)]
struct Observed(Arc<Mutex<Vec<(String, String)>>>);

#[tokio::test]
async fn handler_context_keeps_types_replacements_and_per_event_clones()
-> Result<(), Box<dyn Error>> {
    let server = MockServer::start().await;
    let messages = ["first", "second"]
        .into_iter()
        .enumerate()
        .map(|(index, body)| {
            json!({
                "type": "m.room.message",
                "sender": "@owner:example.test",
                "event_id": format!("$message-{index}:example.test"),
                "origin_server_ts": 1_000 + index,
                "content": { "msgtype": "m.text", "body": body },
            })
        })
        .collect::<Vec<_>>();
    let response = json!({
        "next_batch": "after-two-events",
        "rooms": { "join": { "!allowed:example.test": {
            "timeline": { "events": messages, "limited": false, "prev_batch": "start" },
            "state": { "events": [{
                "type": "m.room.member", "state_key": "@agent:example.test",
                "sender": "@agent:example.test", "event_id": "$member:example.test",
                "origin_server_ts": 1, "content": { "membership": "join" },
            }] },
            "account_data": { "events": [] },
            "ephemeral": { "events": [] },
            "unread_notifications": {},
        }}},
        "to_device": { "events": [] },
        "account_data": { "events": [] },
        "device_lists": { "changed": [], "left": [] },
        "device_one_time_keys_count": {},
    });
    Mock::given(method("GET"))
        .and(path("/_matrix/client/v3/sync"))
        .respond_with(ResponseTemplate::new(200).set_body_json(response))
        .expect(1)
        .mount(&server)
        .await;
    let client = Client::builder()
        .homeserver_url(server.uri())
        .server_versions([MatrixVersion::V1_12])
        .build()
        .await?;
    client
        .restore_session(MatrixSession {
            meta: SessionMeta {
                user_id: "@agent:example.test".try_into()?,
                device_id: "CONTEXTDEVICE".into(),
            },
            tokens: SessionTokens {
                access_token: "context-fixture-access-token".into(),
                refresh_token: None,
            },
        })
        .await?;
    let observed = Observed(Arc::new(Mutex::new(Vec::new())));
    client.add_event_handler_context(Label("original".into()));
    client.add_event_handler_context(observed.clone());
    client.add_event_handler_context(Label("replacement".into()));
    client.add_event_handler(
        |event: OriginalSyncRoomMessageEvent,
         Ctx(mut label): Ctx<Label>,
         Ctx(observed): Ctx<Observed>| async move {
            observed
                .0
                .lock()
                .await
                .push((event.content.body().to_owned(), label.0.clone()));
            label.0.push_str("-local-to-one-handler");
        },
    );
    client.sync_once(SyncSettings::default()).await?;
    let mut actual = observed.0.lock().await.clone();
    actual.sort();
    assert_eq!(
        actual,
        vec![
            ("first".into(), "replacement".into()),
            ("second".into(), "replacement".into()),
        ]
    );
    Ok(())
}
