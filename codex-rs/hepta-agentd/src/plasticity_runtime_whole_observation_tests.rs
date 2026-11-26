//! Actual original cold row, bounded writer channel and whole-record transport.
//! Synthetic proposal data proves neither model evaluation nor acceptance.
use super::*;
use codex_hepta_agent_components::intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_agent_components::intelligence::PlasticityAnchorCommitterV1;
use codex_hepta_agent_components::plasticity::DurableCompletedProposalV1;
use codex_hepta_agent_components::plasticity::DurableProposalRegistry;
use codex_hepta_agent_components::plasticity::ParameterCandidateKindV2;
use codex_hepta_agent_components::plasticity::ParameterCandidateRequestV2;
use codex_hepta_agent_components::plasticity::ParameterDeltaV2;
use codex_hepta_agent_components::plasticity::ParameterProposalRequestV2;

#[path = "plasticity_whole_client_tests.rs"]
mod client_tests;
#[path = "plasticity_whole_root_process_fixture.rs"]
mod root_process;

fn large_original_row() -> (ClockFixture, DurableCompletedProposalV1, Vec<PathBuf>) {
    let mut fixture = clock_fixture(|| Ok(50));
    let root = fixture._runtime_root.path();
    let registry_path = root.join("large-completed.registry");
    let anchor_path = root.join("large-completed.anchor");
    let scope = digest("large-completed-scope");
    let mut anchor = AgentdPlasticityAnchorStoreV1::open(new_file(&anchor_path), scope)
        .expect("original independent anchor owner");
    let fence = anchor.issue_next_fence().expect("original fence");
    let selected = digest("large-completed-selected");
    let proposal =
        codex_hepta_agent_components::plasticity::propose_v2(ParameterProposalRequestV2 {
            proposal_id: id("proposal.large.completed"),
            proposer_id: id("proposer.large.completed"),
            evaluator_id: id("evaluator.large.completed"),
            selected_artifact_digest: selected,
            window: ProposalWindowV2 {
                window_id: id("window.large.completed"),
                window_digest: digest("large-completed-window"),
            },
            baseline_generation: generation(1),
            candidate_generation: generation(2),
            dataset_digest: digest("large-completed-dataset"),
            update_rule_digest: digest("large-completed-rule"),
            modulator_digest: digest("large-completed-modulator"),
            modulator_broadcast_digest: digest("large-completed-broadcast"),
            eligibility_digest: digest("large-completed-eligibility"),
            evaluation_digest: digest("large-completed-evaluation"),
            rollback_predecessor_digest: selected,
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer.large.completed"),
                baseline_squared_l2_raw_q64: 1_000_000_000_000,
            }],
            candidates: vec![
                ParameterCandidateRequestV2 {
                    candidate_id: id("candidate.large.nochange"),
                    kind: ParameterCandidateKindV2::NoChange,
                    parameter_deltas: Vec::new(),
                },
                ParameterCandidateRequestV2 {
                    candidate_id: id("candidate.large.update"),
                    kind: ParameterCandidateKindV2::Update,
                    parameter_deltas: (0..1024)
                        .map(|index| ParameterDeltaV2 {
                            layer_id: id("layer.large.completed"),
                            parameter_id: id(&format!("parameter.large.completed.{index:04}")),
                            delta: FixedQ32::from_raw(1),
                            lower_bound: FixedQ32::from_raw(-10),
                            upper_bound: FixedQ32::from_raw(10),
                            evidence_digest: digest("large-completed-signal"),
                        })
                        .collect(),
                },
            ],
        })
        .expect("sole original proposal rules");
    let mut registry =
        DurableProposalRegistry::open_bootstrap_empty(new_file(&registry_path), scope, fence, 32)
            .expect("actual original writer");
    let receipt = registry
        .append_v2(Digest32::ZERO, proposal.clone())
        .expect("actual append");
    let head = registry
        .current_anchor()
        .expect("head")
        .expect("complete row");
    assert!(anchor.persist_anchor(scope, fence, head));
    drop(registry);
    let cold_file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&registry_path)
        .expect("original cold file");
    let writer = AnchoredPlasticityWriterV1::reopen_anchored(cold_file, scope, fence, 32, head)
        .expect("same original anchored cold writer");
    let row = writer
        .observe_completed_proposal_v1(&proposal.proposal_id, anchor.anchor())
        .expect("read only")
        .expect("original complete row");
    assert_eq!(row.proposal, proposal);
    assert_eq!(row.receipt, receipt);
    assert!(
        row.to_bytes().expect("whole original packet").len()
            > crate::MAX_CONTROL_FRAME_BYTES as usize
    );
    fixture.owner.parameter_writer = writer;
    fixture.owner.parameter_anchor_store = anchor;
    (fixture, row, vec![registry_path, anchor_path])
}

#[tokio::test]
async fn completed_large_original_row_uses_the_actual_owner_and_root_socket_without_new_writes() {
    if let Some(directory) = root_process::child_directory() {
        root_process::serve_child(directory).await;
        return;
    }
    if unsafe { libc::geteuid() } == 0 {
        root_process::read_from_actual_non_root_child().await;
        return;
    }
    let (mut fixture, expected, paths) = large_original_row();
    let reads = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let observed_reads = Arc::clone(&reads);
    fixture.owner.clock = Box::new(move || {
        observed_reads.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        Ok(50)
    });
    let before: Vec<_> = paths
        .iter()
        .map(|path| fs::read(path).expect("before"))
        .collect();
    let cancellation = CancellationToken::new();
    let owner = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    let bytes = fixture
        .handle
        .observe_completed_proposal(expected.proposal.proposal_id.clone())
        .await
        .expect("same bounded original owner")
        .expect("actual row");
    assert_eq!(
        DurableCompletedProposalV1::from_bytes(&bytes).expect("whole original codec"),
        expected
    );
    let socket = fixture._runtime_root.path().join("large-observation.sock");
    let server = crate::AgentdControlServer::bind(
        socket.clone(),
        Arc::clone(&fixture.state),
        cancellation.clone(),
    )
    .await
    .expect("actual original socket");
    let serving = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(socket, fixture.state.identity().agent_id.clone(), 1)
        .expect("original client")
        .with_peer_process(unsafe { libc::geteuid() }, std::process::id())
        .expect("actual original server process");
    let result = client
        .plasticity_completed_proposal(expected.proposal.proposal_id.clone())
        .await;
    assert!(
        matches!(result, Err(AgentdError::Protocol(message)) if message.contains("root_peer_required"))
    );
    assert_eq!(reads.load(std::sync::atomic::Ordering::SeqCst), 1);
    cancellation.cancel();
    serving.await.expect("server join").expect("server retired");
    owner.await.expect("writer join").expect("writer retired");
    let after: Vec<_> = paths
        .iter()
        .map(|path| fs::read(path).expect("after"))
        .collect();
    assert_eq!(after, before);
}
