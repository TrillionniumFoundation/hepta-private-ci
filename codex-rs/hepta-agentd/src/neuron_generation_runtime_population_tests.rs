use std::fs;
use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::CellBundleComponentsV1;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::CellCapabilityContractV1;
use codex_hepta_neuron::CellFunctionalRoleV1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellOwnerPopulationErrorV2;
use codex_hepta_neuron::CellPopulationLimitsV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::support::Fixture;
use super::support::checked;
use super::support::cost;
use super::support::generation;
use super::support::host;
use super::support::request;
use crate::NeuronGenerationRuntimeBootstrapV2;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_service::spawn_neuron_generation_service;

async fn population_fixture() -> (Fixture, CellCompatibilityBundleV1, CellCapabilityContractV1) {
    let mut fixture = Fixture::new().await;
    let artifact = CellCompatibilityBundleV1 {
        artifact_id: checked(StableId::new("selected-generator")),
        generation: generation(fixture.config.initial.generation),
        components: CellBundleComponentsV1 {
            base: Digest32::from_array([10; 32]),
            organ_adapter: None,
            cell_adapter: None,
            heads: Digest32::from_array([44; 32]),
            composition: Digest32::from_array([45; 32]),
            encoder: Digest32::from_array([3; 32]),
            tokenizer: Digest32::from_array([46; 32]),
            normalizer: Digest32::from_array([47; 32]),
            calibration: Digest32::from_array([48; 32]),
            numeric_profile: Digest32::from_array([49; 32]),
            output_schema: Digest32::from_array(fixture.config.manifest.output_schema),
            state_schema: Digest32::from_array(fixture.config.manifest.state_schema),
            state_semantics: Digest32::from_array([50; 32]),
        },
        training_lineage: None,
        rollback_predecessor: None,
    };
    fixture.config.manifest.bundle_digest = *checked(artifact.digest()).as_array();
    fixture.config.initial.manifest_digest = checked(fixture.config.manifest.digest());
    let capability = CellCapabilityContractV1 {
        type_id: checked(StableId::new("generator")),
        generation: generation(1),
        role: CellFunctionalRoleV1::ActionGeneration,
        input_schema_digest: Digest32::from_array(fixture.config.manifest.input_schema),
        output_schema_digest: Digest32::from_array(fixture.config.manifest.output_schema),
        state_schema_digest: Digest32::from_array(fixture.config.manifest.state_schema),
        behavior_contract_digest: Digest32::from_array([70; 32]),
    };
    (fixture, artifact, capability)
}

fn bind(
    bootstrap: NeuronGenerationRuntimeBootstrapV2,
    artifact: &CellCompatibilityBundleV1,
    capability: CellCapabilityContractV1,
    task_role: CellFunctionalRoleV1,
) -> Result<NeuronGenerationRuntimeBootstrapV2, CellOwnerPopulationErrorV2> {
    bootstrap.with_population(
        checked(StableId::new("generation-owner")),
        capability,
        artifact,
        task_role,
        CellPopulationLimitsV1 {
            max_types: 1,
            max_expert_versions: 1,
            max_instances: 2,
            max_active_instances: 1,
            max_reserved_state_bytes: 2 * (64 + 1024),
        },
    )
}

