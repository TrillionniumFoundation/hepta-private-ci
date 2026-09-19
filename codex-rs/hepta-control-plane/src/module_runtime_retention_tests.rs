//! Lifecycle working-set regressions, not target-host durability measurements.

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid identity")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn abi(name: &str, epoch: u64, predecessor: Option<&RuntimeModuleAbiV1>) -> RuntimeModuleAbiV1 {
    RuntimeModuleAbiV1 {
        module_id: id(name),
        owner_id: id("module-owner"),
        generation: generation(epoch),
        implementation_digest: Digest32::of_bytes(format!("{name}-{epoch}").as_bytes()),
        candidate_artifact_digest: Digest32::of_bytes(format!("candidate-{name}-{epoch}").as_bytes()),
        predecessor_generation: predecessor.map(|value| value.generation),
        rollback_predecessor_digest: predecessor
            .map_or(Digest32::ZERO, |value| value.implementation_digest),
        state_class: RuntimeModuleStateClassV1::Stateless,
        dependencies: Vec::new(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: BTreeSet::new(),
        effect_scope: BTreeSet::new(),
    }
}

fn witness() -> RuntimeModulePromotionWitnessV1 {
    RuntimeModulePromotionWitnessV1 {
        selection_digest: Digest32::of_bytes(b"independent-selection"),
        canary_digest: Digest32::of_bytes(b"observed-canary"),
        handoff_digest: Digest32::of_bytes(b"completed-handoff"),
    }
}

fn promote(registry: &mut RuntimeModuleRegistryV1, candidate: RuntimeModuleAbiV1) {
    let module = candidate.module_id.clone();
    let epoch = candidate.generation;
    registry.register_candidate(candidate).expect("register");
    registry.enter_shadow(&module, epoch).expect("shadow");
    registry.enter_canary(&module, epoch).expect("canary");
    registry
        .promote_after_handoff(&module, epoch, witness())
        .expect("promote");
}

#[test]
fn thousand_upgrade_rollback_cycles_keep_payloads_bounded_and_epochs_fenced() {
    let mut registry = RuntimeModuleRegistryV1::new();
    let module = id("evolving.module");
    promote(&mut registry, abi(module.as_str(), 1, None));
    for _ in 0..1_000 {
        let epoch = registry.active_generation(&module).expect("active generation");
        let previous = registry.record(&module, epoch).expect("active record").abi.clone();
        let next = abi(module.as_str(), epoch.get() + 1, Some(&previous));
        let next_epoch = next.generation;
        promote(&mut registry, next);
        let rollback_epoch = generation(next_epoch.get() + 1);
        let snapshot = registry
            .rollback_active_to_predecessor_content(
                &module,
                next_epoch,
                rollback_epoch,
                Digest32::of_bytes(b"independently-observed-rollback"),
            )
            .expect("rollback must not consume cumulative history capacity");
        assert_eq!(snapshot.active.len(), 1);
        assert_eq!(snapshot.active[0].generation, rollback_epoch);
        assert_eq!(snapshot.active[0].implementation_digest, previous.implementation_digest);
        assert!(registry.records.len() <= 4, "payload history grew without bound");
        assert_eq!(registry.generation_fences.len(), 1);
    }
    assert!(registry.record(&module, generation(1)).is_none());
    // A retained identity fence, not the discarded payload, rejects old epochs.
    let before = registry.clone();
    assert_eq!(
        registry.register_candidate(abi(module.as_str(), 1, None)),
        Err(RuntimeModuleRegistryError::InvalidGeneration)
    );
    assert_eq!(registry.records, before.records);
    assert_eq!(registry.generation_fences, before.generation_fences);
}

#[test]
fn full_pending_queue_does_not_starve_rollback_or_expand_selected_capacity() {
    let mut registry = RuntimeModuleRegistryV1::new();
    for index in 0..MAX_RUNTIME_MODULES {
        let name = format!("module-{index}");
        let first = abi(&name, 1, None);
        promote(&mut registry, first.clone());
        promote(&mut registry, abi(&name, 2, Some(&first)));
    }
    for index in 0..MAX_PENDING_RUNTIME_MODULES {
        let name = format!("module-{index}");
        let active = registry.record(&id(&name), generation(2)).expect("active").abi.clone();
        registry.register_candidate(abi(&name, 3, Some(&active))).expect("pending candidate");
    }
    assert_eq!(registry.pending_candidate_count(), MAX_PENDING_RUNTIME_MODULES);
    assert_eq!(
        registry.register_candidate(abi("extra-module", 1, None)),
        Err(RuntimeModuleRegistryError::Bounds)
    );
    registry
        .rollback_active_to_predecessor_content(
            &id("module-0"), generation(2), generation(4), Digest32::of_bytes(b"rollback"),
        )
        .expect("reserved transactional rollback slot");
    assert_eq!(registry.active.len(), MAX_RUNTIME_MODULES);
    assert_eq!(registry.pending_candidate_count(), MAX_PENDING_RUNTIME_MODULES);
    assert_eq!(registry.active_generation(&id("module-0")), Some(generation(4)));
}

