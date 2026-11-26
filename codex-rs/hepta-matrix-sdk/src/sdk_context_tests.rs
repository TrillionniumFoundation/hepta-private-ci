#![allow(clippy::expect_used)]

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use matrix_sdk::Client;
use matrix_sdk::SessionMeta;
use matrix_sdk::SessionTokens;
use matrix_sdk::authentication::matrix::MatrixSession;
use matrix_sdk::config::RequestConfig;
use matrix_sdk::config::SyncSettings;
use matrix_sdk::event_handler::Ctx;
use matrix_sdk::ruma::api::MatrixVersion;
use matrix_sdk::ruma::events::direct::DirectEvent;
use pretty_assertions::assert_eq;
use serde_json::json;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

#[tokio::test]
async fn maintained_map_preserves_typed_context_clones_and_handler_identity()
-> Result<(), Box<dyn std::error::Error>> {
    let server = MockServer::start().await;
    let batches = AtomicUsize::new(0);
    Mock::given(method("GET"))
        .and(path("/_matrix/client/v3/sync"))
        .respond_with(move |_request: &wiremock::Request| {
            let batch = batches.fetch_add(1, Ordering::Relaxed);
            ResponseTemplate::new(200).set_body_json(json!({
                "next_batch": format!("context-batch-{batch}"),
                "account_data": {"events": [{
                    "type": "m.direct",
                    "content": {"@peer:example.test": [format!("!context-{batch}:example.test")]}
                }]}
            }))
        })
        .expect(3)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/_matrix/client/v3/keys/upload"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "one_time_key_counts": {"signed_curve25519": 100}
        })))
        .mount(&server)
        .await;

    let client = Client::builder()
        .homeserver_url(server.uri())
        .server_versions([MatrixVersion::V1_16])
        .request_config(
            RequestConfig::new()
                .retry_limit(0)
                .timeout(Duration::from_secs(2)),
        )
        .build()
        .await?;
    let user_id = "@context:example.test".parse()?;
    client
        .restore_session(MatrixSession {
            meta: SessionMeta {
                user_id,
                device_id: "CONTEXT_TEST".into(),
            },
            tokens: SessionTokens {
                access_token: "synthetic-local-context-fixture".to_owned(),
                refresh_token: None,
            },
        })
        .await?;
    let observed = Arc::new(Mutex::new(Vec::<String>::new()));
    client.add_event_handler_context(observed.clone());
    client.add_event_handler_context("first".to_owned());
    let handle = client.add_event_handler(
        |_event: DirectEvent,
         Ctx(value): Ctx<String>,
         Ctx(observed): Ctx<Arc<Mutex<Vec<String>>>>,
         event_client: Client| async move {
            observed
                .lock()
                .expect("context fixture mutex")
                .push(format!(
                    "{}:{value}",
                    event_client.user_id().expect("restored identity")
                ));
        },
    );
    client.sync_once(SyncSettings::default()).await?;
    let same_client = client.clone();
    same_client.add_event_handler_context("second".to_owned());
    same_client.sync_once(SyncSettings::default()).await?;
    same_client.remove_event_handler(handle);
    // A different context type is absent; it must not invoke a handler with
    // another type's value or inherit the removed handler's identity.
    let unexpected_context = observed.clone();
    same_client.add_event_handler(move |_event: DirectEvent, Ctx(_): Ctx<u64>| {
        let unexpected_context = unexpected_context.clone();
        async move {
            unexpected_context
                .lock()
                .expect("context fixture mutex")
                .push("unexpected typed context".to_owned());
        }
    });
    same_client.sync_once(SyncSettings::default()).await?;
    assert_eq!(
        *observed.lock().expect("context fixture result"),
        [
            "@context:example.test:first",
            "@context:example.test:second"
        ]
    );
    server.verify().await;
    Ok(())
}
