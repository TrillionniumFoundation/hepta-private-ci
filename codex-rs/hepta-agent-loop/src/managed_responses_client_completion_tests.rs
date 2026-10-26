//! No listener, provider send, installed credential, or synthetic watch setter.
use super::*;
use crate::managed_responses::ManagedResponsesAttempt;
use crate::managed_responses::ManagedResponsesClient;
use crate::managed_responses::error_tests::fixture::request;
use codex_api::AuthProvider;
use codex_api::Provider;
use codex_api::ResponsesClient;
use codex_api::ResponsesOptions;
use codex_api::RetryConfig;
use codex_http_client::HttpClientBuilder;
use codex_http_client::ReqwestTransport;
use tokio_util::sync::CancellationToken;

struct NoSendAuth;

impl AuthProvider for NoSendAuth {
    fn add_auth_headers(&self, _headers: &mut http::HeaderMap) {
        panic!("pre-transport rejection must never request authentication");
    }
}

fn offline_client() -> Result<ManagedResponsesClient> {
    let provider = Provider {
        name: "no-send completion fixture".into(),
        base_url: "http://127.0.0.1:1".into(),
        query_params: None,
        headers: http::HeaderMap::new(),
        retry: RetryConfig {
            max_attempts: 1,
            base_delay: Duration::from_millis(1),
            retry_429: false,
            retry_5xx: false,
            retry_transport: false,
        },
        stream_idle_timeout: Duration::from_secs(1),
    };
    let endpoint = provider.url_for_path("responses");
    let http = HttpClientBuilder::new()
        .without_request_logging()
        .without_redirects()
        .build_direct()
        .map_err(|_| Error::Contract("no-send HTTP client construction"))?;
    Ok(ManagedResponsesClient {
        client: ResponsesClient::new(
            ReqwestTransport::from_http_client(http),
            provider,
            Arc::new(NoSendAuth),
        ),
        endpoint,
        terminal_completion: tokio::sync::watch::channel(false).0,
    })
}

#[tokio::test]
async fn client_getter_tracks_original_supervisor_after_error_or_caller_abort() {
    for abort_caller in [false, true] {
        let client = offline_client().expect("no-send client");
        // Exercise the public getter, not a constructed completion receiver.
        let mut completion = client.terminal_completion();
        let (policy_tx, policy_rx) = oneshot::channel();
        let started = Arc::new(Notify::new());
        let proceed = Arc::new(Notify::new());
        let (observer, encoded_rx) = observer(None, /*fail*/ false);
        let lease = Lease {
            terminal: policy_tx,
            gates: Some((started.clone(), proceed.clone())),
            fail: true,
        };
        let dispatch = RequestDispatchMetadata::new();
        let observed_dispatch = dispatch.clone();
        let caller = tokio::spawn(async move {
            let (binding, request, api_request) = request();
            let (events, _received) = tokio::sync::mpsc::channel(4);
            client
                .stream_admitted(
                    ManagedResponsesAttempt {
                        binding: &binding,
                        request: &request,
                        // Deliberately invalid before any auth or transport use.
                        expected_model: "",
                        api_request,
                        options: ResponsesOptions {
                            encoded_body_observer: Some(observer),
                            ..Default::default()
                        },
                        dispatch,
                        lease: Box::new(lease),
                        maximum_elapsed: Duration::from_secs(2),
                        terminal_timeout: Duration::from_secs(2),
                        bridge_limits: crate::ResponsesBridgeLimits {
                            maximum_items: 4,
                            maximum_retained_bytes: 4096,
                            maximum_visible_bytes: 256,
                        },
                    },
                    &mut ContinuationOwner,
                    events,
                    &CancellationToken::new(),
                )
                .await
        });
        timeout(Duration::from_secs(2), started.notified())
            .await
            .expect("original policy write started");
        let encoded = timeout(Duration::from_secs(2), encoded_rx)
            .await
            .expect("encoded write progresses while policy pending")
            .expect("original encoded terminal");
        assert!(matches!(
            encoded,
            EncodedRequestTerminal::Abandoned { reason_code }
                if reason_code == "native_response_unresolved"
        ));
        assert!(!observed_dispatch.transport_invoked());
        assert!(!caller.is_finished());
        assert!(
            timeout(Duration::from_millis(20), completion.wait())
                .await
                .is_err()
        );
        if abort_caller {
            caller.abort();
            assert!(caller.await.expect_err("caller cancelled").is_cancelled());
        } else {
            proceed.notify_one();
            assert!(matches!(
                timeout(Duration::from_secs(2), caller)
                    .await
                    .expect("caller deadline")
                    .expect("caller joined"),
                Err(Error::Owner(_))
            ));
        }
        // Cancellation releases no gate and does not manufacture settlement.
        if abort_caller {
            assert!(
                timeout(Duration::from_millis(20), completion.wait())
                    .await
                    .is_err()
            );
            proceed.notify_one();
        }
        let policy = timeout(Duration::from_secs(2), policy_rx)
            .await
            .expect("detached original policy continues")
            .expect("original policy terminal");
        assert!(matches!(
            policy,
            ModelProviderTerminal::NotDispatched { reason_code }
                if reason_code == "native_response_unresolved"
        ));
        timeout(Duration::from_secs(2), completion.wait())
            .await
            .expect("settlement deadline")
            .expect("both futures returned despite failed persistence");
        assert!(!observed_dispatch.transport_invoked());
    }
}

#[tokio::test]
async fn unstarted_client_getter_never_reports_settlement() {
    let client = offline_client().expect("no-send client");
    let mut completion = client.terminal_completion();
    assert!(
        timeout(Duration::from_millis(20), completion.wait())
            .await
            .is_err()
    );
    drop(client);
    assert!(matches!(completion.wait().await, Err(Error::Owner(_))));
}
