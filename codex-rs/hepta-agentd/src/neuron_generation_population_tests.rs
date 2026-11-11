use codex_hepta_learning_artifacts::CellBundleComponentsV1;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_types::StableId;

use pretty_assertions::assert_eq;

use super::*;

fn artifact() -> CellCompatibilityBundleV1 {
    CellCompatibilityBundleV1 {
        artifact_id: checked(StableId::new("selected-generator")),
        generation: checked(Generation::new(1)),
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
            output_schema: Digest32::from_array([9; 32]),
            state_schema: Digest32::from_array([8; 32]),
            state_semantics: Digest32::from_array([50; 32]),
        },
        training_lineage: None,
        rollback_predecessor: None,
    }
}

fn limits() -> CellPopulationLimitsV1 {
    CellPopulationLimitsV1 {
        max_types: 1,
        max_expert_versions: 1,
        max_instances: 1,
        max_active_instances: 1,
        max_reserved_state_bytes: 320,
    }
}

fn bind(
    owner: &mut AgentdNeuronGenerationOwnerV2<FileAnchorWitnessStore, Model>,
    artifact: &CellCompatibilityBundleV1,
    task_role: CellFunctionalRoleV1,
    capacity: CellPopulationLimitsV1,
) -> Result<(), CellOwnerPopulationErrorV2> {
    let manifest = owner.journal().manifest();
    let capability = CellCapabilityContractV1 {
        type_id: checked(StableId::new("generator")),
        generation: checked(Generation::new(1)),
        role: CellFunctionalRoleV1::ActionGeneration,
        input_schema_digest: Digest32::from_array(manifest.input_schema),
        output_schema_digest: Digest32::from_array(manifest.output_schema),
        state_schema_digest: Digest32::from_array(manifest.state_schema),
        behavior_contract_digest: Digest32::from_array([70; 32]),
    };
    owner.bind_population(
        checked(StableId::new("generation-owner")),
        capability,
        artifact,
        task_role,
        capacity,
    )
}

#[test]
fn artifact_and_role_mismatch_cannot_register_or_dispatch() {
    let fixture = Fixture::new();
    let artifact = artifact();
    let model = Model::default();
    let mut owner = fixture.owner_with_bundle(model.clone(), Some(&artifact));
    let mut wrong = artifact.clone();
    wrong.components.base = Digest32::from_array([99; 32]);
    assert_eq!(
        bind(
            &mut owner,
            &wrong,
            CellFunctionalRoleV1::ActionGeneration,
            limits()
        ),
        Err(CellOwnerPopulationErrorV2::InvalidBinding)
    );
    assert_eq!(
        bind(
            &mut owner,
            &artifact,
            CellFunctionalRoleV1::VerificationMetacognition,
            limits()
        ),
        Err(CellOwnerPopulationErrorV2::WrongRole)
    );
    assert_eq!(checked(owner.population_observation()), None);
    assert_eq!(checked(owner.journal().pending_request()), None);
    assert_eq!(model.calls.load(Ordering::SeqCst), 0);
}

#[test]
fn artifact_derived_reservation_enforces_capacity() {
    let fixture = Fixture::new();
    let artifact = artifact();
    let mut owner = fixture.owner_with_bundle(Model::default(), Some(&artifact));
    let mut capacity = limits();
    capacity.max_reserved_state_bytes = 319;
    assert_eq!(
        bind(
            &mut owner,
            &artifact,
            CellFunctionalRoleV1::ActionGeneration,
            capacity
        ),
        Err(CellOwnerPopulationErrorV2::Population(
            CellPopulationErrorV1::CapacityExceeded("reserved state bytes")
        ))
    );
    assert_eq!(checked(owner.journal().pending_request()), None);
}

#[test]
fn fresh_population_check_blocks_drained_owner_before_contact() {
    let fixture = Fixture::new();
    let artifact = artifact();
    let model = Model::default();
    let mut owner = fixture.owner_with_bundle(model.clone(), Some(&artifact));
    checked(bind(
        &mut owner,
        &artifact,
        CellFunctionalRoleV1::ActionGeneration,
        limits(),
    ));
    let req = request(&owner);
    checked(owner.journal_mut().drain());
    let before = checked(fs::read(fixture.0.join("journal")));
    assert_eq!(
        owner.step(req, || 11),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(checked(fs::read(fixture.0.join("journal"))), before);
    assert_eq!(model.calls.load(Ordering::SeqCst), 0);
}

#[test]
fn bound_population_reopens_and_reconciles_original_computation() {
    let fixture = Fixture::new();
    let artifact = artifact();
    let model = Model {
        lose_response: true,
        ..Model::default()
    };
    let mut owner = fixture.owner_with_bundle(model.clone(), Some(&artifact));
    checked(bind(
        &mut owner,
        &artifact,
        CellFunctionalRoleV1::ActionGeneration,
        limits(),
    ));
    let observed = checked(owner.population_observation()).expect("bound population");
    assert_eq!(
        observed.registration().expert.shared_base_digest,
        artifact.components.base
    );
    assert_eq!(
        observed.registration().expert.parameter_bundle_digest,
        checked(artifact.digest())
    );
    let req = request(&owner);
    assert_eq!(
        owner.step(req.clone(), || 11),
        Err(CellGenerationErrorV2::Unavailable)
    );
    assert!(
        checked(owner.population_observation())
            .expect("bound population")
            .is_active()
    );
    drop(owner);
    let mut owner = fixture.owner_with_bundle(model.clone(), Some(&artifact));
    checked(bind(
        &mut owner,
        &artifact,
        CellFunctionalRoleV1::ActionGeneration,
        limits(),
    ));
    let receipt = checked(owner.step(req.clone(), || 20));
    assert_eq!(checked(owner.step(req, || 21)), receipt);
    assert_eq!(model.calls.load(Ordering::SeqCst), 1);
    assert!(
        checked(owner.population_observation())
            .expect("pending output")
            .is_active()
    );
}

#[test]
fn another_owners_unknown_work_blocks_new_task_before_journal_or_dispatch() {
    let artifact = artifact();
    let first_fixture = Fixture::new();
    let mut first = first_fixture.owner_with_bundle(
        Model {
            lose_response: true,
            ..Model::default()
        },
        Some(&artifact),
    );
    checked(bind(
        &mut first,
        &artifact,
        CellFunctionalRoleV1::ActionGeneration,
        limits(),
    ));
    let first_request = request(&first);
    assert_eq!(
        first.step(first_request, || 11),
        Err(CellGenerationErrorV2::Unavailable)
    );
    let active = checked(first.population_observation()).expect("bound population");
    let second_fixture = Fixture::new();
    let model = Model::default();
    let mut second = second_fixture.owner_with_cell(model.clone(), Some(&artifact), "other-cell");
    let mut capacity = limits();
    capacity.max_instances = 2;
    capacity.max_reserved_state_bytes = 640;
    checked(bind(
        &mut second,
        &artifact,
        CellFunctionalRoleV1::ActionGeneration,
        capacity,
    ));
    let req = request(&second);
    let before = checked(fs::read(second_fixture.0.join("journal")));
    assert_eq!(
        second.step_with_population(req, &[active], || 11),
        Err(CellGenerationErrorV2::Capacity)
    );
    assert_eq!(checked(fs::read(second_fixture.0.join("journal"))), before);
    assert_eq!(checked(second.journal().pending_request()), None);
    assert_eq!(model.calls.load(Ordering::SeqCst), 0);
}
