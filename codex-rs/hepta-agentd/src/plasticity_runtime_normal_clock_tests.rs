use super::*;

use codex_hepta_agent_components::intelligence::TopologyPlasticityProductErrorV1;
use codex_hepta_agent_components::learning_ledger::CausalV2Error;
use codex_hepta_agent_components::learning_ledger::SignedEvidenceError;

use crate::AgentdPlasticityHostErrorV1;
use crate::AgentdTopologyHostErrorV1;
use crate::PlasticityOwnerEvidenceErrorV1;
use crate::plasticity_runtime::PlasticityRuntimeCallErrorV1;
use crate::plasticity_runtime::PlasticityRuntimeOwnerV1;

struct ClockFixture {
    _daemon: AgentdFixture,
    _runtime_root: TempDir,
    state: Arc<AgentdState>,
    owner: PlasticityRuntimeOwnerV1,
    files: RuntimeFiles,
    parameter: ParameterPlasticityProductRequestV1,
    topology: TopologyPlasticityProductRequestV1,
}

fn normal_clock_fixture() -> ClockFixture {
    let daemon = AgentdFixture::new();
    let runtime_root = tempfile::tempdir().expect("runtime root");
    let files = runtime_files(runtime_root.path());
    let mut ledger =
        DurableLedger::create(new_file(&files.ledger), digest("ledger:clock-binding"), 32)
            .expect("ledger create");
    ledger
        .append_qualification(
            Digest32::ZERO,
            ledger_decision(digest("plasticity-clock-objective")),
        )
        .expect("ledger append");
    let sources = build_owner_sources(
        runtime_root.path(),
        &ledger,
        digest("plasticity-clock-objective"),
        digest("plasticity-clock-selected"),
    );
    let signing = SigningFixture::new();
    let verifier = signing.verifier(sources.objective_digest);
    let parameter = signed_request(&sources, &ledger, &signing, &verifier);
    let topology = signed_topology_request(&sources, &ledger, &signing, &verifier);
    let (parameter_writer, parameter_anchor_store) = bootstrap_agentd_plasticity_writer_v1(
        new_file(&files.parameter_registry),
        new_file(&files.parameter_anchor),
        digest("parameter-clock-scope"),
        32,
    )
    .expect("parameter writer");
    let (topology_writer, topology_anchor_store) = bootstrap_agentd_topology_writer_v1(
        new_file(&files.topology_registry),
        new_file(&files.topology_anchor),
        digest("topology-clock-scope"),
        32,
    )
    .expect("topology writer");
    let bootstrap = PlasticityRuntimeBootstrapV1::new(
        8,
        sources.artifacts.clone(),
        ledger,
        Box::new(resolver(&sources)),
        sources.owner_policy.clone(),
        verifier,
        parameter_writer,
        parameter_anchor_store,
        topology_writer,
        topology_anchor_store,
    )
    .expect("runtime bootstrap");
    let state = daemon.state();
    let (handle, mut owner) = bootstrap.into_channel().expect("compose owner");
    owner.current_artifacts = Some(
        crate::plasticity_runtime::current_artifacts::fixture_current_artifacts(&sources.artifacts),
    );
    state
        .attach_plasticity_runtime(handle)
        .expect("attach owner");
    ClockFixture {
        _daemon: daemon,
        _runtime_root: runtime_root,
        state,
        owner,
        files,
        parameter,
        topology,
    }
}

fn persistent_bytes(files: &RuntimeFiles) -> Vec<Vec<u8>> {
    [
        &files.parameter_registry,
        &files.parameter_anchor,
        &files.topology_registry,
        &files.topology_anchor,
    ]
    .into_iter()
    .map(|path| fs::read(path).expect("read durable state"))
    .collect()
}

#[tokio::test]
async fn installed_model_context_uses_original_plasticity_owner_and_clock() {
    let fixture = normal_clock_fixture();
    let before = persistent_bytes(&fixture.files);
    let context = crate::AgentdSelfIterationModelOwnerContextV2::from_state(&fixture.state);
    assert!(context.neuron_host().is_none());
    let handle = context
        .plasticity_handle()
        .expect("original daemon plasticity handle");
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    let result = handle.propose_parameter(fixture.parameter, 50).await;
    cancellation.cancel();
    owner_task
        .await
        .expect("original owner join")
        .expect("original owner shutdown");
    assert!(
        matches!(
            result,
            Err(PlasticityRuntimeCallErrorV1::Parameter(
                AgentdPlasticityHostErrorV1::OwnerEvidence(PlasticityOwnerEvidenceErrorV1::Missing)
            ))
        ),
        "installed context bypassed the original owner or revived expired evidence: {result:?}"
    );
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
async fn producer_time_cannot_revive_expired_parameter_owner_evidence() {
    let fixture = normal_clock_fixture();
    let before = persistent_bytes(&fixture.files);
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    let result = fixture
        .state
        .submit_parameter_plasticity_v1(fixture.parameter, 50)
        .await;
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    // The original dataset receipt verifier rejects the expired receipt before
    // the owner resolver can return a receipt for the later Stale check.
    assert!(
        matches!(
            result,
            Err(PlasticityRuntimeCallErrorV1::Parameter(
                AgentdPlasticityHostErrorV1::OwnerEvidence(PlasticityOwnerEvidenceErrorV1::Missing)
            ))
        ),
        "expired owner evidence was accepted using producer time: {result:?}"
    );
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
async fn producer_time_cannot_revive_expired_topology_signatures() {
    let fixture = normal_clock_fixture();
    let before = persistent_bytes(&fixture.files);
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    let result = fixture
        .state
        .submit_topology_plasticity_v1(fixture.topology, 50)
        .await;
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    assert!(
        matches!(
            result,
            Err(PlasticityRuntimeCallErrorV1::Topology(
                AgentdTopologyHostErrorV1::Product(
                    TopologyPlasticityProductErrorV1::GeneratorEvidence(
                        SignedEvidenceError::ValidityWindow
                            | SignedEvidenceError::Principal(CausalV2Error::AuthenticationWindow)
                    )
                )
            ))
        ),
        "expired topology signature was accepted using producer time: {result:?}"
    );
    assert_eq!(persistent_bytes(&fixture.files), before);
}
