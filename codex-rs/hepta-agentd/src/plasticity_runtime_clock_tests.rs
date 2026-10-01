use super::*;

use codex_hepta_intelligence::ParameterPlasticityProductErrorV1;
use codex_hepta_intelligence::TopologyPlasticityProductErrorV1;
use codex_hepta_learning_ledger::SignedEvidenceError;

use crate::AgentdError;
use crate::AgentdPlasticityHostErrorV1;
use crate::AgentdTopologyHostErrorV1;
use crate::PlasticityOwnerEvidenceErrorV1;
use crate::plasticity_runtime::PlasticityRuntimeCallErrorV1;
use crate::plasticity_runtime::PlasticityRuntimeCommandV1;
use crate::plasticity_runtime::PlasticityRuntimeHandleV1;
use crate::plasticity_runtime::PlasticityRuntimeOwnerV1;

struct ClockFixture {
    _daemon: AgentdFixture,
    _runtime_root: TempDir,
    state: Arc<AgentdState>,
    handle: PlasticityRuntimeHandleV1,
    owner: PlasticityRuntimeOwnerV1,
    files: RuntimeFiles,
    parameter: ParameterPlasticityProductRequestV1,
    topology: TopologyPlasticityProductRequestV1,
}

fn clock_fixture(clock: fn() -> Result<u64, AgentdError>) -> ClockFixture {
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
    state
        .attach_plasticity_runtime(handle.clone())
        .expect("attach owner");
    owner.clock = Box::new(clock);
    ClockFixture {
        _daemon: daemon,
        _runtime_root: runtime_root,
        state,
        handle,
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

fn advancing_clock(
    initial: u64,
    final_now: u64,
) -> Box<dyn FnMut() -> Result<u64, AgentdError> + Send> {
    let mut first = Some(initial);
    Box::new(move || Ok(first.take().unwrap_or(final_now)))
}

#[tokio::test]
async fn parameter_owner_receipt_that_expires_during_preparation_cannot_be_appended() {
    let mut fixture = clock_fixture(|| Ok(50));
    fixture.owner.clock = advancing_clock(/*initial*/ 50, /*final_now*/ 61);
    let before = persistent_bytes(&fixture.files);
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    assert!(matches!(
        fixture
            .state
            .submit_parameter_plasticity_v1(fixture.parameter, 50)
            .await,
        Err(PlasticityRuntimeCallErrorV1::Parameter(
            AgentdPlasticityHostErrorV1::Product(ParameterPlasticityProductErrorV1::Binding(
                "owner evidence expired before append"
            ))
        ))
    ));
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
async fn parameter_signature_that_expires_during_preparation_cannot_be_appended() {
    let mut fixture = clock_fixture(|| Ok(50));
    fixture.owner.clock = advancing_clock(/*initial*/ 50, /*final_now*/ 51);
    fixture.parameter.generator_attestation.expires_at = 50;
    fixture.parameter.generator_attestation.signature = SigningFixture::new().keys[0]
        .sign(&fixture.parameter.generator_attestation.signing_bytes())
        .to_bytes();
    let before = persistent_bytes(&fixture.files);
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    assert!(matches!(
        fixture
            .state
            .submit_parameter_plasticity_v1(fixture.parameter, 50)
            .await,
        Err(PlasticityRuntimeCallErrorV1::Parameter(
            AgentdPlasticityHostErrorV1::Product(ParameterPlasticityProductErrorV1::Evaluation(
                codex_hepta_intelligence_eval::SignedEvaluationError::Evidence(
                    SignedEvidenceError::ValidityWindow
                )
            ))
        ))
    ));
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
async fn topology_signature_that_expires_during_preparation_cannot_be_appended() {
    let mut fixture = clock_fixture(|| Ok(50));
    fixture.owner.clock = advancing_clock(/*initial*/ 50, /*final_now*/ 91);
    let before = persistent_bytes(&fixture.files);
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    assert!(matches!(
        fixture
            .state
            .submit_topology_plasticity_v1(fixture.topology, 50)
            .await,
        Err(PlasticityRuntimeCallErrorV1::Topology(
            AgentdTopologyHostErrorV1::Product(
                TopologyPlasticityProductErrorV1::EvaluatorEvidence(
                    SignedEvidenceError::ValidityWindow
                )
            )
        ))
    ));
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
async fn final_clock_failure_or_regression_rejects_without_durable_effects() {
    for final_now in [Some(49), None] {
        let mut fixture = clock_fixture(|| Ok(50));
        let mut initial = Some(50);
        fixture.owner.clock = Box::new(move || {
            initial
                .take()
                .or(final_now)
                .ok_or_else(|| AgentdError::Protocol("clock unavailable".to_string()))
        });
        let before = persistent_bytes(&fixture.files);
        let cancellation = CancellationToken::new();
        let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
            Arc::clone(&fixture.state),
            Some(fixture.owner),
            cancellation.clone(),
        );
        assert!(matches!(
            fixture
                .state
                .submit_parameter_plasticity_v1(fixture.parameter, 50)
                .await,
            Err(PlasticityRuntimeCallErrorV1::Parameter(
                AgentdPlasticityHostErrorV1::Product(ParameterPlasticityProductErrorV1::Binding(
                    "final verification clock regressed" | "host clock unavailable"
                ))
            ))
        ));
        cancellation.cancel();
        owner_task
            .await
            .expect("owner join")
            .expect("owner shutdown");
        assert_eq!(persistent_bytes(&fixture.files), before);
    }
}

#[tokio::test]
async fn queued_parameter_uses_processing_time_for_owner_receipt_expiry() {
    let fixture = clock_fixture(|| Ok(61));
    let before = persistent_bytes(&fixture.files);
    // The caller supplies a formerly valid time. The owner's later time must
    // reject owner receipts whose validity ended at 60.
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
    assert!(matches!(
        result,
        Err(PlasticityRuntimeCallErrorV1::Parameter(
            AgentdPlasticityHostErrorV1::OwnerEvidence(PlasticityOwnerEvidenceErrorV1::Stale)
        ))
    ));
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
async fn caller_time_cannot_revalidate_expired_parameter_signature() {
    let mut fixture = clock_fixture(|| Ok(50));
    // Owner receipts remain valid until 60. Shorten and re-sign just the
    // Generator attestation, so rejection must come from signature validity.
    fixture.parameter.generator_attestation.expires_at = 49;
    fixture.parameter.generator_attestation.signature = SigningFixture::new().keys[0]
        .sign(&fixture.parameter.generator_attestation.signing_bytes())
        .to_bytes();
    let before = persistent_bytes(&fixture.files);
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    assert!(matches!(
        fixture
            .state
            .submit_parameter_plasticity_v1(fixture.parameter, 45)
            .await,
        Err(PlasticityRuntimeCallErrorV1::Parameter(
            AgentdPlasticityHostErrorV1::Product(
                ParameterPlasticityProductErrorV1::GeneratorEvidence(
                    SignedEvidenceError::ValidityWindow
                )
            )
        ))
    ));
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
async fn topology_evidence_that_expires_in_queue_cannot_be_appended() {
    let fixture = clock_fixture(|| Ok(91));
    let before = persistent_bytes(&fixture.files);
    let (response, receive) = tokio::sync::oneshot::channel();
    // Put the signed request into the queue before starting the owner. The
    // final host time is beyond the signed evidence expiry at 90.
    fixture
        .handle
        .sender
        .send(PlasticityRuntimeCommandV1::Topology {
            request: Box::new(fixture.topology),
            response,
        })
        .await
        .expect("queue topology");
    assert_eq!(fixture.owner.receiver.len(), 1);
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    assert!(matches!(
        receive.await.expect("topology response"),
        Err(PlasticityRuntimeCallErrorV1::Topology(
            AgentdTopologyHostErrorV1::Product(
                TopologyPlasticityProductErrorV1::GeneratorEvidence(
                    SignedEvidenceError::ValidityWindow
                )
            )
        ))
    ));
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
async fn unavailable_host_clock_rejects_both_proposal_kinds_without_durable_effects() {
    let fixture = clock_fixture(|| Err(AgentdError::Protocol("clock unavailable".to_string())));
    let before = persistent_bytes(&fixture.files);
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    assert!(matches!(
        fixture
            .state
            .submit_parameter_plasticity_v1(fixture.parameter, 50)
            .await,
        Err(PlasticityRuntimeCallErrorV1::ClockUnavailable)
    ));
    assert!(matches!(
        fixture
            .state
            .submit_topology_plasticity_v1(fixture.topology, 50)
            .await,
        Err(PlasticityRuntimeCallErrorV1::ClockUnavailable)
    ));
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[path = "plasticity_runtime_admission_tests.rs"]
mod admission_tests;
