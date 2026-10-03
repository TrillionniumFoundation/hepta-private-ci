use super::*;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;

#[tokio::test]
async fn checkpoint_socket_authenticates_actual_root_before_round_or_material_lookup() {
    let (directory, _, state) =
        super::super::isolation_tests::fixture_with_readiness(false).expect("state");
    let state = Arc::new(state);
    let socket = directory.path().join("checkpoint.sock");
    let cancel = tokio_util::sync::CancellationToken::new();
    let server = crate::AgentdControlServer::bind(socket.clone(), state.clone(), cancel.clone())
        .await
        .expect("original socket");
    let task = tokio::spawn(server.run());
    let mut stream = codex_uds::UnixStream::connect(socket)
        .await
        .expect("connect");
    let request = crate::AgentdRequest {
        schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 1,
        spawn_generation: 1,
        method: crate::AgentdMethod::PrepareParameterCheckpointV1 {
            round_hex: "invalid".into(),
            material_source: PathBuf::from("/must-not-read-material"),
            material_digest: "invalid".into(),
        },
    };
    let mut bytes = serde_json::to_vec(&request).expect("request");
    bytes.push(b'\n');
    stream.write_all(&bytes).await.expect("write");
    let mut response = String::new();
    BufReader::new(stream)
        .read_line(&mut response)
        .await
        .expect("read");
    if unsafe { libc::geteuid() } == 0 {
        assert!(
            response.contains("checkpoint requires healthy actual Running Agent"),
            "{response}"
        );
    } else {
        assert!(response.contains("root_peer_required"), "{response}");
    }
    cancel.cancel();
    task.await.expect("retirement").expect("server");
}

fn inputs(
    now: u64,
) -> (
    crate::CanonicalIterationEnvelopeV1,
    codex_hepta_agent_components::learning_artifacts::IterationEnvelopeV1,
) {
    use codex_hepta_agent_components::learning_artifacts::IterationEnvelopeV1;
    let objective = Digest32::of_bytes(b"lock.metrics.objective");
    let grammar = Digest32::of_bytes(b"checkpoint grammar");
    let commit = "1".repeat(40);
    let tree = "2".repeat(40);
    let expires = now + 120_000;
    let json = serde_json::json!({"envelopeId":"checkpoint.window", "baseCommit":commit,"baseTree":tree,"objectiveDigest":objective.to_string(),"grammarDigest":grammar.to_string(),"allowedPaths":["original/store"],"deniedAuthorities":["promote"],"maximumFiles":2,"maximumBytes":4096,"maximumCandidates":2,"wallTimeMicros":60_000_000,"computeBudget":{"profile":"hepta.iteration-compute-budget.v1","maximumParallelSandboxes":1,"maximumMemoryBytes":4096,"maximumProcesses":2},"mandatoryChecks":["original/checkpoint"],"expiresUnixMs":expires});
    (
        crate::CanonicalIterationEnvelopeV1::decode(&serde_json::to_vec(&json).expect("JSON"))
            .expect("canonical"),
        IterationEnvelopeV1 {
            envelope_id: StableId::new("checkpoint.window").expect("id"),
            base_commit: Digest32::of_bytes(commit.as_bytes()),
            base_tree: Digest32::of_bytes(tree.as_bytes()),
            objective_digest: objective,
            grammar_digest: grammar,
            maximum_files: 2,
            maximum_diff_bytes: 4096,
            maximum_candidates: 2,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: expires / 1000,
        },
    )
}

