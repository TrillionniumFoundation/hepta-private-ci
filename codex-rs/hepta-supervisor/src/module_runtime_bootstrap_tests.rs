//! Bootstrap publication shares the dependency invariant of upgrade/rollback.

use super::*;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use pretty_assertions::assert_eq;

fn module(name: &str, dependencies: &[&str]) -> RuntimeModuleAbiV1 {
    RuntimeModuleAbiV1 {
        module_id: StableId::new(name).unwrap(),
        owner_id: StableId::new("bootstrap-owner").unwrap(),
        generation: Generation::new(/*value*/ 1).unwrap(),
        implementation_digest: Digest32::of_bytes(name.as_bytes()),
        candidate_artifact_digest: Digest32::of_bytes(name.as_bytes()),
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class: RuntimeModuleStateClassV1::Stateless,
        dependencies: dependencies
            .iter()
            .map(|dependency| StableId::new(*dependency).unwrap())
            .collect(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: BTreeSet::new(),
        effect_scope: BTreeSet::new(),
    }
}

#[test]
fn bootstrap_rejects_dangling_dependency_without_consuming_identity_or_writer() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    let mut consumer = module("consumer", &["provider"]);
    consumer.state_class = RuntimeModuleStateClassV1::Stateful;
    consumer
        .authoritative_domains
        .insert(StableId::new("owned-domain").unwrap());
    let before = supervisor.registry.checkpoint();
    let topology = supervisor.topology();
    assert_eq!(
        supervisor.register_bootstrap(consumer.clone()),
        Err(RuntimeModuleSupervisorErrorV1::TopologyDependencyMissing {
            module_id: consumer.module_id.clone(),
            dependency_id: StableId::new("provider").unwrap(),
        })
    );
    assert_eq!(supervisor.registry.checkpoint(), before);
    assert_eq!(supervisor.topology(), topology);
    assert!(supervisor.selections.is_empty());
    assert!(supervisor.pending_topologies.is_empty());
    assert!(supervisor.pending_promotions.is_empty());
    assert!(supervisor.retirement_ready.is_empty());

    // The same generation can be retried after its provider becomes available.
    // Rejection must not leave an identity fence or selected writer behind.
    supervisor
        .register_bootstrap(module("provider", &[]))
        .unwrap();
    let snapshot = supervisor.register_bootstrap(consumer.clone()).unwrap();
    assert_eq!(snapshot.active.len(), 2);
    assert_eq!(
        supervisor.registry.active_generation(&consumer.module_id),
        Some(consumer.generation)
    );
    validate_runtime_dependency_graph(&snapshot).unwrap();
}

#[test]
fn bootstrap_rejects_a_retired_dependency_and_preserves_unrelated_routes() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    let provider = module("provider", &[]);
    supervisor.register_bootstrap(provider.clone()).unwrap();
    supervisor
        .register_bootstrap(module("unrelated", &[]))
        .unwrap();
    supervisor
        .retire_after_reconciliation(
            &provider.module_id,
            provider.generation,
            RuntimeModuleRetirementWitnessV1 {
                drain_digest: Digest32::of_bytes(b"drained"),
                reconciliation_digest: Digest32::ZERO,
                unknown_effect_count: 0,
            },
        )
        .unwrap();
    let before = supervisor.registry.checkpoint();
    let topology = supervisor.topology();
    let consumer = module("consumer", &["provider"]);
    assert_eq!(
        supervisor.register_bootstrap(consumer.clone()),
        Err(RuntimeModuleSupervisorErrorV1::TopologyDependencyMissing {
            module_id: consumer.module_id,
            dependency_id: provider.module_id,
        })
    );
    assert_eq!(supervisor.registry.checkpoint(), before);
    assert_eq!(supervisor.topology(), topology);
    // A valid independent module remains admissible with the rejected identity.
    supervisor
        .register_bootstrap(module("consumer", &[]))
        .unwrap();
    validate_runtime_dependency_graph(&supervisor.topology()).unwrap();
}

#[test]
fn bootstrap_accepts_dependency_order_and_keeps_dependent_retirement_fence() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    let provider = module("provider", &[]);
    supervisor.register_bootstrap(provider.clone()).unwrap();
    supervisor
        .register_bootstrap(module("middle", &["provider"]))
        .unwrap();
    let snapshot = supervisor
        .register_bootstrap(module("consumer", &["middle", "provider"]))
        .unwrap();
    validate_runtime_dependency_graph(&snapshot).unwrap();
    let before = supervisor.registry.checkpoint();
    assert_eq!(
        supervisor.retire_after_reconciliation(
            &provider.module_id,
            provider.generation,
            RuntimeModuleRetirementWitnessV1 {
                drain_digest: Digest32::of_bytes(b"drained"),
                reconciliation_digest: Digest32::ZERO,
                unknown_effect_count: 0,
            },
        ),
        Err(RuntimeModuleSupervisorErrorV1::Registry(
            RuntimeModuleRegistryError::SelectedDependent(StableId::new("consumer").unwrap())
        ))
    );
    assert_eq!(supervisor.registry.checkpoint(), before);
    assert_eq!(supervisor.topology(), snapshot);
    assert!(supervisor.retirement_ready.is_empty());
}
