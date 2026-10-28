use super::test_transport::FirstPartyTestTransport;
use super::transport::ModelApiTransport;
use codex_http_client::HttpClientBuilder;
use codex_http_client::HttpTransport;
use codex_http_client::Request;
use codex_http_client::ReqwestTransport;
use codex_http_client::TransportError;
use futures::StreamExt;
use http::HeaderValue;
use http::Method;
use http::StatusCode;
use http::header::AUTHORIZATION;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::net::TcpListener;
use std::sync::Arc;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

const LOGICAL_RESPONSES: &str = "https://api.openai.com/v1/responses";

async fn owned_fixture() -> anyhow::Result<(MockServer, Arc<FirstPartyTestTransport>)> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let fixture = Arc::new(FirstPartyTestTransport::from_loopback_listener(
        listener.try_clone()?,
    )?);
    let server = MockServer::builder().listener(listener).start().await;
    assert_eq!(server.address(), &fixture.address());
    Ok((server, fixture))
}

fn request(url: &str) -> Request {
    let mut request = Request::new(Method::POST, url.to_string()).with_json(&json!({
        "input": [{"role": "user", "internal_chat_message_metadata_passthrough": {
            "content_kinds": ["user.text"], "timestamp": "fixture-timestamp"
        }}]
    }));
    request.headers.insert(
        AUTHORIZATION,
        HeaderValue::from_static("Bearer fixture-only-fake-credential"),
    );
    request
}

#[tokio::test]
async fn fixture_forwards_unchanged_wire_body_and_headers_to_its_owned_listener()
-> anyhow::Result<()> {
    let (server, fixture) = owned_fixture().await?;
    Mock::given(method("POST"))
        .and(path("/v1/responses"))
        .respond_with(ResponseTemplate::new(200).set_body_string("fixture-response"))
        .expect(2)
        .mount(&server)
        .await;
    let transport = ModelApiTransport::for_fixture(fixture, LOGICAL_RESPONSES)?;
    let outbound = request(LOGICAL_RESPONSES);
    let expected_body = outbound
        .prepare_body_for_send()
        .map_err(anyhow::Error::msg)?
        .body_bytes();
    let response = transport.execute(outbound.clone()).await?;
    assert_eq!(response.body.as_ref(), b"fixture-response");
    let mut response = transport.stream(outbound).await?;
    let mut streamed = Vec::new();
    while let Some(bytes) = response.bytes.next().await {
        streamed.extend_from_slice(&bytes?);
    }
    assert_eq!(streamed.as_slice(), b"fixture-response");
    let received = server.received_requests().await.expect("recorded requests");
    assert_eq!(received.len(), 2);
    for received in received {
        assert_eq!(received.body.as_slice(), expected_body.as_ref());
        assert_eq!(
            received
                .headers
                .get(AUTHORIZATION)
                .expect("fake auth header"),
            "Bearer fixture-only-fake-credential"
        );
        assert_eq!(received.url.path(), "/v1/responses");
    }
    Ok(())
}

#[tokio::test]
async fn fixture_rejects_other_origins_paths_queries_and_late_destination_changes()
-> anyhow::Result<()> {
    let (server, fixture) = owned_fixture().await?;
    let transport = ModelApiTransport::for_fixture(Arc::clone(&fixture), LOGICAL_RESPONSES)?;
    for forbidden in [
        "http://api.openai.com/v1/responses",
        "https://api.openai.com.evil.example/v1/responses",
        "https://api.openai.com/v1/models",
        "https://api.openai.com/v1/responses/../models",
        "https://api.openai.com/v1/responses?forward=other",
        "https://api.openai.com/v1/responses#fragment",
    ] {
        assert!(ModelApiTransport::for_fixture(Arc::clone(&fixture), forbidden).is_err());
        // Covers a request altered after the transport was constructed, such
        // as a destination change made while applying authentication.
        assert!(matches!(
            transport.execute(request(forbidden)).await,
            Err(TransportError::Build(_))
        ));
    }
    assert!(
        server
            .received_requests()
            .await
            .expect("recorded requests")
            .is_empty()
    );
    Ok(())
}

#[tokio::test]
async fn fixture_does_not_follow_redirects_or_forward_credentials_to_another_server()
-> anyhow::Result<()> {
    let (server, fixture) = owned_fixture().await?;
    let other = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(200))
        .mount(&other)
        .await;
    Mock::given(method("POST"))
        .and(path("/v1/responses"))
        .respond_with(
            ResponseTemplate::new(307)
                .insert_header("Location", format!("{}/credential-trap", other.uri())),
        )
        .expect(1)
        .mount(&server)
        .await;
    let transport = ModelApiTransport::for_fixture(fixture, LOGICAL_RESPONSES)?;
    assert!(matches!(
        transport.execute(request(LOGICAL_RESPONSES)).await,
        Err(TransportError::Http {
            status: StatusCode::TEMPORARY_REDIRECT,
            ..
        })
    ));
    assert!(
        other
            .received_requests()
            .await
            .expect("recorded requests")
            .is_empty()
    );
    Ok(())
}

#[tokio::test]
async fn fixture_instances_route_independently_and_production_transport_is_unchanged()
-> anyhow::Result<()> {
    let (first, first_fixture) = owned_fixture().await?;
    let (second, second_fixture) = owned_fixture().await?;
    for (server, body) in [(&first, "first"), (&second, "second")] {
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(200).set_body_string(body))
            .mount(server)
            .await;
    }
    let first_transport = ModelApiTransport::for_fixture(first_fixture, LOGICAL_RESPONSES)?;
    let second_transport = ModelApiTransport::for_fixture(second_fixture, LOGICAL_RESPONSES)?;
    let (first_response, second_response) = tokio::join!(
        first_transport.execute(request(LOGICAL_RESPONSES)),
        second_transport.execute(request(LOGICAL_RESPONSES)),
    );
    assert_eq!(first_response?.body.as_ref(), b"first");
    assert_eq!(second_response?.body.as_ref(), b"second");

    let production = ModelApiTransport::production(ReqwestTransport::from_http_client(
        HttpClientBuilder::new()
            .without_redirects()
            .build_direct()?,
    ));
    let response = production
        .execute(request(&format!("{}/ordinary", first.uri())))
        .await?;
    assert_eq!(response.body.as_ref(), b"first");
    let requests = first.received_requests().await.expect("recorded requests");
    assert_eq!(requests.len(), 2);
    assert_eq!(requests[1].url.path(), "/ordinary");
    assert_eq!(
        second
            .received_requests()
            .await
            .expect("recorded requests")
            .len(),
        1
    );
    Ok(())
}

#[test]
fn fixture_requires_an_owned_loopback_listener() -> anyhow::Result<()> {
    let listener = TcpListener::bind("0.0.0.0:0")?;
    assert!(FirstPartyTestTransport::from_loopback_listener(listener).is_err());
    Ok(())
}
