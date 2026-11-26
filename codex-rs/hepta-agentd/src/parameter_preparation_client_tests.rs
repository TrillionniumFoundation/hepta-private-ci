#[derive(Clone, Copy)]
enum PreparedReplyCase {
    Exact,
    ForeignSpawn,
    ForeignRound,
    ForeignHead,
    ForeignParameter,
    ForeignModelGeneration,
    RelativeSource,
    PartialAdmission,
}

#[tokio::test]
async fn prepared_client_preserves_runtime_and_parameter_identity_and_rejects_foreign_whole_facts()
{
    for case in [
        PreparedReplyCase::Exact,
        PreparedReplyCase::ForeignSpawn,
        PreparedReplyCase::ForeignRound,
        PreparedReplyCase::ForeignHead,
        PreparedReplyCase::ForeignParameter,
        PreparedReplyCase::ForeignModelGeneration,
        PreparedReplyCase::RelativeSource,
        PreparedReplyCase::PartialAdmission,
    ] {
        let fixture = clock_fixture(|| Ok(50));
        let input = input(&fixture.parameter);
        let evidence = fixture.parameter.admission.clone();
        let round: crate::AgentdSelfIterationRoundV1 = serde_json::from_value(serde_json::json!({
            "goal":"goal.prepared-client", "ordinal":1, "candidate_admissions":32,
            "policy":digest("whole policy").to_string(),
            "execution":digest("whole execution").to_string(),
            "admitted_at_ms":1,"deadline_ms":100,
        }))
        .expect("original typed Round codec");
        let expected_round =
            crate::client::encode_hex(&round.canonical_bytes().expect("whole Round"));
        let search = std::path::PathBuf::from("/root/original-unsigned-search-shape");
        let search_pin = digest("original unsigned search shape source");
        let agent = fixture.state.identity().agent_id.clone();
        let baseline = crate::ParameterPreparationBaselineV1 {
            agent_id: agent.to_string(),
            artifact_id: input.baseline_id.to_string(),
            model_id: "stable-operational-model-id".into(),
            model_generation: input.baseline_generation.get(),
            model_content_digest: input.generated.selected_artifact_digest.to_string(),
            runtime_configuration_digest: digest("original runtime config").to_string(),
            body_digest: digest("original body").to_string(),
            registry_head_digest: evidence.artifact_registry_head_digest.to_string(),
            material_source: "/root/original-baseline-material".into(),
            material_digest: digest("original whole material").to_string(),
            context_source: "/root/original-input-context".into(),
            context_digest: digest("original whole context").to_string(),
        };
        assert_ne!(baseline.artifact_id, baseline.model_id);
        let expected = (8, input.clone(), evidence.clone(), baseline.clone());
        let mut query =
            crate::parameter_admission_query::query(&input).expect("whole profile/input");
        let mut admission_hex = crate::client::encode_hex(
            &encode_untrusted_plasticity_admission_v1(&evidence).expect("whole admission"),
        );
        let directory = tempfile::tempdir().expect("original socket fixture");
        let socket = directory.path().join("prepared-client.sock");
        let mut listener = codex_uds::UnixListener::bind(&socket)
            .await
            .expect("listen");
        let client = AgentdClient::new(socket, agent.clone(), 7).expect("original client");
        let task = tokio::spawn(async move {
            let stream = listener.accept().await.expect("actual socket peer");
            let (reader, mut writer) = tokio::io::split(stream);
            let mut frame = Vec::new();
            BufReader::new(reader)
                .read_until(b'\n', &mut frame)
                .await
                .expect("read original frame");
            let request: AgentdRequest = serde_json::from_slice(&frame).expect("original request");
            let AgentdMethod::PrepareParameterInputV1 {
                mut round_hex,
                search_source,
                search_digest,
            } = request.method
            else {
                panic!("wrong finite read purpose")
            };
            assert_eq!(round_hex, expected_round);
            let mut baseline = baseline;
            let mut spawn_generation = 7;
            match case {
                PreparedReplyCase::Exact => {}
                PreparedReplyCase::ForeignSpawn => spawn_generation = 8,
                PreparedReplyCase::ForeignRound => round_hex = "00".into(),
                PreparedReplyCase::ForeignHead => {
                    baseline.registry_head_digest = digest("different CURRENT").to_string()
                }
                PreparedReplyCase::ForeignParameter => {
                    baseline.artifact_id = baseline.model_id.clone();
                    query.baseline_id = baseline.model_id.clone();
                }
                PreparedReplyCase::ForeignModelGeneration => baseline.model_generation += 1,
                PreparedReplyCase::RelativeSource => {
                    baseline.material_source = "relative-source".into()
                }
                PreparedReplyCase::PartialAdmission => {
                    admission_hex.pop();
                }
            }
            let response = AgentdResponse {
                schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: request.request_id,
                agent_id: agent,
                spawn_generation,
                current_generation: 8,
                payload: AgentdPayload::PreparedParameterInputV1 {
                    round_hex,
                    search_source,
                    search_digest,
                    query,
                    admission_hex,
                    baseline,
                },
            };
            let mut frame = serde_json::to_vec(&response).expect("whole response");
            frame.push(b'\n');
            writer
                .write_all(&frame)
                .await
                .expect("original response write");
        });
        let result = client
            .prepare_parameter_input_v1(round, search, search_pin)
            .await;
        task.await.expect("fixture server closed");
        match case {
            PreparedReplyCase::Exact => assert_eq!(result.expect("exact whole facts"), expected),
            _ => assert!(result.is_err()),
        }
    }
}
