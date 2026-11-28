use super::super::DEFAULT_TIMEOUT;
use super::CatalogGate;
use anyhow::Result;
use codex_http_client::HttpClientBuilder;
use http::StatusCode;
use pretty_assertions::assert_eq;
use tokio::time::timeout;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::header;
use wiremock::matchers::method;
use wiremock::matchers::path;
use wiremock::matchers::query_param;

#[tokio::test]
async fn held_catalog_preserves_requests_and_allows_other_routes() -> Result<()> {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/backend-api/ps/plugins/list"))
        .and(query_param("scope", "GLOBAL"))
        .and(query_param("limit", "200"))
        .and(header("authorization", "Bearer gate-test"))
        .and(header("chatgpt-account-id", "gate-account"))
        .respond_with(
            ResponseTemplate::new(StatusCode::OK.as_u16()).set_body_string("catalog-body"),
        )
        .expect(/*r*/ 1)
        .mount(&server)
        .await;
    Mock::given(method("GET"))
        .and(path("/backend-api/ps/plugins/installed"))
        .and(query_param("scope", "WORKSPACE"))
        .respond_with(ResponseTemplate::new(StatusCode::OK.as_u16()).set_body_string("other-body"))
        .expect(/*r*/ 1)
        .mount(&server)
        .await;
    let gate = CatalogGate::start(&server).await?;
    let mut held = gate.hold_next_global_catalog();
    let client = HttpClientBuilder::new().build_direct()?;
    let url = format!(
        "{}/backend-api/ps/plugins/list?scope=GLOBAL&limit=200",
        gate.uri()
    );
    let catalog_client = client.clone();
    let pending = tokio::spawn(async move {
        let response = catalog_client
            .get(url)
            .header("authorization", "Bearer gate-test")
            .header("chatgpt-account-id", "gate-account")
            .send()
            .await?;
        Ok::<_, anyhow::Error>((response.status(), response.text().await?))
    });
    timeout(DEFAULT_TIMEOUT, held.wait_until_held()).await??;
    let unrelated = timeout(
        DEFAULT_TIMEOUT,
        client
            .get(format!(
                "{}/backend-api/ps/plugins/installed?scope=WORKSPACE",
                gate.uri()
            ))
            .send(),
    )
    .await??;
    assert_eq!(unrelated.status(), StatusCode::OK);
    assert_eq!(unrelated.text().await?, "other-body");
    assert!(
        !pending.is_finished(),
        "catalog body escaped before release"
    );
    held.release()?;
    assert_eq!(
        timeout(DEFAULT_TIMEOUT, pending).await???,
        (StatusCode::OK, "catalog-body".to_string())
    );
    gate.shutdown().await?;
    server.verify().await;
    Ok(())
}

#[tokio::test]
async fn dropped_catalog_release_does_not_return_a_success_body() -> Result<()> {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/backend-api/ps/plugins/list"))
        .and(query_param("scope", "GLOBAL"))
        .respond_with(
            ResponseTemplate::new(StatusCode::OK.as_u16()).set_body_string("must-stay-held"),
        )
        .expect(/*r*/ 1)
        .mount(&server)
        .await;
    let gate = CatalogGate::start(&server).await?;
    let mut held = gate.hold_next_global_catalog();
    let client = HttpClientBuilder::new().build_direct()?;
    let url = format!("{}/backend-api/ps/plugins/list?scope=GLOBAL", gate.uri());
    let pending = tokio::spawn(async move {
        let response = client.get(url).send().await?;
        Ok::<_, anyhow::Error>((response.status(), response.text().await?))
    });
    timeout(DEFAULT_TIMEOUT, held.wait_until_held()).await??;
    drop(held);
    assert_eq!(
        timeout(DEFAULT_TIMEOUT, pending).await???,
        (
            StatusCode::BAD_GATEWAY,
            "held catalog response was dropped without release".to_string()
        )
    );
    gate.shutdown().await?;
    server.verify().await;
    Ok(())
}
