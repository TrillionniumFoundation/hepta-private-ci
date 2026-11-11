use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

async fn budget_client(
    server: &MockServer,
    callbacks: &Arc<AtomicUsize>,
) -> anyhow::Result<RmcpClient> {
    let observed = Arc::clone(callbacks);
    initialize_client(
        server,
        Box::new(move |_, _| {
            observed.fetch_add(/*val*/ 1, Ordering::SeqCst);
            async {
                Ok(ElicitationResponse {
                    action: ElicitationAction::Accept,
                    content: None,
                    meta: None,
                })
            }
            .boxed()
        }),
    )
    .await
}

fn input_batch(body: &Value, count: usize, state: &str) -> ResponseTemplate {
    let requests: serde_json::Map<String, Value> = (0..count)
        .map(|i| (format!("confirmation-{i}"), elicitation_request("form")))
        .collect();
    result_response(
        body,
        json!({
            "resultType": "input_required", "inputRequests": requests, "requestState": state,
        }),
    )
}

#[tokio::test]
async fn modern_mrtr_reserves_whole_batches_across_rounds_for_tools_and_resources()
-> anyhow::Result<()> {
    for resource in [false, true] {
        for (batches, succeeds, expected_callbacks) in [
            (vec![64], true, 64),
            (vec![65], false, 0),
            (vec![32, 32, 1], false, 64),
        ] {
            let server = MockServer::start().await;
            Mock::given(method("POST"))
                .and(path("/mcp"))
                .respond_with(move |request: &Request| {
                    let body: Value = request.body_json().unwrap();
                    if body["method"] == "server/discover" {
                        return discover_response(&body);
                    }
                    let round = body
                        .pointer("/params/requestState")
                        .and_then(Value::as_str)
                        .unwrap_or("0")
                        .parse::<usize>()
                        .unwrap();
                    if let Some(count) = batches.get(round) {
                        input_batch(&body, *count, &(round + 1).to_string())
                    } else if resource {
                        result_response(&body, json!({"resultType": "complete", "contents": []}))
                    } else {
                        result_response(&body, json!({"resultType": "complete", "content": []}))
                    }
                })
                .mount(&server)
                .await;
            let callbacks = Arc::new(AtomicUsize::new(0));
            let client = budget_client(&server, &callbacks).await?;
            let result = if resource {
                client
                    .read_resource(
                        ReadResourceRequestParams::new("memo://budget"),
                        Some(Duration::from_secs(5)),
                    )
                    .await
                    .map(|_| ())
            } else {
                client
                    .call_tool(
                        "budget".into(),
                        /*arguments*/ None,
                        /*meta*/ None,
                        Some(Duration::from_secs(5)),
                    )
                    .await
                    .map(|_| ())
            };
            assert_eq!(result.is_ok(), succeeds, "{result:?}");
            assert_eq!(callbacks.load(Ordering::SeqCst), expected_callbacks);
            client.shutdown().await;
        }
    }
    Ok(())
}

#[tokio::test]
async fn concurrent_modern_calls_have_independent_input_budgets() -> anyhow::Result<()> {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/mcp"))
        .respond_with(move |request: &Request| {
            let body: Value = request.body_json().unwrap();
            if body["method"] == "server/discover" {
                return discover_response(&body);
            }
            if body.pointer("/params/requestState").is_some() {
                return result_response(&body, json!({"resultType": "complete", "content": []}));
            }
            input_batch(&body, /*count*/ 64, "complete")
        })
        .mount(&server)
        .await;
    let callbacks = Arc::new(AtomicUsize::new(0));
    let client = budget_client(&server, &callbacks).await?;
    let (first, second) = tokio::join!(
        client.call_tool(
            "first".into(),
            /*arguments*/ None,
            /*meta*/ None,
            Some(Duration::from_secs(5))
        ),
        client.call_tool(
            "second".into(),
            /*arguments*/ None,
            /*meta*/ None,
            Some(Duration::from_secs(5))
        ),
    );
    first?;
    second?;
    assert_eq!(callbacks.load(Ordering::SeqCst), 128);
    client.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn modern_stateless_404_does_not_restart_input_work() -> anyhow::Result<()> {
    let server = MockServer::start().await;
    let attempts = Arc::new(AtomicUsize::new(0));
    let observed_attempts = Arc::clone(&attempts);
    let discoveries = Arc::new(AtomicUsize::new(0));
    let observed_discoveries = Arc::clone(&discoveries);
    Mock::given(method("GET"))
        .and(path("/mcp"))
        .respond_with(ResponseTemplate::new(405))
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/mcp"))
        .respond_with(move |request: &Request| {
            let body: Value = request.body_json().unwrap();
            if body["method"] == "server/discover" {
                let session = observed_discoveries.fetch_add(/*val*/ 1, Ordering::SeqCst);
                return discover_response(&body)
                    .insert_header("mcp-session-id", format!("session-{session}"));
            }
            // Modern HTTP ignores even an offered legacy session header.
            assert_eq!(request.headers.get("mcp-session-id"), None);
            let attempt = observed_attempts.fetch_add(/*val*/ 1, Ordering::SeqCst);
            if attempt == 1 {
                assert_eq!(
                    body.pointer("/params/requestState"),
                    Some(&json!("continue"))
                );
                return ResponseTemplate::new(404);
            }
            assert_eq!(body.pointer("/params/requestState"), None);
            let count = if attempt == 0 { 32 } else { 33 };
            input_batch(&body, count, "continue")
        })
        .mount(&server)
        .await;
    let callbacks = Arc::new(AtomicUsize::new(0));
    let client = budget_client(&server, &callbacks).await?;
    let result = client
        .call_tool(
            "recovery-budget".into(),
            /*arguments*/ None,
            /*meta*/ None,
            Some(Duration::from_secs(5)),
        )
        .await;
    let error = result.expect_err("stateless 404 must terminate the logical call");
    assert!(format!("{error:#}").contains("HTTP 404"), "{error:#}");
    assert_eq!(discoveries.load(Ordering::SeqCst), 1);
    assert_eq!(attempts.load(Ordering::SeqCst), 2);
    assert_eq!(callbacks.load(Ordering::SeqCst), 32);
    client.shutdown().await;
    Ok(())
}
