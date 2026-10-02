//! Qualify the maintained type map through SDK context extraction, not a mock map.
use matrix_sdk::Client;
use matrix_sdk::SessionMeta;
use matrix_sdk::SessionTokens;
use matrix_sdk::authentication::matrix::MatrixSession;
use matrix_sdk::config::SyncSettings;
use matrix_sdk::event_handler::Ctx;
use matrix_sdk::ruma::api::MatrixVersion;
use matrix_sdk::ruma::device_id;
use matrix_sdk::ruma::events::room::message::OriginalSyncRoomMessageEvent;
use matrix_sdk::ruma::user_id;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

type Observations = Arc<Mutex<Vec<(String, usize)>>>;

#[derive(Clone)]
struct Label(String);

#[tokio::test]
async fn context_replacement_type_isolation_and_clone_extraction()
-> Result<(), Box<dyn std::error::Error>> {
    let server = MockServer::start().await;
    Mock::given(method("GET")).and(path("/_matrix/client/v3/sync"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "next_batch": "fixture-token", "rooms": {"join": {"!room:fixture.invalid": {
                "state": {"events": [{"type":"m.room.member","state_key":"@alice:fixture.invalid","sender":"@alice:fixture.invalid","event_id":"$join","origin_server_ts":1,"content":{"membership":"join"}}]},
                "timeline": {"limited":false,"events":[{"type":"m.room.message","sender":"@alice:fixture.invalid","event_id":"$message","origin_server_ts":2,"content":{"msgtype":"m.text","body":"fixture"}}]}
            }}}
        }))).mount(&server).await;
    let client = Client::builder()
        .homeserver_url(server.uri())
        .server_versions([MatrixVersion::V1_11])
        .build()
        .await?;
    client
        .restore_session(MatrixSession {
            meta: SessionMeta {
                user_id: user_id!("@alice:fixture.invalid").to_owned(),
                device_id: device_id!("ALICE").to_owned(),
            },
            tokens: SessionTokens {
                access_token: "isolated-token".into(),
                refresh_token: None,
            },
        })
        .await?;
    let observed = Arc::new(Mutex::new(Vec::<(String, usize)>::new()));
    client.add_event_handler_context(Label("old".into()));
    client.add_event_handler_context(Label("replacement".into()));
    client.add_event_handler_context(7_usize);
    client.add_event_handler_context(observed.clone());
    client.add_event_handler(
        |_: OriginalSyncRoomMessageEvent,
         label: Ctx<Label>,
         count: Ctx<usize>,
         observed: Ctx<Observations>| async move {
            observed
                .lock()
                .expect("fixture mutex")
                .push((label.0.0, count.0));
        },
    );
    client
        .sync_once(SyncSettings::new().timeout(Duration::from_millis(100)))
        .await?;
    assert_eq!(
        *observed.lock().map_err(|_| "fixture mutex")?,
        vec![("replacement".into(), 7)]
    );
    Ok(())
}
