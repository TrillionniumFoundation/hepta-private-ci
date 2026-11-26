//! Original client correlation and generation semantics, not exporter custody.
use super::*;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;

#[tokio::test]
async fn prepared_client_returns_runtime_generation_and_rejects_foreign_spawn() {
    let configuration = Digest32::of_bytes(b"prepared-client-config");
    let body = Digest32::of_bytes(b"prepared-client-body");
    let agent = codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
        .expect("agent");
    for spawn in [7, 8] {
        let directory = tempfile::tempdir().expect("transport fixture");
        let socket = directory.path().join("prepared.sock");
        let mut listener = codex_uds::UnixListener::bind(&socket)
            .await
            .expect("socket");
        let client = crate::AgentdClient::new(socket, agent.clone(), 7)
            .expect("original client")
            .with_peer_process(unsafe { libc::geteuid() }, std::process::id())
            .expect("actual non-Root transport peer");
        let agent = agent.clone();
        let serving = tokio::spawn(async move {
            let stream = listener.accept().await.expect("transport");
            let (reader, mut writer) = tokio::io::split(stream);
            let mut bytes = Vec::new();
            BufReader::new(reader)
                .read_until(b'\n', &mut bytes)
                .await
                .expect("request");
            let request: crate::AgentdRequest =
                serde_json::from_slice(&bytes).expect("original request");
            assert!(matches!(
                request.method,
                crate::AgentdMethod::PreparedGenerationV2 { generation: 2, .. }
            ));
            let response = crate::AgentdResponse {
                schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: request.request_id,
                agent_id: agent,
                spawn_generation: spawn,
                current_generation: 8,
                payload: crate::AgentdPayload::PreparedGenerationV2 {
                    generation: 2,
                    configuration_digest: configuration.to_string(),
                    body_digest: body.to_string(),
                    prepared_hex: None,
                },
            };
            let mut bytes = serde_json::to_vec(&response).expect("original response");
            bytes.push(b'\n');
            writer.write_all(&bytes).await.expect("whole response");
            writer.shutdown().await.expect("response retirement");
        });
        let result = client.prepared_generation_v2(2, configuration, body).await;
        serving.await.expect("actual producer retired");
        if spawn == 7 {
            let (runtime_generation, packet) = result.expect("correlated response");
            assert_eq!(runtime_generation, 8);
            assert!(packet.is_none());
        } else {
            assert!(
                result.is_err(),
                "foreign spawn was accepted as current runtime"
            );
        }
    }
}
