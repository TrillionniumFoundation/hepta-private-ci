use super::*;
use crate::CellCapabilityContractV1;
use crate::CellFeatureProjectionBindingV1;
use crate::CellFunctionalRoleV1;
use crate::CellPartitionOwnerV1;
use crate::NeuronModelError;
use crate::PreparedCellStepV1;
use crate::cell_test_support::RecordedControl;
use crate::cell_test_support::checked;
use crate::cell_test_support::d;
use crate::cell_test_support::definition;
use crate::cell_test_support::id;
use crate::cell_test_support::input;
use crate::cell_test_support::scope;
use crate::commit_cell_step;
use crate::decide_cell;
use crate::infer_cell;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

// Independent Python-canonical receipt; the runtime control below is a fixture,
// not a deployed Granite, EG2, Memory V13 or semantic seven-role backend.
const PYTHON_RECEIPT: &str = r#"{"authority":"DENY_ALL","conversion_sha256":"b4411703c9b8794c3a807caf119f10ea741aa62f81c957404ca75b4f6ec0ad84","feature_vector_q24":[16777216,8388608],"legacy_head_parity_qualified":false,"numeric_profile":"signed-q24-nearest-ties-even-v1","row":0,"schema":"hepta.feature-global-q24-conversion.v1","source_bundle_sha256":"69254f58858d38e25d1294190830d812f68d1c98a702aa8afd85c7d73c5189b9","source_record_digest":"70ce871f8a3d3fb449bc3c3ace6547cef02dfc74ffe48d912532a724bfdbe5b9"}"#;

fn projection() -> CellGlobalFeatureProjectionV1 {
    checked(CellGlobalFeatureProjectionV1::from_json(
        PYTHON_RECEIPT.as_bytes(),
        CellFeatureProjectionBindingV1 {
            scope_digest: scope("run1").digest(),
            source_frontier: d("frontier"),
            encoder_digest: d("encoder"),
            source_bundle_digest: d("bundle-source"),
            source_record_digest: d("record"),
            conversion_digest: checked(
                "b4411703c9b8794c3a807caf119f10ea741aa62f81c957404ca75b4f6ec0ad84".parse(),
            ),
            row: 0,
            width: 2,
        },
    ))
}

fn registration() -> CellBackendRegistrationV1 {
    let mut definition = definition();
    definition.max_input_bytes = 4096;
    let capability = CellCapabilityContractV1 {
        type_id: id("typed-memory-association"),
        generation: checked(Generation::new(/*value*/ 7)),
        role: CellFunctionalRoleV1::MemoryAssociation,
        input_schema_digest: checked(cell_global_feature_schema_digest_v1(/*width*/ 2)),
        output_schema_digest: cell_native_decision_schema_digest_v1(),
        state_schema_digest: definition.state_schema_digest,
        behavior_contract_digest: d("memory-behavior"),
    };
    let expert = CellExpertVersionV1 {
        version_id: id("expert-v1"),
        type_id: capability.type_id.clone(),
        capability_digest: checked(capability.digest()),
        shared_base_digest: d("shared-base"),
        parameter_bundle_digest: definition.bundle_digest,
    };
    CellBackendRegistrationV1 {
        backend_id: id("backend"),
        family: CellBackendFamilyV1::FrozenRepresentationPrivateHead,
        capability,
        expert,
        definition,
    }
}

fn owner(registration: &CellBackendRegistrationV1) -> CellPartitionOwnerV1 {
    let mut owner = checked(CellPartitionOwnerV1::new(
        /*max_partitions*/ 1, /*max_receipts_per_partition*/ 8,
    ));
    checked(owner.admit(
        scope("run1"),
        &registration.definition,
        d("frontier"),
        /*writer_epoch*/ 1,
    ));
    owner
}

fn request(projection: &CellGlobalFeatureProjectionV1) -> CellStepInputV1 {
    let mut request = input("run1");
    request.observation = projection.observation_bytes().to_vec();
    request
}

fn ready(entry: CellStepEntryV1) -> PreparedCellStepV1 {
    match entry {
        CellStepEntryV1::Ready(prepared) => *prepared,
        CellStepEntryV1::Replayed(_) => panic!("expected a fresh proposal"),
    }
}

