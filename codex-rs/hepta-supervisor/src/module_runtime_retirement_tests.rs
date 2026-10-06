use super::RuntimeModuleRetirementWitnessV1;
use super::RuntimeModuleSupervisorErrorV1;
use super::RuntimeModuleSupervisorV1;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleLifecycleV1;
use codex_hepta_control_plane::RuntimeModuleRegistryV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn module(name: &str) -> RuntimeModuleAbiV1 {
    RuntimeModuleAbiV1 {
        module_id: id(name),
        owner_id: id("memory-team"),
        generation: generation(1),
        implementation_digest: digest("retirement-v1"),
        candidate_artifact_digest: digest("retirement-v1"),
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class: RuntimeModuleStateClassV1::Stateful,
        dependencies: Vec::new(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: [id("memory-ledger")].into_iter().collect(),
        effect_scope: Default::default(),
    }
}

fn active() -> RuntimeModuleSupervisorV1 {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor
        .register_bootstrap(module("memory.retrieval"))
        .expect("bootstrap");
    supervisor
}

fn drained() -> RuntimeModuleRetirementWitnessV1 {
    RuntimeModuleRetirementWitnessV1 {
        drain_digest: digest("owner-observed-drain"),
        reconciliation_digest: digest("owner-observed-terminal-effects"),
        unknown_effect_count: 0,
    }
}

#[test]
fn retirement_resumes_a_quiescing_registry_checkpoint() {
    let mut supervisor = active();
    let module = id("memory.retrieval");
    let current = generation(1);
    supervisor.registry.begin_retire(&module, current).unwrap();
    let checkpoint = supervisor.registry.checkpoint();
    // Exercise the real registry codec. The expected root is a test fixture,
    // not independently authenticated host custody or a persisted Supervisor.
    supervisor.registry = RuntimeModuleRegistryV1::restore_checkpoint_bytes(
        &supervisor.registry.checkpoint_bytes(),
        checkpoint.checkpoint_digest,
    )
    .unwrap();
    assert_eq!(supervisor.registry.checkpoint(), checkpoint);
    assert!(supervisor.topology().active.is_empty());

    let topology = supervisor
        .retire_after_reconciliation(&module, current, drained())
        .expect("continue the already-started retirement");
    assert!(topology.active.is_empty());
    assert_eq!(supervisor.registry.active_generation(&module), None);
    assert_eq!(
        supervisor
            .registry
            .record(&module, current)
            .unwrap()
            .lifecycle,
        RuntimeModuleLifecycleV1::Retired
    );
    assert_eq!(
        supervisor.registry.greatest_admitted_generation(&module),
        Some(current)
    );
}

#[test]
fn unresolved_effects_keep_quiescing_retirement_and_writer_reservation() {
    let mut supervisor = active();
    let module = id("memory.retrieval");
    let current = generation(1);
    supervisor.registry.begin_retire(&module, current).unwrap();
    let before = supervisor.registry.checkpoint();
    let ready = supervisor.retirement_ready.clone();
    let mut witness = drained();
    witness.unknown_effect_count = 1;

    assert_eq!(
        supervisor.retire_after_reconciliation(&module, current, witness),
        Err(RuntimeModuleSupervisorErrorV1::InvalidRetirementWitness)
    );
    assert_eq!(supervisor.registry.checkpoint(), before);
    assert_eq!(supervisor.retirement_ready, ready);
    assert_eq!(
        supervisor.registry.active_generation(&module),
        Some(current)
    );
    assert!(supervisor.topology().active.is_empty());
}

#[test]
fn already_observed_active_retirement_remains_supported() {
    let mut supervisor = active();
    let module = id("memory.retrieval");
    let result = supervisor
        .retire_after_reconciliation(&module, generation(1), drained())
        .unwrap();
    assert!(result.active.is_empty());
    assert_eq!(supervisor.registry.active_generation(&module), None);
}

#[test]
fn already_observed_quarantined_retirement_remains_supported() {
    let mut supervisor = active();
    let module = id("memory.retrieval");
    supervisor
        .registry
        .quarantine(&module, generation(1))
        .unwrap();
    let result = supervisor
        .retire_after_reconciliation(&module, generation(1), drained())
        .unwrap();
    assert!(result.active.is_empty());
    assert_eq!(supervisor.registry.active_generation(&module), None);
}

#[test]
fn begin_retirement_retries_preserve_other_routes_and_current_observations() {
    for quarantine in [false, true] {
        let mut supervisor = active();
        let key = id("memory.retrieval");
        let current = generation(1);
        let mut unrelated = module("independent-provider");
        unrelated.authoritative_domains = [id("independent-ledger")].into_iter().collect();
        supervisor.register_bootstrap(unrelated).unwrap();
        supervisor
            .record_retirement_ready(&key, current, drained())
            .unwrap();
        if quarantine {
            supervisor.registry.quarantine(&key, current).unwrap();
        }
        let selections = supervisor.selections.clone();
        let stopped = supervisor.begin_retirement(&key, current).unwrap();
        assert_eq!(stopped.active.len(), 1);
        assert_eq!(stopped.active[0].module_id, id("independent-provider"));
        assert_eq!(supervisor.registry.active_generation(&key), Some(current));
        assert_eq!(
            supervisor.registry.greatest_admitted_generation(&key),
            Some(current)
        );
        assert_eq!(supervisor.selections, selections);
        assert!(supervisor.retirement_ready.is_empty());

        // An observation made after stopping admission belongs to the current
        // phase. Replaying its begin must not erase it or restart dispatch.
        supervisor
            .record_retirement_ready(&key, current, drained())
            .unwrap();
        let before = supervisor.registry.checkpoint();
        let ready = supervisor.retirement_ready.clone();
        assert_eq!(supervisor.begin_retirement(&key, current).unwrap(), stopped);
        assert_eq!(supervisor.registry.checkpoint(), before);
        assert_eq!(supervisor.retirement_ready, ready);
        assert_eq!(supervisor.selections, selections);
    }
}

#[test]
fn retirement_holds_the_writer_domain_until_terminal_reconciliation() {
    let mut supervisor = active();
    let key = id("memory.retrieval");
    let current = generation(1);
    supervisor.begin_retirement(&key, current).unwrap();
    let before = supervisor.registry.checkpoint();
    let contender = module("replacement-owner");
    assert_eq!(
        supervisor.register_bootstrap(contender.clone()),
        Err(RuntimeModuleSupervisorErrorV1::Registry(
            codex_hepta_control_plane::RuntimeModuleRegistryError::AuthoritativeWriterConflict(id(
                "memory-ledger"
            ))
        ))
    );
    assert_eq!(supervisor.registry.checkpoint(), before);
    supervisor
        .retire_after_reconciliation(&key, current, drained())
        .unwrap();
    let topology = supervisor.register_bootstrap(contender).unwrap();
    assert_eq!(topology.active.len(), 1);
    assert_eq!(topology.active[0].module_id, id("replacement-owner"));
    assert_eq!(
        supervisor.registry.greatest_admitted_generation(&key),
        Some(current)
    );
}

#[test]
fn selected_dependents_block_retirement_without_mutation() {
    for lifecycle in [
        RuntimeModuleLifecycleV1::Active,
        RuntimeModuleLifecycleV1::Quiescing,
        RuntimeModuleLifecycleV1::Quarantined,
    ] {
        let mut supervisor = active();
        let key = id("memory.retrieval");
        let current = generation(1);
        let mut consumer = module("retained-consumer");
        consumer.dependencies = vec![key.clone()];
        consumer.authoritative_domains.clear();
        supervisor.register_bootstrap(consumer).unwrap();
        match lifecycle {
            RuntimeModuleLifecycleV1::Quiescing => supervisor
                .registry
                .begin_retire(&id("retained-consumer"), current)
                .unwrap(),
            RuntimeModuleLifecycleV1::Quarantined => supervisor
                .registry
                .quarantine(&id("retained-consumer"), current)
                .unwrap(),
            RuntimeModuleLifecycleV1::Active => {}
            RuntimeModuleLifecycleV1::Registered
            | RuntimeModuleLifecycleV1::Shadow
            | RuntimeModuleLifecycleV1::Canary
            | RuntimeModuleLifecycleV1::Retired => {
                unreachable!("the test enumerates selected reservations only")
            }
        }
        supervisor
            .record_retirement_ready(&key, current, drained())
            .unwrap();
        let before = supervisor.registry.checkpoint();
        let ready = supervisor.retirement_ready.clone();
        let selections = supervisor.selections.clone();
        assert_eq!(
            supervisor.begin_retirement(&key, current),
            Err(RuntimeModuleSupervisorErrorV1::Registry(
                codex_hepta_control_plane::RuntimeModuleRegistryError::SelectedDependent(id(
                    "retained-consumer"
                ))
            ))
        );
        assert_eq!(supervisor.registry.checkpoint(), before);
        assert_eq!(supervisor.retirement_ready, ready);
        assert_eq!(supervisor.selections, selections);
    }
}

#[test]
fn invalid_terminal_observations_preserve_quiescing_for_a_valid_retry() {
    let valid = drained();
    for witness in [
        RuntimeModuleRetirementWitnessV1 {
            drain_digest: Digest32::ZERO,
            ..valid.clone()
        },
        RuntimeModuleRetirementWitnessV1 {
            reconciliation_digest: Digest32::ZERO,
            ..valid.clone()
        },
        RuntimeModuleRetirementWitnessV1 {
            unknown_effect_count: 1,
            ..valid.clone()
        },
    ] {
        let mut supervisor = active();
        let key = id("memory.retrieval");
        let current = generation(1);
        supervisor.begin_retirement(&key, current).unwrap();
        let before = supervisor.registry.checkpoint();
        let ready = supervisor.retirement_ready.clone();
        assert_eq!(
            supervisor.retire_after_reconciliation(&key, current, witness),
            Err(RuntimeModuleSupervisorErrorV1::InvalidRetirementWitness)
        );
        assert_eq!(supervisor.registry.checkpoint(), before);
        assert_eq!(supervisor.retirement_ready, ready);
        assert_eq!(supervisor.registry.active_generation(&key), Some(current));
        let topology = supervisor
            .retire_after_reconciliation(&key, current, valid.clone())
            .unwrap();
        assert!(topology.active.is_empty());
        assert_eq!(supervisor.registry.active_generation(&key), None);
        assert_eq!(
            supervisor.registry.greatest_admitted_generation(&key),
            Some(current)
        );
    }
}

#[test]
fn wrong_or_terminal_retirement_identities_do_not_change_the_registry() {
    let mut supervisor = active();
    let key = id("memory.retrieval");
    let current = generation(1);
    for (wrong_key, wrong_generation) in [
        (key.clone(), generation(2)),
        (id("not-registered"), current),
    ] {
        let before = supervisor.registry.checkpoint();
        let ready = supervisor.retirement_ready.clone();
        assert!(
            supervisor
                .begin_retirement(&wrong_key, wrong_generation)
                .is_err()
        );
        assert!(
            supervisor
                .retire_after_reconciliation(&wrong_key, wrong_generation, drained())
                .is_err()
        );
        assert_eq!(supervisor.registry.checkpoint(), before);
        assert_eq!(supervisor.retirement_ready, ready);
    }
    supervisor.begin_retirement(&key, current).unwrap();
    supervisor
        .retire_after_reconciliation(&key, current, drained())
        .unwrap();
    let retired = supervisor.registry.checkpoint();
    assert!(supervisor.begin_retirement(&key, current).is_err());
    assert!(
        supervisor
            .retire_after_reconciliation(&key, current, drained())
            .is_err()
    );
    assert_eq!(supervisor.registry.checkpoint(), retired);
    assert!(supervisor.retirement_ready.is_empty());
}
