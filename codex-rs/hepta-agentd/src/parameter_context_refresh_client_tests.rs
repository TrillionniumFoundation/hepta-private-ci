use super::*;

#[derive(Clone, Copy)]
enum ReplyCase {
    Exact,
    ForeignSpawn,
    ForeignRound,
    ForeignSource,
    ForeignPin,
}

#[tokio::test]
async fn refresh_client_keeps_runtime_generation_and_rejects_foreign_context_acknowledgements() {
    for case in [
        ReplyCase::Exact,
        ReplyCase::ForeignSpawn,
        ReplyCase::ForeignRound,
        ReplyCase::ForeignSource,
        ReplyCase::ForeignPin,
    ] {
        let directory = tempfile::tempdir().expect("original socket fixture");
        let socket = directory.path().join("context-refresh-client.sock");
        let mut listener = codex_uds::UnixListener::bind(&socket)
            .await
            .expect("listen");
        let agent = codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
            .expect("Agent identity");
        let client = AgentdClient::new(socket, agent.clone(), 7).expect("original client");
        let round = super::super::input_context_tests::fixture_round();
        let expected_round = crate::client::encode_hex(&round.canonical_bytes().expect("Round"));
        let source = std::path::PathBuf::from("/root/original-round-context");
        let pin = digest("original whole protected context");
        let task = tokio::spawn(async move {
            let stream = listener.accept().await.expect("actual socket peer");
            let (reader, mut writer) = tokio::io::split(stream);
            let mut frame = Vec::new();
            BufReader::new(reader)
                .read_until(b'\n', &mut frame)
                .await
                .expect("original bounded request");
            let request: AgentdRequest = serde_json::from_slice(&frame).expect("request");
            let AgentdMethod::RefreshParameterInputContextV2 {
                mut round_hex,
                mut context_source,
                mut context_digest,
            } = request.method
            else {
                panic!("wrong original context operation")
            };
            assert_eq!(round_hex, expected_round);
            assert_eq!(context_source, "/root/original-round-context");
            assert_eq!(context_digest, pin.to_string());
            let mut spawn_generation = 7;
            match case {
                ReplyCase::Exact => {}
                ReplyCase::ForeignSpawn => spawn_generation = 8,
                ReplyCase::ForeignRound => round_hex = "00".into(),
                ReplyCase::ForeignSource => context_source = "/root/other-context".into(),
                ReplyCase::ForeignPin => context_digest = digest("other context").to_string(),
            }
            let response = AgentdResponse {
                schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: request.request_id,
                agent_id: agent,
                spawn_generation,
                current_generation: 8,
                payload: AgentdPayload::ParameterInputContextRefreshedV2 {
                    round_hex,
                    context_source,
                    context_digest,
                },
            };
            let mut bytes = serde_json::to_vec(&response).expect("original response");
            bytes.push(b'\n');
            writer.write_all(&bytes).await.expect("response");
        });
        let result = client
            .refresh_parameter_input_context_v2(round, source, pin)
            .await;
        task.await.expect("fixture server closes");
        match case {
            ReplyCase::Exact => assert_eq!(result.expect("whole context acknowledgement"), 8),
            _ => assert!(result.is_err()),
        }
    }
}
