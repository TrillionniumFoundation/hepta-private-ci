//! The public client transport is identical with and without daemon composition.
use super::*;
use codex_uds::UnixListener;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

async fn exchange(
    encode: impl FnOnce(AgentdResponse) -> Vec<u8> + Send + 'static,
) -> TestResult<Result<Option<AgentRunReceipt>, AgentdError>> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("client.sock");
    let mut listener = UnixListener::bind(&path).await?;
    let owner = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3")?;
    let client = AgentdClient::new(path, owner.clone(), 7)?;
    let server = tokio::spawn(async move {
        let stream = listener.accept().await?;
        let (reader, mut writer) = tokio::io::split(stream);
        let mut reader = BufReader::new(reader);
        let mut request = Vec::new();
        reader.read_until(b'\n', &mut request).await?;
        let request: AgentdRequest =
            serde_json::from_slice(&request).map_err(std::io::Error::other)?;
        let response = AgentdResponse {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: request.request_id,
            agent_id: owner,
            spawn_generation: request.spawn_generation,
            current_generation: request.spawn_generation,
            payload: AgentdPayload::RunStatus { run: None },
        };
        writer.write_all(&encode(response)).await
    });
    let result = client.run_status("absent-run".into()).await;
    server.await??;
    Ok(result)
}

fn frame(response: AgentdResponse) -> Vec<u8> {
    let mut bytes = serde_json::to_vec(&response).expect("wire response");
    bytes.push(b'\n');
    bytes
}

#[tokio::test]
async fn bounded_client_roundtrip_observes_owner_response() -> TestResult {
    assert!(exchange(frame).await??.is_none());
    Ok(())
}

#[tokio::test]
async fn client_rejects_every_response_identity_substitution() -> TestResult {
    for field in ["schema", "request", "agent", "generation"] {
        let response = exchange(move |mut response| {
            match field {
                "schema" => response.schema_version += 1,
                "request" => response.request_id += 1,
                "agent" => {
                    response.agent_id =
                        AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd4").expect("other owner")
                }
                "generation" => response.spawn_generation += 1,
                _ => unreachable!(),
            }
            frame(response)
        })
        .await?;
        assert!(matches!(response, Err(AgentdError::Protocol(_))), "{field}");
    }
    Ok(())
}

#[tokio::test]
async fn client_preserves_overload_and_bounded_frame_rejection() -> TestResult {
    let overloaded = exchange(|_| AGENTD_CONTROL_OVERLOAD_FRAME.to_vec()).await?;
    assert!(matches!(
        overloaded,
        Err(AgentdError::Overloaded {
            retry_after_ms: AGENTD_OVERLOAD_RETRY_AFTER_MS
        })
    ));
    for bytes in [
        Vec::new(),
        b"{}".to_vec(),
        vec![b'x'; MAX_CONTROL_FRAME_BYTES as usize + 1],
    ] {
        let result = exchange(move |_| bytes).await?;
        assert!(matches!(result, Err(AgentdError::Protocol(_))));
    }
    Ok(())
}