/// Must be run as actual UID0 against the real UDS/held runtime. An ordinary
/// ignored count is not qualification of this protected path.
#[tokio::test]
#[ignore = "requires actual UID0 and exclusively created /run fixture"]
async fn actual_root_checkpoint_socket_reads_whole_current_state_and_rejects_round_pin_and_pending()
{
    assert_eq!(
        unsafe { libc::geteuid() },
        0,
        "actual Root qualification required"
    );
    let protected = tempfile::Builder::new()
        .prefix("hepta-checkpoint-owner-")
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir_in("/run")
        .expect("original Root fixture");
    let root = protected.path();
    let (runtime, material, host) =
        crate::neuron_runtime_v2::parameter_checkpoint_tests::fixture(root);
    let encoded_material =
        codex_hepta_agent_components::neuron::encode_neuron_generation_material_v2(&material)
            .expect("whole material");
    let material_source = root.join("baseline-material.json");
    std::fs::write(&material_source, &encoded_material).expect("material");
    std::fs::set_permissions(&material_source, std::fs::Permissions::from_mode(0o444))
        .expect("protected material");
    let pin = Digest32::of_bytes(&encoded_material);
    let journal = root.join("iteration.json");
    let now: u64 = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("clock")
        .as_millis()
        .try_into()
        .expect("clock bound");

    let (configuration, handle) = crate::AgentdSelfIterationRuntimeConfigV1::new(
        journal.clone(),
        crate::self_iteration::checkpoint_test_trust(now, material.scope.objective_digest),
    )
    .expect("original Round owner");
    let iteration = configuration
        .start(host.clone())
        .expect("same retained host");
    let iteration_cancel = tokio_util::sync::CancellationToken::new();
    let iteration_task = tokio::spawn(iteration.run(iteration_cancel.clone()));
    let (canonical, envelope) = inputs(now);
    let round = handle
        .reserve_round(
            StableId::new("checkpoint.goal").expect("goal"),
            canonical,
            envelope,
        )
        .await
        .expect("original debit/reservation");
    let (_state_directory, _, state) =
        super::super::isolation_tests::fixture_with_readiness(false).expect("state");
    let cognitive = codex_hepta_agent_components::cognitive_store::DurableCognitiveStore::open(
        &state.identity.layout,
    )
    .await
    .expect("original cognitive owner");
    state
        .attach_cognitive_store(Arc::new(cognitive))
        .expect("attach");
    state
        .mark_runtime_prerequisites_ready()
        .expect("actual prerequisites");
    state.mark_app_server_ready().expect("AppServer readiness");
    assert!(state.neuron_runtime_v2.set(host.clone()).is_ok());
    assert!(state.self_iteration_handle.set(handle.clone()).is_ok());
    let agent = state.identity.agent_id.clone();
    let state = Arc::new(state);
    let socket = root.join("checkpoint.sock");
    let cancel = tokio_util::sync::CancellationToken::new();
    let server = crate::AgentdControlServer::bind(socket.clone(), state.clone(), cancel.clone())
        .await
        .expect("original actual UDS");
    let server_task = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(socket, agent, 1).expect("Root client");
    let before = [
        std::fs::read(&journal).expect("journal"),
        std::fs::read(&material.generation_store).expect("store"),
        std::fs::read(&material.runtime_index).expect("index"),
        std::fs::read(&material.witness).expect("witness"),
    ];
    let (scope_generation, serving, original_response) = client
        .inspect_parameter_serving_scope_source_v1(round.clone())
        .await
        .expect("actual Root Serving scope");
    assert_eq!(scope_generation, 2);
    assert!(original_response.ends_with(b"\n"));
    let neutral: crate::AgentdResponse =
        serde_json::from_slice(&original_response).expect("whole original neutral frame");
    assert_eq!(neutral.current_generation, scope_generation);
    assert_eq!(
        neutral.request_id, 1,
        "source API dispatches exactly one original request"
    );
    assert_eq!(neutral.agent_id, state.identity.agent_id);
    let low = codex_hepta_contracts::decode_original_parameter_serving_scope_response_v1(
        &original_response,
    )
    .expect("sole low original envelope accepts actual authenticated response bytes");
    assert_eq!(low.request_id, neutral.request_id);
    assert_eq!(low.agent_id, neutral.agent_id);
    assert_eq!(low.spawn_generation, neutral.spawn_generation);
    assert_eq!(low.current_generation, neutral.current_generation);
    let crate::AgentdPayload::ParameterServingScopeV1(original_scope) = neutral.payload else {
        panic!("original Serving payload")
    };
    let codex_hepta_contracts::ParameterServingScopePayloadV1::ParameterServingScopeV1(low_scope) =
        low.payload;
    assert_eq!(original_scope, low_scope);
    assert_eq!(
        original_scope.round_hex,
        crate::client::encode_hex(&round.canonical_bytes().expect("Round"))
    );

    assert_eq!(serving.round, round);
    assert_eq!(serving.scope, material.scope);
    assert_eq!(
        serving.goal_ordinal, None,
        "legacy owner is not invented as Goal ordinal1"
    );
    assert_eq!(
        client
            .inspect_parameter_serving_scope_v1(round.clone())
            .await
            .expect("same readonly Scope"),
        (scope_generation, serving)
    );
    let (generation, first) = client
        .prepare_parameter_checkpoint_v1(round.clone(), material_source.clone(), pin)
        .await
        .expect("whole actual Root observation");
    assert_eq!(generation, 2);
    assert_eq!(first.round, round);
    assert_eq!(first.anchor.sequence, 1);
    assert_eq!(first.goal_ordinal, None);
    assert_eq!(
        first
            .checkpoint(&material)
            .expect("all vectors")
            .eligibility_q24()
            .len(),
        material.native.width
    );
    let mut path_changed = material.clone();
    path_changed.generation_store = root.join("different-physical-store");
    assert!(
        first.checkpoint(&path_changed).is_err(),
        "whole material pin retains original physical source paths"
    );
    let repeated = client
        .prepare_parameter_checkpoint_v1(round.clone(), material_source.clone(), pin)
        .await
        .expect("repeat only read");
    assert_eq!(repeated, (generation, first));
    assert_eq!(
        [
            std::fs::read(&journal).expect("journal"),
            std::fs::read(&material.generation_store).expect("store"),
            std::fs::read(&material.runtime_index).expect("index"),
            std::fs::read(&material.witness).expect("witness")
        ],
        before
    );
    let mut wrong = serde_json::to_value(&round).expect("Round");
    wrong["goal"] = "other.goal".into();
    let wrong: crate::AgentdSelfIterationRoundV1 =
        serde_json::from_value(wrong).expect("typed different Round");
    assert!(
        client
            .inspect_parameter_serving_scope_v1(wrong.clone())
            .await
            .is_err()
    );
    assert!(
        client
            .prepare_parameter_checkpoint_v1(wrong, material_source.clone(), pin)
            .await
            .is_err()
    );
    assert!(
        client
            .prepare_parameter_checkpoint_v1(
                round.clone(),
                material_source.clone(),
                Digest32::of_bytes(b"wrong pin")
            )
            .await
            .is_err()
    );
    // Actual pending model intent cannot be bypassed by a read-only Root call.
    let request = codex_hepta_agent_components::infer_core::SelfIterationModelRequestV1 {
        request_id: round
            .model_request_id(
                codex_hepta_agent_components::infer_core::SelfIterationModelRoleV1::Generator,
                None,
            )
            .expect("exact request"),
        role: codex_hepta_agent_components::infer_core::SelfIterationModelRoleV1::Generator,
        envelope_digest: round.execution_envelope_digest(),
        candidate_digest: None,
        prompt: "fixture original intent".into(),
        deadline_ms: round.deadline_ms(),
        maximum_response_bytes: 8192,
    };
    handle
        .begin_model(round.clone(), request)
        .await
        .expect("durable pending original intent");
    let pending = std::fs::read(&journal).expect("pending journal");
    assert!(
        client
            .inspect_parameter_serving_scope_v1(round.clone())
            .await
            .is_err()
    );
    assert!(
        client
            .prepare_parameter_checkpoint_v1(round, material_source, pin)
            .await
            .is_err()
    );
    assert_eq!(std::fs::read(&journal).expect("journal"), pending);
    assert_eq!(runtime.calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    cancel.cancel();
    server_task.await.expect("server retire").expect("server");
    iteration_cancel.cancel();
    iteration_task
        .await
        .expect("Round retire")
        .expect("Round owner");
}
