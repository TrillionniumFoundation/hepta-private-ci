//! These fixtures isolate admission bookkeeping, not worker or authority shutdown.

use codex_hepta_control_plane::RuntimeModuleRegistryCheckpointV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use pretty_assertions::assert_eq;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn candidate(epoch: u64) -> RuntimeModuleAbiV1 {
    RuntimeModuleAbiV1 {
        module_id: id("module"),
        owner_id: id("owner"),
        generation: generation(epoch),
        implementation_digest: digest(&format!("implementation-{epoch}")),
        candidate_artifact_digest: digest(&format!("candidate-{epoch}")),
        predecessor_generation: (epoch > 1).then(|| generation(1)),
        rollback_predecessor_digest: if epoch > 1 {
            digest("implementation-1")
        } else {
            Digest32::ZERO
        },
        state_class: RuntimeModuleStateClassV1::Stateful,
        dependencies: Vec::new(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: [id("owned.domain")].into_iter().collect(),
        effect_scope: [id("external.effect")].into_iter().collect(),
    }
}

#[derive(Debug, PartialEq)]
struct WorkingSet {
    checkpoint: RuntimeModuleRegistryCheckpointV1,
    selections: BTreeMap<(StableId, Generation), Digest32>,
    topologies: BTreeMap<Digest32, RuntimeTopologyCandidateV1>,
    promotions: BTreeMap<(Digest32, StableId), RuntimeModulePromotionWitnessV1>,
    retirements: BTreeMap<(StableId, Generation), Digest32>,
}

fn working_set(supervisor: &RuntimeModuleSupervisorV1) -> WorkingSet {
    WorkingSet {
        checkpoint: supervisor.registry.checkpoint(),
        selections: supervisor.selections.clone(),
        topologies: supervisor.pending_topologies.clone(),
        promotions: supervisor.pending_promotions.clone(),
        retirements: supervisor.retirement_ready.clone(),
    }
}

#[test]
fn withdrawal_preserves_incumbent_writer_and_disables_shadow_or_canary_promotion() {
    for lifecycle in [
        RuntimeModuleLifecycleV1::Shadow,
        RuntimeModuleLifecycleV1::Canary,
    ] {
        let mut supervisor = RuntimeModuleSupervisorV1::new();
        let serving = supervisor
            .register_bootstrap(candidate(1))
            .expect("bootstrap");
        let incumbent = supervisor
            .registry
            .record(&id("module"), generation(1))
            .cloned();
        supervisor
            .register_shadow_for_test(candidate(2), digest("selection"))
            .expect("shadow");
        if lifecycle == RuntimeModuleLifecycleV1::Canary {
            supervisor
                .enter_canary(&id("module"), generation(2))
                .expect("canary");
        }
        let mut expected = supervisor
            .registry
            .record(&id("module"), generation(2))
            .cloned()
            .unwrap();
        expected.lifecycle = RuntimeModuleLifecycleV1::Quarantined;
        supervisor
            .discard_selected_candidate(&id("module"), generation(2))
            .expect("withdraw");
        assert_eq!(supervisor.topology(), serving);
        assert_eq!(
            supervisor.registry.record(&id("module"), generation(1)),
            incumbent.as_ref()
        );
        assert_eq!(
            supervisor.registry.record(&id("module"), generation(2)),
            Some(&expected)
        );
        assert_eq!(
            supervisor.registry.active_generation(&id("module")),
            Some(generation(1))
        );
        assert!(supervisor.selections.is_empty());
        assert_eq!(
            supervisor.promote_stateless(&id("module"), generation(2), digest("canary")),
            Err(RuntimeModuleSupervisorErrorV1::MissingVerifiedSelection)
        );
        assert_eq!(
            supervisor.enter_canary(&id("module"), generation(2)),
            Err(RuntimeModuleRegistryError::InvalidLifecycleTransition.into())
        );
    }
}

#[test]
fn a_full_pending_queue_can_reclaim_one_slot_without_raising_its_limit() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor.register_bootstrap(candidate(1)).unwrap();
    for epoch in 2..=129 {
        supervisor
            .register_shadow_for_test(candidate(epoch), digest("selection"))
            .unwrap();
    }
    let before = working_set(&supervisor);
    assert_eq!(
        supervisor.register_shadow_for_test(candidate(130), digest("selection")),
        Err(RuntimeModuleRegistryError::Bounds.into())
    );
    assert_eq!(working_set(&supervisor), before);
    supervisor
        .discard_selected_candidate(&id("module"), generation(64))
        .unwrap();
    supervisor
        .register_shadow_for_test(candidate(130), digest("selection"))
        .expect("released one slot");
    assert_eq!(supervisor.selections.len(), 128);
    let before = working_set(&supervisor);
    assert_eq!(
        supervisor.register_shadow_for_test(candidate(131), digest("selection")),
        Err(RuntimeModuleRegistryError::Bounds.into())
    );
    assert_eq!(working_set(&supervisor), before);
    assert_eq!(
        supervisor.registry.active_generation(&id("module")),
        Some(generation(1))
    );
}

