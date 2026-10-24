use super::*;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_protocol::protocol::TokenUsage;

#[tokio::test]
async fn changed_body_is_rejected_before_a_request_artifact_is_written() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let evidence = Evidence::create(&directory.path().join("qualification"))?;
    let observer = ExactBodyObserver::new(evidence.clone(), Digest32::of_bytes(b"original"));
    assert!(observer.observe_encoded_body(b"changed").await.is_err());
    assert!(!evidence.directory().join("encoded-request.json").exists());
    Ok(())
}

#[tokio::test]
async fn exact_body_is_retained_once_and_repeated_callback_cannot_resend() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let evidence = Evidence::create(&directory.path().join("qualification"))?;
    let observer = ExactBodyObserver::new(evidence.clone(), Digest32::of_bytes(b"original"));
    observer
        .observe_encoded_body(b"original")
        .await
        .map_err(anyhow::Error::msg)?;
    assert!(observer.observe_encoded_body(b"original").await.is_err());
    assert_eq!(
        std::fs::read(evidence.directory().join("encoded-request.json"))?,
        b"original"
    );
    Ok(())
}

#[tokio::test]
async fn continuation_retains_encrypted_items_and_actual_reasoning_cache_and_rollout_usage()
-> Result<()> {
    let directory = tempfile::tempdir()?;
    let evidence = Evidence::create(&directory.path().join("qualification"))?;
    let binding = TurnBinding {
        run_id: StableId::new("run:fixture")?,
        turn_id: StableId::new("turn:fixture")?,
        generation: Generation::new(1)?,
        admission_digest: Digest32::of_bytes(b"admission"),
        deadline_unix_ms: u64::MAX,
    };
    let request = ModelRequest {
        request_id: StableId::new("request:fixture")?,
        payload: "".into(),
        context_digest: Digest32::of_bytes(b""),
        input_tokens: 0,
        maximum_provider_input_tokens: 32,
        maximum_output_tokens: 8,
    };
    let retained = Arc::new(Mutex::new(None));
    let mut owner = ContinuationEvidence {
        evidence: evidence.clone(),
        binding: binding.clone(),
        request: request.clone(),
        retained,
    };
    let item = serde_json::from_value(json!({"type":"reasoning", "id":"rs:fixture", "summary":[],
        "content":[{"type":"text","text":"provider-exposed content"}],
        "encrypted_content":"opaque-original-continuation"}))?;
    let receipt = owner
        .retain(
            &binding,
            &request,
            ResponsesContinuation {
                provider_response_id: "response:fixture".into(),
                server_model: Some("observed-model".into()),
                items: vec![item],
                usage: TokenUsage {
                    input_tokens: 12,
                    cached_input_tokens: 7,
                    cache_write_input_tokens: 2,
                    output_tokens: 4,
                    reasoning_output_tokens: 3,
                    total_tokens: 16,
                    codex_rollout_budget_units: Some(serde_json::Number::from(9)),
                },
                provider_rollout_budget_units: Some(serde_json::Number::from(9)),
                end_turn: Some(true),
            },
        )
        .await?;
    let bytes = std::fs::read(evidence.directory().join("provider-continuation.json"))?;
    assert_eq!(receipt, Digest32::of_bytes(&bytes));
    let persisted: Value = serde_json::from_slice(&bytes)?;
    assert_eq!(
        persisted["items"][0]["encrypted_content"],
        "opaque-original-continuation"
    );
    assert_eq!(
        persisted["items"][0]["content"][0]["text"],
        "provider-exposed content"
    );
    assert_eq!(persisted["usage"]["input_tokens"], 12);
    assert_eq!(persisted["usage"]["cached_input_tokens"], 7);
    assert_eq!(persisted["usage"]["cache_write_input_tokens"], 2);
    assert_eq!(persisted["usage"]["reasoning_output_tokens"], 3);
    assert_eq!(persisted["provider_rollout_budget_units"], 9);
    Ok(())
}

#[test]
fn original_qualification_directory_cannot_be_reused_for_another_provider_send() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("qualification");
    let first = Evidence::create(&path)?;
    first.record("admission.json", &json!({"request":"original"}))?;
    assert!(Evidence::create(&path).is_err());
    assert!(
        first
            .record("admission.json", &json!({"request":"different"}))
            .is_err()
    );
    Ok(())
}