#[test]
fn each_family_uses_the_native_owner_pipeline_and_replays_exactly_once() {
    for family in [
        CellBackendFamilyV1::FrozenRepresentationPrivateHead,
        CellBackendFamilyV1::GenerativeAdapterState,
        CellBackendFamilyV1::TrainableStateModel,
    ] {
        let mut registration = registration();
        registration.family = family;
        let digest = checked(registration.digest());
        let mut owner = owner(&registration);
        let registry = checked(CellBackendRegistryV1::new(
            vec![registration.clone()],
            /*max_backends*/ 1,
        ));
        let backend = checked(registry.resolve(&registration.backend_id, digest));
        let projection = projection();
        let before = checked(owner.snapshot(&scope("run1")));
        let prepared = ready(checked(backend.enter(
            &owner,
            &projection,
            request(&projection),
            /*now_micros*/ 10,
        )));
        assert_eq!(
            prepared.model_request.feature_vector_q24,
            vec![1 << 24, 1 << 23]
        );
        assert_eq!(checked(owner.snapshot(&scope("run1"))), before);
        let mut control = RecordedControl::new();
        let inferred = checked(infer_cell(
            prepared,
            &mut owner,
            &mut control,
            /*now_micros*/ 11,
        ));
        let proposal = checked(decide_cell(inferred, /*now_micros*/ 12));
        let receipt = checked(commit_cell_step(
            &mut owner, proposal, /*now_micros*/ 13,
        ));
        assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
        assert_eq!(
            receipt.cost.consumed_input_bytes,
            PREFIX.len() + 32 + PYTHON_RECEIPT.len()
        );
        assert_eq!(receipt.cost.truncated_input_bytes, 0);
        match checked(backend.enter(
            &owner,
            &projection,
            request(&projection),
            /*now_micros*/ 101,
        )) {
            CellStepEntryV1::Replayed(replayed) => assert_eq!(*replayed, receipt),
            CellStepEntryV1::Ready(_) => panic!("a committed operation must not create new work"),
        }
        assert_eq!((control.executions, control.reads), (1, 0));
    }
}

#[test]
fn registry_requires_matching_contract_expert_bundle_and_native_schemas() {
    for index in 0..7 {
        let mut registration = registration();
        match index {
            0 => registration.expert.type_id = id("other-type"),
            1 => registration.expert.capability_digest = d("other-capability"),
            2 => registration.expert.shared_base_digest = Digest32::ZERO,
            3 => registration.expert.parameter_bundle_digest = d("other-bundle"),
            4 => registration.capability.state_schema_digest = d("other-state"),
            5 => registration.capability.input_schema_digest = d("full-tensor-bundle"),
            6 => registration.capability.output_schema_digest = d("generated-media"),
            _ => unreachable!("fixture index"),
        }
        if index >= 4 {
            registration.expert.capability_digest = checked(registration.capability.digest());
        }
        assert!(matches!(
            CellBackendRegistryV1::new(vec![registration], /*max_backends*/ 1),
            Err(CellExecutionError::IncompatibleBundle)
        ));
    }
}

#[test]
fn lookup_requires_an_exact_pin_and_registry_does_not_accept_duplicate_names() {
    let registration = registration();
    let digest = checked(registration.digest());
    let registry = checked(CellBackendRegistryV1::new(
        vec![registration.clone()],
        /*max_backends*/ 1,
    ));
    assert_eq!(
        checked(registry.resolve(&registration.backend_id, digest)).registration(),
        &registration
    );
    assert_eq!(
        registry.resolve(&registration.backend_id, d("stale-registration")),
        Err(CellExecutionError::IncompatibleBundle)
    );
    assert_eq!(
        registry.resolve(&id("missing"), digest),
        Err(CellExecutionError::IncompatibleBundle)
    );
    assert!(matches!(
        CellBackendRegistryV1::new(
            vec![registration.clone(), registration.clone()],
            /*max_backends*/ 2
        ),
        Err(CellExecutionError::InvalidDefinition)
    ));
    assert!(matches!(
        CellBackendRegistryV1::new(
            vec![registration.clone(), registration.clone()],
            /*max_backends*/ 1
        ),
        Err(CellExecutionError::CapacityExceeded)
    ));
    assert!(matches!(
        CellBackendRegistryV1::new(vec![registration], /*max_backends*/ 0),
        Err(CellExecutionError::CapacityExceeded)
    ));
}

#[test]
fn reclassifying_family_role_or_expert_cannot_reinterpret_a_committed_decision() {
    let registration = registration();
    let mut owner = owner(&registration);
    let registry = checked(CellBackendRegistryV1::new(
        vec![registration.clone()],
        /*max_backends*/ 1,
    ));
    let backend =
        checked(registry.resolve(&registration.backend_id, checked(registration.digest())));
    let projection = projection();
    let mut control = RecordedControl::new();
    let prepared = ready(checked(backend.enter(
        &owner,
        &projection,
        request(&projection),
        /*now_micros*/ 10,
    )));
    let inferred = checked(infer_cell(
        prepared,
        &mut owner,
        &mut control,
        /*now_micros*/ 11,
    ));
    let proposal = checked(decide_cell(inferred, /*now_micros*/ 12));
    checked(commit_cell_step(
        &mut owner, proposal, /*now_micros*/ 13,
    ));
    for index in 0..3 {
        let mut changed = registration.clone();
        match index {
            0 => changed.family = CellBackendFamilyV1::TrainableStateModel,
            1 => {
                changed.capability.role = CellFunctionalRoleV1::VerificationMetacognition;
                changed.expert.capability_digest = checked(changed.capability.digest());
            }
            2 => changed.expert.version_id = id("renamed-expert"),
            _ => unreachable!("fixture index"),
        }
        let registry = checked(CellBackendRegistryV1::new(
            vec![changed.clone()],
            /*max_backends*/ 1,
        ));
        let backend = checked(registry.resolve(&changed.backend_id, checked(changed.digest())));
        assert!(matches!(
            backend.enter(
                &owner,
                &projection,
                request(&projection),
                /*now_micros*/ 14
            ),
            Err(CellExecutionError::OperationConflict)
        ));
    }
    assert_eq!((control.executions, control.reads), (1, 0));
}

