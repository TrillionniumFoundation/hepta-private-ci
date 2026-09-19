//! Dispatch suppression must not release authoritative ownership.

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn abi(module: &str, epoch: u64) -> RuntimeModuleAbiV1 {
    let digest = Digest32::of_bytes(module.as_bytes());
    RuntimeModuleAbiV1 {
        module_id: id(module),
        owner_id: id("owner"),
        generation: generation(epoch),
        implementation_digest: digest,
        candidate_artifact_digest: digest,
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class: RuntimeModuleStateClassV1::Stateful,
        dependencies: Vec::new(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: [id("ledger")].into_iter().collect(),
        effect_scope: BTreeSet::new(),
    }
}

#[test]
fn draining_writer_is_not_dispatchable_but_keeps_its_domain() {
    let mut registry = RuntimeModuleRegistryV1::new();
    registry.register_candidate(abi("old", 1)).expect("register");
    registry
        .activate_bootstrap(&id("old"), generation(1))
        .expect("bootstrap");
    registry
        .begin_retire(&id("old"), generation(1))
        .expect("drain");
    assert!(registry.snapshot().active.is_empty());
    registry
        .register_candidate(abi("new", 2))
        .expect("register peer");
    assert_eq!(
        registry.activate_bootstrap(&id("new"), generation(2)),
        Err(RuntimeModuleRegistryError::AuthoritativeWriterConflict(id(
            "ledger"
        )))
    );
    registry
        .finish_retire(&id("old"), generation(1))
        .expect("reconciled retirement");
    let snapshot = registry
        .activate_bootstrap(&id("new"), generation(2))
        .expect("new owner");
    assert_eq!(snapshot.active[0].module_id, id("new"));
}

#[test]
fn quarantined_active_writer_requires_reconciliation_before_domain_reuse() {
    let mut registry = RuntimeModuleRegistryV1::new();
    registry.register_candidate(abi("old", 1)).expect("register");
    registry
        .activate_bootstrap(&id("old"), generation(1))
        .expect("bootstrap");
    registry
        .quarantine(&id("old"), generation(1))
        .expect("quarantine");
    assert!(registry.snapshot().active.is_empty());
    registry
        .register_candidate(abi("new", 2))
        .expect("register peer");
    assert_eq!(
        registry.activate_bootstrap(&id("new"), generation(2)),
        Err(RuntimeModuleRegistryError::AuthoritativeWriterConflict(id(
            "ledger"
        )))
    );
    registry
        .begin_retire(&id("old"), generation(1))
        .expect("reconcile");
    registry
        .finish_retire(&id("old"), generation(1))
        .expect("retire");
    registry
        .activate_bootstrap(&id("new"), generation(2))
        .expect("new owner");
}

#[test]
fn quarantining_an_unselected_candidate_does_not_acquire_a_writer_domain() {
    let mut registry = RuntimeModuleRegistryV1::new();
    registry
        .register_candidate(abi("candidate", 1))
        .expect("register");
    registry
        .quarantine(&id("candidate"), generation(1))
        .expect("quarantine");
    registry
        .register_candidate(abi("owner", 2))
        .expect("register owner");
    registry
        .activate_bootstrap(&id("owner"), generation(2))
        .expect("no phantom reservation");
}

#[test]
fn retirement_does_not_reopen_bootstrap_or_rewind_generation() {
    let mut registry = RuntimeModuleRegistryV1::new();
    registry
        .register_candidate(abi("module", 7))
        .expect("register");
    registry
        .activate_bootstrap(&id("module"), generation(7))
        .expect("bootstrap");
    registry
        .begin_retire(&id("module"), generation(7))
        .expect("drain");
    registry
        .finish_retire(&id("module"), generation(7))
        .expect("retire");
    assert_eq!(
        registry.register_candidate(abi("module", 6)),
        Err(RuntimeModuleRegistryError::InvalidGeneration)
    );
    registry
        .register_candidate(abi("module", 8))
        .expect("future candidate");
    assert_eq!(
        registry.activate_bootstrap(&id("module"), generation(8)),
        Err(RuntimeModuleRegistryError::InvalidLifecycleTransition)
    );
}

#[test]
fn effectful_or_stateful_candidate_cannot_take_stateless_promotion_shortcut() {
    for state_class in [
        RuntimeModuleStateClassV1::Stateful,
        RuntimeModuleStateClassV1::ExternalStateful,
    ] {
        let mut registry = RuntimeModuleRegistryV1::new();
        let mut candidate = abi("module", 1);
        candidate.state_class = state_class;
        candidate.authoritative_domains.clear();
        candidate.effect_scope.insert(id("browser.dispatch"));
        registry.register_candidate(candidate).expect("register");
        registry
            .enter_shadow(&id("module"), generation(1))
            .expect("shadow");
        registry
            .enter_canary(&id("module"), generation(1))
            .expect("canary");
        assert_eq!(
            registry.promote_after_handoff(
                &id("module"),
                generation(1),
                RuntimeModulePromotionWitnessV1 {
                    selection_digest: Digest32::of_bytes(b"selection"),
                    canary_digest: Digest32::of_bytes(b"canary"),
                    handoff_digest: Digest32::ZERO,
                }
            ),
            Err(RuntimeModuleRegistryError::MissingWriterHandoff)
        );
        assert!(registry.snapshot().active.is_empty());
    }
}
