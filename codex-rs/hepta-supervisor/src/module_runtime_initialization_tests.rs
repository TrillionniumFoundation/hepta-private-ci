//! Initialization follows all ABI obligations, not only the state-class label.

use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use pretty_assertions::assert_eq;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn abi(state_class: RuntimeModuleStateClassV1) -> RuntimeModuleAbiV1 {
    RuntimeModuleAbiV1 {
        module_id: id("new.module"),
        owner_id: id("module.owner"),
        generation: Generation::new(1).expect("generation"),
        implementation_digest: digest("implementation"),
        candidate_artifact_digest: digest("candidate"),
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class,
        dependencies: Vec::new(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: Default::default(),
        effect_scope: Default::default(),
    }
}

fn witness() -> RuntimeModuleInitializationWitnessV1 {
    RuntimeModuleInitializationWitnessV1 {
        initial_state_digest: digest("owner-initial-state"),
        readiness_digest: digest("owner-readiness"),
    }
}

fn admit(supervisor: &mut RuntimeModuleSupervisorV1, candidate: &RuntimeModuleAbiV1) {
    supervisor
        .register_shadow_for_test(candidate.clone(), digest("selection"))
        .expect("isolated selected-shadow fixture");
    supervisor
        .enter_canary(&candidate.module_id, candidate.generation)
        .expect("canary");
}

fn assert_initialized(candidate: RuntimeModuleAbiV1) {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    admit(&mut supervisor, &candidate);
    let before = supervisor.registry.checkpoint();
    assert_eq!(
        supervisor.promote_stateless(&candidate.module_id, candidate.generation, digest("canary"),),
        Err(RuntimeModuleRegistryError::MissingWriterHandoff.into())
    );
    assert_eq!(supervisor.registry.checkpoint(), before);
    let snapshot = supervisor
        .promote_new_initialized_module(
            &candidate.module_id,
            candidate.generation,
            digest("canary"),
            witness(),
        )
        .expect("all state, writer and effect obligations admit initialization");
    assert_eq!(snapshot.active.len(), 1);
    let record = supervisor
        .registry
        .record(&candidate.module_id, candidate.generation)
        .expect("published record");
    let mut initialization_bytes = b"hepta.runtime-module-initialization.v1".to_vec();
    initialization_bytes.extend_from_slice(witness().initial_state_digest.as_array());
    initialization_bytes.extend_from_slice(witness().readiness_digest.as_array());
    assert_eq!(
        record,
        &codex_hepta_control_plane::RuntimeModuleRecordV1 {
            abi: candidate,
            lifecycle: RuntimeModuleLifecycleV1::Active,
            selection_digest: Some(digest("selection")),
            canary_digest: Some(digest("canary")),
            handoff_digest: Some(Digest32::of_bytes(&initialization_bytes)),
        }
    );
    let checkpoint = supervisor.registry.checkpoint();
    let restored = RuntimeModuleRegistryV1::restore_checkpoint_bytes(
        &supervisor.registry.checkpoint_bytes(),
        checkpoint.checkpoint_digest,
    )
    .expect("canonical checkpoint retains initialized obligations");
    assert_eq!(restored.checkpoint(), checkpoint);
    assert_eq!(restored.snapshot(), snapshot);
}

#[test]
fn stateless_domain_owner_has_an_initialized_admission_path() {
    let mut candidate = abi(RuntimeModuleStateClassV1::Stateless);
    candidate.authoritative_domains.insert(id("owned.data"));
    assert_initialized(candidate);
}

#[test]
fn stateless_effect_adapter_has_an_initialized_admission_path() {
    let mut candidate = abi(RuntimeModuleStateClassV1::Stateless);
    candidate.effect_scope.insert(id("external.effect"));
    assert_initialized(candidate);
}

#[test]
fn stateless_writer_and_effect_adapter_has_an_initialized_admission_path() {
    let mut candidate = abi(RuntimeModuleStateClassV1::Stateless);
    candidate.authoritative_domains.insert(id("owned.data"));
    candidate.effect_scope.insert(id("external.effect"));
    assert_initialized(candidate);
}

#[test]
fn local_and_external_state_still_require_initialization() {
    for state_class in [
        RuntimeModuleStateClassV1::Stateful,
        RuntimeModuleStateClassV1::ExternalStateful,
    ] {
        assert_initialized(abi(state_class));
    }
}

#[test]
fn pure_stateless_module_keeps_the_witness_free_promotion_path() {
    let candidate = abi(RuntimeModuleStateClassV1::Stateless);
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    admit(&mut supervisor, &candidate);
    supervisor
        .promote_stateless(&candidate.module_id, candidate.generation, digest("canary"))
        .expect("stateless promotion");
    assert_eq!(
        supervisor
            .registry
            .record(&candidate.module_id, candidate.generation),
        Some(&codex_hepta_control_plane::RuntimeModuleRecordV1 {
            abi: candidate.clone(),
            lifecycle: RuntimeModuleLifecycleV1::Active,
            selection_digest: Some(digest("selection")),
            canary_digest: Some(digest("canary")),
            handoff_digest: None,
        })
    );
}

#[test]
fn incomplete_initialization_evidence_leaves_candidate_and_routes_unchanged() {
    let mut candidate = abi(RuntimeModuleStateClassV1::Stateless);
    candidate.effect_scope.insert(id("external.effect"));
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    admit(&mut supervisor, &candidate);
    let before = supervisor.registry.checkpoint();
    for incomplete in [
        RuntimeModuleInitializationWitnessV1 {
            initial_state_digest: Digest32::ZERO,
            ..witness()
        },
        RuntimeModuleInitializationWitnessV1 {
            readiness_digest: Digest32::ZERO,
            ..witness()
        },
    ] {
        assert_eq!(
            supervisor.promote_new_initialized_module(
                &candidate.module_id,
                candidate.generation,
                digest("canary"),
                incomplete,
            ),
            Err(RuntimeModuleSupervisorErrorV1::InvalidInitializationWitness)
        );
        assert_eq!(supervisor.registry.checkpoint(), before);
    }
}

#[test]
fn initialized_addition_cannot_take_an_existing_writer_domain() {
    let mut candidate = abi(RuntimeModuleStateClassV1::Stateless);
    candidate.authoritative_domains.insert(id("owned.data"));
    let mut incumbent = candidate.clone();
    incumbent.module_id = id("incumbent");
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor.register_bootstrap(incumbent).expect("incumbent");
    admit(&mut supervisor, &candidate);
    let before = supervisor.registry.checkpoint();
    assert_eq!(
        supervisor.promote_new_initialized_module(
            &candidate.module_id,
            candidate.generation,
            digest("canary"),
            witness(),
        ),
        Err(RuntimeModuleRegistryError::AuthoritativeWriterConflict(id("owned.data")).into())
    );
    assert_eq!(supervisor.registry.checkpoint(), before);
}

#[test]
fn replacement_cannot_substitute_initialization_for_predecessor_handoff() {
    let mut candidate = abi(RuntimeModuleStateClassV1::Stateless);
    candidate.effect_scope.insert(id("external.effect"));
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor
        .register_bootstrap(candidate.clone())
        .expect("incumbent");
    candidate.predecessor_generation = Some(candidate.generation);
    candidate.generation = Generation::new(2).expect("generation");
    candidate.rollback_predecessor_digest = candidate.implementation_digest;
    candidate.implementation_digest = digest("replacement");
    admit(&mut supervisor, &candidate);
    let before = supervisor.registry.checkpoint();
    assert_eq!(
        supervisor.promote_new_initialized_module(
            &candidate.module_id,
            candidate.generation,
            digest("canary"),
            witness(),
        ),
        Err(RuntimeModuleSupervisorErrorV1::PredecessorMismatch)
    );
    assert_eq!(supervisor.registry.checkpoint(), before);
}

#[test]
fn initialization_preserves_selection_canary_and_dependency_checks() {
    let mut candidate = abi(RuntimeModuleStateClassV1::Stateful);
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor
        .registry
        .register_candidate(candidate.clone())
        .expect("register");
    let before = supervisor.registry.checkpoint();
    assert_eq!(
        supervisor.promote_new_initialized_module(
            &candidate.module_id,
            candidate.generation,
            digest("canary"),
            witness(),
        ),
        Err(RuntimeModuleSupervisorErrorV1::MissingVerifiedSelection)
    );
    assert_eq!(supervisor.registry.checkpoint(), before);

    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor
        .register_shadow_for_test(candidate.clone(), digest("selection"))
        .expect("shadow");
    let before = supervisor.registry.checkpoint();
    assert_eq!(
        supervisor.promote_new_initialized_module(
            &candidate.module_id,
            candidate.generation,
            digest("canary"),
            witness(),
        ),
        Err(RuntimeModuleRegistryError::InvalidLifecycleTransition.into())
    );
    assert_eq!(supervisor.registry.checkpoint(), before);

    let mut supervisor = RuntimeModuleSupervisorV1::new();
    candidate.dependencies.push(id("absent.provider"));
    admit(&mut supervisor, &candidate);
    let before = supervisor.registry.checkpoint();
    assert_eq!(
        supervisor.promote_new_initialized_module(
            &candidate.module_id,
            candidate.generation,
            digest("canary"),
            witness(),
        ),
        Err(RuntimeModuleSupervisorErrorV1::TopologyDependencyMissing {
            module_id: candidate.module_id.clone(),
            dependency_id: id("absent.provider"),
        })
    );
    assert_eq!(supervisor.registry.checkpoint(), before);
}
