use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::*;
use crate::CellBackendManifestV2;
use crate::CellGenerationConfigV2;
use crate::CellGenerationScopeV2;
use crate::CellRuntimeSnapshotV2;
use crate::FileAnchorWitnessStore;
use crate::JournalScope;
use crate::cell_test_support::checked;
use crate::cell_test_support::d;
use crate::cell_test_support::id;

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-owner-population-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&path));
        Self(path)
    }
    fn file(&self, name: &str) -> File {
        checked(
            OpenOptions::new()
                .create(true)
                .truncate(false)
                .read(true)
                .write(true)
                .open(self.0.join(name)),
        )
    }
    fn open(
        &self,
        configuration: CellGenerationConfigV2,
    ) -> CellGenerationJournalV2<FileAnchorWitnessStore> {
        let witness = checked(FileAnchorWitnessStore::open(
            self.file("witness"),
            JournalScope {
                scope_digest: d("scope"),
                objective_digest: d("objective"),
            },
            checked(Generation::new(1)),
            /*max_records*/ 4096,
        ));
        checked(CellGenerationJournalV2::open(
            self.file("journal"),
            witness,
            configuration,
            /*max_records*/ 128,
        ))
    }
    fn bytes(&self) -> Vec<u8> {
        checked(fs::read(self.0.join("journal")))
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn config() -> CellGenerationConfigV2 {
    let manifest = CellBackendManifestV2 {
        profile: "qualification-generation".to_string(),
        source_digest: [1; 32],
        bundle_digest: [2; 32],
        encoder: Some([3; 32]),
        head: None,
        memory: None,
        world_model: Some([4; 32]),
        decoder: Some([5; 32]),
        runtime_digest: [6; 32],
        device_digest: [7; 32],
        input_schema: [8; 32],
        state_schema: [9; 32],
        output_schema: [10; 32],
        learning: CellLearningBindingV2::Resumable {
            weights: [11; 32],
            optimizer: [12; 32],
            rng: [13; 32],
            sampler: [14; 32],
            training_cursor: [15; 32],
        },
        evolution: CellEvolutionBindingV2 {
            structure: [16; 32],
            lineage: [17; 32],
            source_dependencies: [18; 32],
            adoption_receipt: [19; 32],
        },
        max_input_bytes: 256,
        max_state_bytes: 256,
        max_delta_bytes: 256,
        max_prefix_bytes: 1024,
        max_step_cost_entries: 32,
        max_ack_cost_entries: 16,
    };
    let initial = CellRuntimeSnapshotV2 {
        scope: CellGenerationScopeV2 {
            principal_digest: [20; 32],
            agent_id: "agent".to_string(),
            cell_id: "cell".to_string(),
            run_id: "run".to_string(),
        },
        manifest_digest: checked(manifest.digest()),
        generation: 1,
        writer_epoch: 1,
        revision: 0,
        state: vec![1],
        prefix: Vec::new(),
        stopped: false,
    };
    CellGenerationConfigV2 {
        manifest,
        initial,
        source_frontier: [21; 32],
        task_digest: [22; 32],
    }
}

fn registration(manifest: &CellBackendManifestV2) -> CellOwnerRegistrationV2 {
    let capability = CellCapabilityContractV1 {
        type_id: id("generation-type"),
        generation: checked(Generation::new(1)),
        role: CellFunctionalRoleV1::ActionGeneration,
        input_schema_digest: Digest32::from_array(manifest.input_schema),
        output_schema_digest: Digest32::from_array(manifest.output_schema),
        state_schema_digest: Digest32::from_array(manifest.state_schema),
        behavior_contract_digest: d("generation-behavior"),
    };
    let expert = CellExpertVersionV1 {
        version_id: id("generation-version"),
        type_id: capability.type_id.clone(),
        capability_digest: checked(capability.digest()),
        shared_base_digest: d("shared-base"),
        parameter_bundle_digest: Digest32::from_array(manifest.bundle_digest),
    };
    CellOwnerRegistrationV2 { capability, expert }
}
fn limits() -> CellPopulationLimitsV1 {
    CellPopulationLimitsV1 {
        max_types: 8,
        max_expert_versions: 8,
        max_instances: 8,
        max_active_instances: 2,
        max_reserved_state_bytes: 20_000,
    }
}
fn observe(
    owner: &CellGenerationJournalV2<FileAnchorWitnessStore>,
) -> CellOwnerPopulationObservationV2 {
    checked(CellOwnerPopulationObservationV2::observe_generation(
        owner,
        id("generation-owner"),
        registration(owner.manifest()),
    ))
}
fn request(
    owner: &CellGenerationJournalV2<FileAnchorWitnessStore>,
    operation: &str,
) -> CellGenerationRequestV2 {
    CellGenerationRequestV2 {
        operation_id: operation.to_string(),
        task_digest: [22; 32],
        source_frontier: [21; 32],
        predecessor: checked(owner.snapshot()).clone(),
        input: vec![2],
        admitted_at_micros: 10,
        deadline_micros: 100,
    }
}

#[test]
fn generation_population_uses_actual_manifest_scope_checkpoint_and_reservation() {
    let fixture = Fixture::new();
    let owner = fixture.open(config());
    let observed = observe(&owner);
    let actual = checked(owner.snapshot());
    assert_eq!(
        observed.identity(),
        &CellOwnerIdentityV2 {
            scope: CellScopeV1 {
                principal_digest: Digest32::from_array(actual.scope.principal_digest),
                agent_id: id(&actual.scope.agent_id),
                cell_id: id(&actual.scope.cell_id),
                run_id: id(&actual.scope.run_id)
            },
            generation: checked(Generation::new(actual.generation)),
            writer_epoch: actual.writer_epoch,
            revision: actual.revision,
            runtime_binding_digest: Digest32::from_array(actual.manifest_digest),
            parameter_digest: Digest32::from_array([11; 32]),
            source_frontier: Digest32::from_array([21; 32]),
            checkpoint_digest: Digest32::from_array(checked(actual.digest())),
            learning: Some(owner.manifest().learning.clone()),
            evolution: Some(owner.manifest().evolution.clone()),
        }
    );
    assert_eq!(observed.instance().reserved_state_bytes, 1280);
    assert!(!observed.is_active());
}

#[test]
fn mismatched_parameter_bundle_or_schema_cannot_enter_population() {
    let fixture = Fixture::new();
    let owner = fixture.open(config());
    let mut wrong = registration(owner.manifest());
    wrong.expert.parameter_bundle_digest = d("another-backend");
    assert_eq!(
        CellOwnerPopulationObservationV2::observe_generation(&owner, id("owner"), wrong),
        Err(CellOwnerPopulationErrorV2::InvalidBinding)
    );
    let mut wrong = registration(owner.manifest());
    wrong.capability.input_schema_digest = d("another-input-port");
    wrong.expert.capability_digest = checked(wrong.capability.digest());
    assert_eq!(
        CellOwnerPopulationObservationV2::observe_generation(&owner, id("owner"), wrong),
        Err(CellOwnerPopulationErrorV2::InvalidBinding)
    );
}

#[test]
fn wrong_task_role_rejects_before_admission_or_journal_write() {
    let fixture = Fixture::new();
    let mut owner = fixture.open(config());
    let observed = observe(&owner);
    let work = request(&owner, "wrong-role");
    let before = fixture.bytes();
    assert_eq!(
        admit_generation_with_population_v2(
            &mut owner,
            &observed,
            &[],
            limits(),
            CellFunctionalRoleV1::VerificationMetacognition,
            work,
            10
        ),
        Err(CellOwnerPopulationErrorV2::WrongRole)
    );
    assert_eq!(fixture.bytes(), before);
    assert_eq!(checked(owner.pending_request()), None);
}

#[test]
fn unknown_inflight_work_retains_capacity_after_cancel_drain_and_reopen() {
    let first_fixture = Fixture::new();
    let mut first = first_fixture.open(config());
    let work = request(&first, "unknown");
    checked(first.admit(work.clone(), 10));
    checked(first.cancel(checked(work.digest())));
    checked(first.drain());
    drop(first);
    let first = first_fixture.open(config());
    let active = observe(&first);
    assert!(active.is_active());
    let census = checked(cell_owner_population_census_v2(
        std::slice::from_ref(&active),
        limits(),
    ));
    assert_eq!(
        (
            census.instance_count,
            census.active_instance_count,
            census.reserved_state_bytes
        ),
        (1, 1, 1280)
    );
    let second_fixture = Fixture::new();
    let mut second_config = config();
    second_config.initial.scope.cell_id = "other-cell".to_string();
    let mut second = second_fixture.open(second_config);
    let observed = observe(&second);
    let work = request(&second, "must-wait");
    let before = second_fixture.bytes();
    let mut capacity = limits();
    capacity.max_active_instances = 1;
    assert_eq!(
        admit_generation_with_population_v2(
            &mut second,
            &observed,
            &[active],
            capacity,
            CellFunctionalRoleV1::ActionGeneration,
            work,
            10
        ),
        Err(CellOwnerPopulationErrorV2::Population(
            CellPopulationErrorV1::CapacityExceeded("active instances")
        ))
    );
    assert_eq!(second_fixture.bytes(), before);
    assert_eq!(checked(second.pending_request()), None);
}

#[test]
fn owner_activity_change_invalidates_an_earlier_admission_observation() {
    let fixture = Fixture::new();
    let mut owner = fixture.open(config());
    let observed = observe(&owner);
    let work = request(&owner, "unknown");
    checked(owner.admit(work.clone(), 10));
    assert_eq!(
        admit_generation_with_population_v2(
            &mut owner,
            &observed,
            &[],
            limits(),
            CellFunctionalRoleV1::ActionGeneration,
            work,
            10
        ),
        Err(CellOwnerPopulationErrorV2::StaleOwner)
    );
}

#[test]
fn decision_and_generation_share_cell_slot_without_claiming_shared_learning() {
    let decision = crate::cell_test_support::owner(&["run"]);
    let definition = crate::cell_test_support::definition();
    let scope = crate::cell_test_support::scope("run");
    let mut reg = registration(&config().manifest);
    reg.capability.type_id = id("decision-type");
    reg.capability.role = CellFunctionalRoleV1::DecisionCoordination;
    reg.capability.input_schema_digest = cell_decision_input_schema_v2();
    reg.capability.output_schema_digest = cell_decision_output_schema_v2();
    reg.capability.state_schema_digest = definition.state_schema_digest;
    reg.expert.version_id = id("decision-version");
    reg.expert.type_id = reg.capability.type_id.clone();
    reg.expert.capability_digest = checked(reg.capability.digest());
    reg.expert.parameter_bundle_digest = definition.bundle_digest;
    let first = checked(CellOwnerPopulationObservationV2::observe_decision(
        &decision,
        id("decision-owner"),
        &scope,
        &definition,
        reg,
    ));
    assert_eq!(
        (&first.identity().learning, &first.identity().evolution),
        (&None, &None)
    );
    let fixture = Fixture::new();
    let mut configuration = config();
    configuration.initial.scope = CellGenerationScopeV2 {
        principal_digest: scope.principal_digest.into_array(),
        agent_id: scope.agent_id.as_str().to_string(),
        cell_id: scope.cell_id.as_str().to_string(),
        run_id: scope.run_id.as_str().to_string(),
    };
    let second = observe(&fixture.open(configuration));
    assert_eq!(
        &first.instance().state_slot_id,
        &second.instance().state_slot_id
    );
    assert_eq!(
        cell_owner_population_census_v2(&[first.clone(), second], limits()),
        Err(CellOwnerPopulationErrorV2::Population(
            CellPopulationErrorV1::DuplicateInstance(first.instance().instance_id.clone())
        ))
    );
}

#[test]
fn population_scope_does_not_alias_different_agent_run_boundaries() {
    let first_fixture = Fixture::new();
    let mut first = config();
    first.initial.scope.agent_id = "ab".to_string();
    first.initial.scope.run_id = "c".to_string();
    let first = observe(&first_fixture.open(first));
    let second_fixture = Fixture::new();
    let mut second = config();
    second.initial.scope.agent_id = "a".to_string();
    second.initial.scope.run_id = "bc".to_string();
    let second = observe(&second_fixture.open(second));
    assert_ne!(
        first.instance().scope_digest,
        second.instance().scope_digest
    );
}
