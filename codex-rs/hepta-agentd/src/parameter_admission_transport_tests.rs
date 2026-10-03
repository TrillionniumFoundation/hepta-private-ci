//! Actual owner, kernel peer gate and exact factual response correlation.
use super::*;
use crate::AgentdClient;
use crate::AgentdControlServer;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use codex_hepta_agent_components::plasticity::encode_untrusted_plasticity_admission_v1;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;

fn input(request: &ParameterPlasticityProductRequestV1) -> crate::AgentdPlasticityAdmissionInputV1 {
    let a = &request.admission;
    crate::AgentdPlasticityAdmissionInputV1 {
        baseline_id: a.baseline_id.clone(),
        objective_digest: a.objective_digest,
        generator_profile: request.generator_profile.clone(),
        generated: request.generated.clone(),
        baseline_generation: a.baseline_generation,
        candidate_generation: a.candidate_generation,
        dataset_digest: a.dataset_digest,
        update_rule_digest: a.update_rule_digest,
        modulator_digest: a.modulator_digest,
        modulator_broadcast_digest: a.modulator_broadcast_digest,
        eligibility_digest: a.eligibility_digest,
    }
}

#[tokio::test]
async fn actual_non_root_peer_cannot_resolve_seven_owner_facts_or_sample_owner_clock() {
    assert_ne!(unsafe { libc::geteuid() }, 0, "ordinary workload fixture");
    let mut fixture = clock_fixture(|| Ok(50));
    let reads = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let observed = Arc::clone(&reads);
    fixture.owner.clock = Box::new(move || {
        observed.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        Ok(50)
    });
    let before = persistent_bytes(&fixture.files);
    let request = input(&fixture.parameter);
    let cancellation = CancellationToken::new();
    let owner = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    let socket = fixture
        ._runtime_root
        .path()
        .join("parameter-admission.sock");
    let server = AgentdControlServer::bind(
        socket.clone(),
        Arc::clone(&fixture.state),
        cancellation.clone(),
    )
    .await
    .expect("same control socket");
    let serving = tokio::spawn(server.run());
    let client =
        AgentdClient::new(socket, fixture.state.identity().agent_id.clone(), 1).expect("client");
    assert!(
        matches!(client.resolve_parameter_admission_v1(request).await,
        Err(AgentdError::Protocol(message)) if message.contains("root_peer_required"))
    );
    assert!(matches!(client.prepare_parameter_input_v1(
        super::input_context_tests::fixture_round(),std::path::PathBuf::from("/missing/root-search"),
        digest("protected search pin")).await,
        Err(AgentdError::Protocol(message)) if message.contains("root_peer_required")));
    assert_eq!(reads.load(std::sync::atomic::Ordering::SeqCst), 0);
    client
        .health()
        .await
        .expect("ordinary lifecycle remains readable");
    cancellation.cancel();
    serving.await.expect("server").expect("retired");
    owner.await.expect("owner").expect("retired");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
#[ignore = "requires an actual UID0 process; original non-Root gate is separately exercised"]
async fn actual_root_peer_resolves_whole_current_admission_without_appending() {
    assert_eq!(unsafe { libc::geteuid() }, 0, "actual kernel Root peer");
    let fixture = clock_fixture(|| Ok(50));
    // Original Fleet Starting1 -> Running2 advances runtime independently from
    // the actual process spawn1. The public read returns runtime generation.
    assert_eq!(fixture.state.identity().spawn_generation, 1);
    let expected_runtime = fixture
        .state
        .current_generation()
        .expect("original current owner");
    assert_eq!(expected_runtime, 2);

    let expected = fixture.parameter.admission.clone();
    let request = input(&fixture.parameter);
    let before = persistent_bytes(&fixture.files);
    let cancellation = CancellationToken::new();
    let owner = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    let socket = fixture
        ._runtime_root
        .path()
        .join("parameter-admission-root.sock");
    let server = AgentdControlServer::bind(
        socket.clone(),
        Arc::clone(&fixture.state),
        cancellation.clone(),
    )
    .await
    .expect("same socket");
    let serving = tokio::spawn(server.run());
    let client =
        AgentdClient::new(socket, fixture.state.identity().agent_id.clone(), 1).expect("client");
    assert_eq!(
        client
            .resolve_parameter_admission_v1(request)
            .await
            .expect("actual owner admission"),
        (expected_runtime, expected)
    );
    cancellation.cancel();
    serving.await.expect("server").expect("retired");
    owner.await.expect("owner").expect("retired");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
async fn original_client_keeps_runtime_generation_and_rejects_foreign_query_or_fact() {
    for case in [0, 1, 2] {
        let fixture = clock_fixture(|| Ok(50));
        let request = input(&fixture.parameter);
        let expected = fixture.parameter.admission.clone();
        let mut admission = expected.clone();
        if case == 2 {
            admission.dataset_digest = digest("different-original-dataset");
        }
        let bytes = encode_untrusted_plasticity_admission_v1(&admission).expect("sole full codec");
        let directory = tempfile::tempdir().expect("directory");
        let path = directory.path().join("parameter-client.sock");
        let mut listener = codex_uds::UnixListener::bind(&path)
            .await
            .expect("listener");
        let agent = fixture.state.identity().agent_id.clone();
        let client = AgentdClient::new(path, agent.clone(), 7).expect("client");
        let task = tokio::spawn(async move {
            let stream = listener.accept().await.expect("accept");
            let (reader, mut writer) = tokio::io::split(stream);
            let mut frame = Vec::new();
            BufReader::new(reader)
                .read_until(b'\n', &mut frame)
                .await
                .expect("read");
            let request: AgentdRequest = serde_json::from_slice(&frame).expect("request");
            let AgentdMethod::ResolveParameterAdmissionV1 { mut query } = request.method else {
                panic!("wrong method")
            };
            if case == 1 {
                query.baseline_id = "different-baseline".into();
            }
            let response = AgentdResponse {
                schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: request.request_id,
                agent_id: agent,
                spawn_generation: 7,
                current_generation: 8,
                payload: AgentdPayload::ParameterAdmissionV1 {
                    query,
                    admission_hex: crate::client::encode_hex(&bytes),
                },
            };
            let mut frame = serde_json::to_vec(&response).expect("response");
            frame.push(b'\n');
            writer.write_all(&frame).await.expect("write");
        });
        let result = client.resolve_parameter_admission_v1(request).await;
        task.await.expect("server");
        if case == 0 {
            assert_eq!(result.expect("whole original facts"), (8, expected));
        } else {
            assert!(result.is_err());
        }
    }
}

#[test]
fn profile_query_rejects_partial_uppercase_and_over_frame_material() {
    let fixture = clock_fixture(|| Ok(50));
    let query = crate::parameter_admission_query::query(&input(&fixture.parameter)).expect("query");
    for hex in [
        query.profile_hex[..query.profile_hex.len() - 2].to_owned(),
        "FF".to_owned(),
        "00".repeat(crate::MAX_CONTROL_FRAME_BYTES as usize),
    ] {
        let mut altered = query.clone();
        altered.profile_hex = hex;
        assert!(crate::parameter_admission_query::decode_query(&altered).is_err());
    }
}

include!("parameter_preparation_client_tests.rs");