#[test]
fn repeated_withdrawals_keep_bookkeeping_bounded_and_preserve_checkpoint_fences() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    let serving = supervisor.register_bootstrap(candidate(1)).unwrap();
    for epoch in 2..=1025 {
        supervisor
            .register_shadow_for_test(candidate(epoch), digest("selection"))
            .unwrap();
        supervisor
            .discard_selected_candidate(&id("module"), generation(epoch))
            .unwrap();
        assert_eq!(supervisor.topology(), serving);
        assert!(supervisor.selections.is_empty());
        assert!(supervisor.registry.checkpoint().records.len() <= 2);
        assert_eq!(
            supervisor
                .registry
                .greatest_admitted_generation(&id("module")),
            Some(generation(epoch))
        );
    }
    assert!(
        supervisor
            .registry
            .record(&id("module"), generation(2))
            .is_none()
    );
    let checkpoint = supervisor.registry.checkpoint();
    let mut restored = RuntimeModuleRegistryV1::restore_checkpoint_bytes(
        &supervisor.registry.checkpoint_bytes(),
        checkpoint.checkpoint_digest,
    )
    .expect("fixture checkpoint round-trip, not independent current-root custody");
    assert_eq!(restored.checkpoint(), checkpoint);
    assert_eq!(restored.snapshot(), serving);
    assert_eq!(
        restored.register_candidate(candidate(2)),
        Err(RuntimeModuleRegistryError::InvalidGeneration)
    );
    assert_eq!(restored.checkpoint(), checkpoint);
}

#[test]
fn selected_active_draining_and_quarantined_writers_cannot_be_withdrawn() {
    for lifecycle in [
        RuntimeModuleLifecycleV1::Active,
        RuntimeModuleLifecycleV1::Quiescing,
        RuntimeModuleLifecycleV1::Quarantined,
    ] {
        let mut supervisor = RuntimeModuleSupervisorV1::new();
        supervisor.register_bootstrap(candidate(1)).unwrap();
        supervisor
            .record_retirement_ready(
                &id("module"),
                generation(1),
                RuntimeModuleRetirementWitnessV1 {
                    drain_digest: digest("drain"),
                    reconciliation_digest: digest("reconciliation"),
                    unknown_effect_count: 0,
                },
            )
            .unwrap();
        if lifecycle == RuntimeModuleLifecycleV1::Quiescing {
            supervisor
                .registry
                .begin_retire(&id("module"), generation(1))
                .unwrap();
        }
        if lifecycle == RuntimeModuleLifecycleV1::Quarantined {
            supervisor
                .registry
                .quarantine(&id("module"), generation(1))
                .unwrap();
        }
        let before = working_set(&supervisor);
        assert_eq!(
            supervisor.discard_selected_candidate(&id("module"), generation(1)),
            Err(RuntimeModuleRegistryError::InvalidLifecycleTransition.into())
        );
        assert_eq!(working_set(&supervisor), before);
    }
}

#[test]
fn unknown_unselected_and_already_terminal_candidates_reject_without_mutation() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    let before = working_set(&supervisor);
    assert_eq!(
        supervisor.discard_selected_candidate(&id("module"), generation(1)),
        Err(RuntimeModuleRegistryError::UnknownCandidate.into())
    );
    assert_eq!(working_set(&supervisor), before);
    supervisor
        .registry
        .register_candidate(candidate(1))
        .unwrap();
    let before = working_set(&supervisor);
    assert_eq!(
        supervisor.discard_selected_candidate(&id("module"), generation(1)),
        Err(RuntimeModuleRegistryError::InvalidLifecycleTransition.into())
    );
    assert_eq!(working_set(&supervisor), before);
    supervisor
        .registry
        .enter_shadow(&id("module"), generation(1))
        .unwrap();
    let before = working_set(&supervisor);
    assert_eq!(
        supervisor.discard_selected_candidate(&id("module"), generation(1)),
        Err(RuntimeModuleSupervisorErrorV1::MissingVerifiedSelection)
    );
    assert_eq!(working_set(&supervisor), before);

    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor
        .register_shadow_for_test(candidate(1), digest("selection"))
        .unwrap();
    supervisor
        .discard_selected_candidate(&id("module"), generation(1))
        .unwrap();
    let before = working_set(&supervisor);
    assert_eq!(
        supervisor.discard_selected_candidate(&id("module"), generation(1)),
        Err(RuntimeModuleRegistryError::InvalidLifecycleTransition.into())
    );
    assert_eq!(working_set(&supervisor), before);
}