#[test]
fn selected_capacity_counts_draining_and_quarantined_writers() {
    let mut registry = RuntimeModuleRegistryV1::new();
    for index in 0..MAX_RUNTIME_MODULES {
        promote(&mut registry, abi(&format!("module-{index}"), 1, None));
    }
    let candidate = abi("extra-module", 1, None);
    registry.register_candidate(candidate.clone()).expect("pending is a separate budget");
    registry.enter_shadow(&candidate.module_id, candidate.generation).unwrap();
    registry.enter_canary(&candidate.module_id, candidate.generation).unwrap();
    registry.quarantine(&id("module-0"), generation(1)).unwrap();
    assert_eq!(registry.snapshot().active.len(), MAX_RUNTIME_MODULES - 1);
    assert_eq!(
        registry.promote_after_handoff(&candidate.module_id, candidate.generation, witness()),
        Err(RuntimeModuleRegistryError::Bounds)
    );
    registry.begin_retire(&id("module-0"), generation(1)).unwrap();
    assert_eq!(
        registry.promote_after_handoff(&candidate.module_id, candidate.generation, witness()),
        Err(RuntimeModuleRegistryError::Bounds)
    );
    registry.finish_retire(&id("module-0"), generation(1)).unwrap();
    registry.promote_after_handoff(&candidate.module_id, candidate.generation, witness()).unwrap();
    assert_eq!(registry.snapshot().active.len(), MAX_RUNTIME_MODULES);
}

#[test]
fn rejected_candidates_release_work_budget_but_not_their_epoch_fence() {
    let mut registry = RuntimeModuleRegistryV1::new();
    for epoch in 1..=1_000 {
        let candidate = abi("rejected.module", epoch, None);
        registry.register_candidate(candidate.clone()).unwrap();
        registry.quarantine(&candidate.module_id, candidate.generation).unwrap();
        assert_eq!(registry.pending_candidate_count(), 0);
        assert_eq!(registry.records.len(), 1);
    }
    assert_eq!(
        registry.register_candidate(abi("rejected.module", 1, None)),
        Err(RuntimeModuleRegistryError::InvalidGeneration)
    );
}

#[test]
fn compaction_cannot_reopen_bootstrap_for_a_retired_identity() {
    let mut registry = RuntimeModuleRegistryV1::new();
    let first = abi("retired.module", 1, None);
    registry.register_candidate(first.clone()).unwrap();
    registry.activate_bootstrap(&first.module_id, first.generation).unwrap();
    registry.begin_retire(&first.module_id, first.generation).unwrap();
    registry.finish_retire(&first.module_id, first.generation).unwrap();
    let replacement = abi("retired.module", 2, None);
    registry.register_candidate(replacement.clone()).unwrap();
    assert!(registry.record(&first.module_id, first.generation).is_none());
    assert_eq!(
        registry.activate_bootstrap(&replacement.module_id, replacement.generation),
        Err(RuntimeModuleRegistryError::InvalidLifecycleTransition)
    );
    registry.enter_shadow(&replacement.module_id, replacement.generation).unwrap();
    registry.enter_canary(&replacement.module_id, replacement.generation).unwrap();
    registry.promote_after_handoff(&replacement.module_id, replacement.generation, witness()).unwrap();
}

#[test]
fn failed_rollback_is_atomic_including_generation_fences() {
    let mut registry = RuntimeModuleRegistryV1::new();
    let mut first = abi("moving-writer", 1, None);
    first.state_class = RuntimeModuleStateClassV1::Stateful;
    first.authoritative_domains.insert(id("original-domain"));
    promote(&mut registry, first.clone());
    let mut second = abi("moving-writer", 2, Some(&first));
    second.state_class = RuntimeModuleStateClassV1::Stateful;
    second.authoritative_domains.insert(id("new-domain"));
    promote(&mut registry, second.clone());
    let mut other = abi("other-writer", 1, None);
    other.state_class = RuntimeModuleStateClassV1::Stateful;
    other.authoritative_domains.insert(id("original-domain"));
    promote(&mut registry, other);
    let before = registry.clone();
    assert!(matches!(
        registry.rollback_active_to_predecessor_content(
            &second.module_id, second.generation, generation(3), Digest32::of_bytes(b"rollback"),
        ),
        Err(RuntimeModuleRegistryError::AuthoritativeWriterConflict(_))
    ));
    assert_eq!(registry.records, before.records);
    assert_eq!(registry.active, before.active);
    assert_eq!(registry.generation_fences, before.generation_fences);
}

#[test]
fn pending_candidate_pins_its_own_predecessor_payload() {
    let mut registry = RuntimeModuleRegistryV1::new();
    let first = abi("pinned.module", 1, None);
    promote(&mut registry, first.clone());
    let second = abi("pinned.module", 2, Some(&first));
    registry.register_candidate(second.clone()).unwrap();
    let third = abi("pinned.module", 3, Some(&first));
    promote(&mut registry, third.clone());
    promote(&mut registry, abi("pinned.module", 4, Some(&third)));
    assert!(registry.record(&first.module_id, first.generation).is_some());
    registry.quarantine(&second.module_id, second.generation).unwrap();
    registry.register_candidate(abi("unrelated.module", 1, None)).unwrap();
    assert!(registry.record(&first.module_id, first.generation).is_none());
}
