use super::*;

#[tokio::test]
async fn full_receipt_transport_preserves_bytes_and_rejects_another_native_request()
-> Result<(), Box<dyn std::error::Error>> {
    let record = "{\"original_output\":\"引号 \\\" 与原始换行\\n\"}";
    for response_request in ["assessment-1", "other-assessment"] {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("native-receipt.sock");
        let mut listener = codex_uds::UnixListener::bind(&path).await?;
        let agent = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3")?;
        let client = AgentdClient::new(path, agent.clone(), 7)?;
        let task = tokio::spawn(async move {
            let stream = listener.accept().await?;
            let (reader, mut writer) = tokio::io::split(stream);
            let mut bytes = Vec::new();
            BufReader::new(reader).read_until(b'\n', &mut bytes).await?;
            let request: AgentdRequest = serde_json::from_slice(&bytes)?;
            assert!(
                matches!(request.method, crate::AgentdMethod::NativeModelReceipt { request_id } if request_id == "assessment-1")
            );
            let response = AgentdResponse {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: request.request_id,
                agent_id: agent,
                spawn_generation: 7,
                current_generation: 8,
                payload: AgentdPayload::NativeModelReceipt {
                    request_id: response_request.into(),
                    native_record_json: Some(record.into()),
                },
            };
            let mut bytes = serde_json::to_vec(&response)?;
            bytes.push(b'\n');
            writer.write_all(&bytes).await?;
            Ok::<_, Box<dyn std::error::Error + Send + Sync>>(())
        });
        let result = client.native_model_receipt("assessment-1".into()).await;
        task.await?.map_err(|error| error.to_string())?;
        if response_request == "assessment-1" {
            assert_eq!(result?, (8, Some(record.into())));
        } else {
            assert!(result.is_err());
        }
    }
    // This tests transport correlation; only the real server kernel peer gate
    // and installed reader can establish the origin of a production receipt.
    Ok(())
}