#[tokio::test]
async fn bootstrap_checks_real_artifact_and_role_before_any_service_contact() {
    let (fixture, artifact, capability) = population_fixture().await;
    for (stem, supplied_artifact, role, expected) in [
        (
            "wrong-role",
            artifact.clone(),
            CellFunctionalRoleV1::VerificationMetacognition,
            CellOwnerPopulationErrorV2::WrongRole,
        ),
        (
            "wrong-artifact",
            CellCompatibilityBundleV1 {
                artifact_id: checked(StableId::new("another-artifact")),
                ..artifact.clone()
            },
            CellFunctionalRoleV1::ActionGeneration,
            CellOwnerPopulationErrorV2::InvalidBinding,
        ),
    ] {
        let journal = fixture.journal_with(stem, fixture.config.clone());
        let path = fixture.directory.path().join(format!("{stem}-journal"));
        let before = checked(fs::read(&path));
        let (handle, bootstrap) = checked(neuron_generation_channel_v2(
            &fixture.identity,
            journal,
            fixture.control.clone(),
            fixture.clock(),
            /*capacity*/ 2,
        ));
        assert_eq!(
            bind(bootstrap, &supplied_artifact, capability.clone(), role).err(),
            Some(expected)
        );
        assert_eq!(
            handle.snapshot().await,
            Err(CellGenerationErrorV2::Unavailable)
        );
        assert_eq!(checked(fs::read(path)), before);
    }
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn bound_service_observes_actual_activity_and_keeps_admission_checks() {
    let (fixture, artifact, capability) = population_fixture().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 2,
    ));
    let bootstrap = checked(bind(
        bootstrap,
        &artifact,
        capability.clone(),
        CellFunctionalRoleV1::ActionGeneration,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime,
    ));
    let idle = checked(handle.population_observation().await).expect("bound owner");
    assert_eq!(&idle.registration().capability, &capability);
    assert_eq!(
        idle.registration().expert.parameter_bundle_digest,
        checked(artifact.digest())
    );
    assert!(!idle.is_active());
    let req = request("bound-step", checked(handle.snapshot().await));
    let receipt = checked(handle.step_with_population(req.clone(), Vec::new()).await);
    // The ordinary port sees the same committed operation without redispatch.
    assert_eq!(checked(handle.step(req).await), receipt);
    assert!(
        checked(handle.population_observation().await)
            .expect("outbox")
            .is_active()
    );
    let chunk = checked(handle.pending_output().await).expect("committed output");
    checked(handle.acknowledge(chunk, [71; 32], cost()).await);
    assert!(
        !checked(handle.population_observation().await)
            .expect("acknowledged")
            .is_active()
    );
    fixture.begin_drain();
    assert_eq!(
        handle
            .step_with_population(
                request("after-drain", checked(handle.snapshot().await)),
                Vec::new(),
            )
            .await,
        Err(CellGenerationErrorV2::Draining)
    );
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
}

#[tokio::test]
async fn unbound_service_rejects_population_step_and_preserves_legacy_step() {
    let fixture = Fixture::new().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 2,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime,
    ));
    assert_eq!(checked(handle.population_observation().await), None);
    let req = request("unbound", checked(handle.snapshot().await));
    assert_eq!(
        handle.step_with_population(req.clone(), Vec::new()).await,
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(checked(handle.pending_request().await), None);
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 0);
    checked(handle.step(req).await);
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
}

#[tokio::test]
async fn async_peer_observation_blocks_capacity_before_target_admission() {
    let (mut fixture, artifact, capability) = population_fixture().await;
    fixture
        .control
        .signals
        .lose_response
        .store(/*val*/ true, Ordering::SeqCst);
    let (peer, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 2,
    ));
    let bootstrap = checked(bind(
        bootstrap,
        &artifact,
        capability.clone(),
        CellFunctionalRoleV1::ActionGeneration,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime,
    ));
    assert_eq!(
        peer.step(request("unknown-peer", checked(peer.snapshot().await)))
            .await,
        Err(CellGenerationErrorV2::Unavailable)
    );
    let active = checked(peer.population_observation().await).expect("unknown peer");
    assert!(active.is_active());
    tasks.shutdown().await;
    drop(peer);
    // Keep the original peer journal unchanged and unresolved while opening a
    // second state slot under the same host. There is no concurrent scheduler.
    fixture.reopen_state().await;
    let mut target_config = fixture.config.clone();
    target_config.initial.scope.cell_id = "other-cell".into();
    let journal = fixture.journal_with("target", target_config);
    let path = fixture.directory.path().join("target-journal");
    let before = checked(fs::read(&path));
    let (target, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        journal,
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 2,
    ));
    let bootstrap = checked(bind(
        bootstrap,
        &artifact,
        capability,
        CellFunctionalRoleV1::ActionGeneration,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime,
    ));
    let req = request("blocked-target", checked(target.snapshot().await));
    assert_eq!(
        target
            .step_with_population(req.clone(), vec![active.clone(); 4_096])
            .await,
        Err(CellGenerationErrorV2::Capacity)
    );
    assert_eq!(
        target.step_with_population(req, vec![active]).await,
        Err(CellGenerationErrorV2::Capacity)
    );
    assert_eq!(checked(target.pending_request().await), None);
    assert_eq!(checked(fs::read(path)), before);
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
}