#[test]
fn unknown_dispatch_recovers_only_the_original_registered_request() {
    let registration = registration();
    let mut owner = owner(&registration);
    let registry = checked(CellBackendRegistryV1::new(
        vec![registration.clone()],
        /*max_backends*/ 1,
    ));
    let backend =
        checked(registry.resolve(&registration.backend_id, checked(registration.digest())));
    let projection = projection();
    let prepared = ready(checked(backend.enter(
        &owner,
        &projection,
        request(&projection),
        /*now_micros*/ 10,
    )));
    let mut control = RecordedControl::new();
    control.failure = Some(NeuronModelError::Indeterminate);
    assert!(matches!(
        infer_cell(prepared, &mut owner, &mut control, /*now_micros*/ 11),
        Err(CellExecutionError::Backend(NeuronModelError::Indeterminate))
    ));
    let pending = checked(owner.pending_inference(&scope("run1")));
    assert!(matches!(
        backend.enter(
            &owner,
            &projection,
            request(&projection),
            /*now_micros*/ 12
        ),
        Err(CellExecutionError::InferencePending)
    ));
    let mut changed = registration.clone();
    changed.family = CellBackendFamilyV1::GenerativeAdapterState;
    let changed_registry = checked(CellBackendRegistryV1::new(
        vec![changed.clone()],
        /*max_backends*/ 1,
    ));
    let changed_backend =
        checked(changed_registry.resolve(&changed.backend_id, checked(changed.digest())));
    assert!(matches!(
        changed_backend.recover(
            &owner,
            &projection,
            request(&projection),
            &mut control,
            /*now_micros*/ 12
        ),
        Err(CellExecutionError::OperationConflict)
    ));
    assert_eq!((control.executions, control.reads), (1, 0));
    let receipt = control.receipt.take();
    assert!(matches!(
        backend.recover(
            &owner,
            &projection,
            request(&projection),
            &mut control,
            /*now_micros*/ 12
        ),
        Err(CellExecutionError::InferencePending)
    ));
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), pending);
    control.receipt = receipt;
    let inferred = checked(backend.recover(
        &owner,
        &projection,
        request(&projection),
        &mut control,
        /*now_micros*/ 101,
    ));
    let proposal = checked(decide_cell(inferred, /*now_micros*/ 102));
    let receipt = checked(commit_cell_step(
        &mut owner, proposal, /*now_micros*/ 103,
    ));
    assert_eq!(receipt.selected_candidate, id("abstain"));
    assert!(receipt.deadline_exceeded);
    assert_eq!(receipt.cost.model_latency_micros, 20);
    assert_eq!((control.executions, control.reads), (1, 2));
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
}

#[test]
fn current_source_invalidation_blocks_replay_of_registered_results() {
    let registration = registration();
    let mut owner = owner(&registration);
    let registry = checked(CellBackendRegistryV1::new(
        vec![registration.clone()],
        /*max_backends*/ 1,
    ));
    let backend =
        checked(registry.resolve(&registration.backend_id, checked(registration.digest())));
    let projection = projection();
    let prepared = ready(checked(backend.enter(
        &owner,
        &projection,
        request(&projection),
        /*now_micros*/ 10,
    )));
    let mut control = RecordedControl::new();
    let inferred = checked(infer_cell(
        prepared,
        &mut owner,
        &mut control,
        /*now_micros*/ 11,
    ));
    let proposal = checked(decide_cell(inferred, /*now_micros*/ 12));
    checked(commit_cell_step(
        &mut owner, proposal, /*now_micros*/ 13,
    ));
    checked(owner.reset_at_frontier(
        &scope("run1"),
        d("deleted-source-frontier"),
        /*writer_epoch*/ 2,
    ));
    assert!(matches!(
        backend.enter(
            &owner,
            &projection,
            request(&projection),
            /*now_micros*/ 14
        ),
        Err(CellExecutionError::StaleSource)
    ));
    assert_eq!((control.executions, control.reads), (1, 0));
}

#[test]
fn registration_prefix_is_charged_against_the_existing_input_limit() {
    let mut registration = registration();
    registration.definition.max_input_bytes = PYTHON_RECEIPT.len();
    let owner = owner(&registration);
    let before = checked(owner.snapshot(&scope("run1")));
    let registry = checked(CellBackendRegistryV1::new(
        vec![registration.clone()],
        /*max_backends*/ 1,
    ));
    let backend =
        checked(registry.resolve(&registration.backend_id, checked(registration.digest())));
    let projection = projection();
    assert!(matches!(
        backend.enter(
            &owner,
            &projection,
            request(&projection),
            /*now_micros*/ 10
        ),
        Err(CellExecutionError::CapacityExceeded)
    ));
    assert_eq!(checked(owner.snapshot(&scope("run1"))), before);
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
}
