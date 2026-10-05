use std::collections::BTreeSet;

use pretty_assertions::assert_eq;

use super::super::RuntimeModuleAbiV1;
use super::super::RuntimeModuleStateClassV1;
use super::*;

type Error = RuntimeModuleRegistryError;
type InvalidCase = (fn(&mut RuntimeModuleRegistryCheckpointV1), Error);
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn abi(name: &str, value: u64, previous: Option<&RuntimeModuleAbiV1>) -> RuntimeModuleAbiV1 {
    RuntimeModuleAbiV1 {
        module_id: id(name),
        owner_id: id("owner.persisted"),
        generation: generation(value),
        implementation_digest: digest(&format!("implementation:{value}")),
        candidate_artifact_digest: digest(&format!("candidate:{value}")),
        predecessor_generation: previous.map(|abi| abi.generation),
        rollback_predecessor_digest: previous
            .map_or(Digest32::ZERO, |abi| abi.implementation_digest),
        state_class: RuntimeModuleStateClassV1::Stateful,
        dependencies: Vec::new(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: BTreeSet::from([id(&format!("domain.{name}"))]),
        effect_scope: BTreeSet::new(),
    }
}
fn bootstrap(registry: &mut RuntimeModuleRegistryV1, value: RuntimeModuleAbiV1) {
    registry.register_candidate(value.clone()).unwrap();
    registry
        .activate_bootstrap(&value.module_id, value.generation)
        .unwrap();
}
fn resign(checkpoint: &mut RuntimeModuleRegistryCheckpointV1) {
    checkpoint.checkpoint_digest = Digest32::of_bytes(&codec::encode(checkpoint));
}
fn restore(
    checkpoint: RuntimeModuleRegistryCheckpointV1,
) -> Result<RuntimeModuleRegistryV1, Error> {
    let current = checkpoint.checkpoint_digest;
    RuntimeModuleRegistryV1::restore_checkpoint(checkpoint, current)
}
fn active() -> RuntimeModuleRegistryV1 {
    let mut registry = RuntimeModuleRegistryV1::new();
    bootstrap(
        &mut registry,
        abi("persisted", /*value*/ 1, /*previous*/ None),
    );
    registry
}

#[test]
fn disabled_writers_and_pending_candidates_survive_reopen() {
    for lifecycle in [
        RuntimeModuleLifecycleV1::Quiescing,
        RuntimeModuleLifecycleV1::Quarantined,
    ] {
        let mut registry = active();
        if lifecycle == RuntimeModuleLifecycleV1::Quiescing {
            registry
                .begin_retire(&id("persisted"), generation(1))
                .unwrap();
        } else {
            registry
                .quarantine(&id("persisted"), generation(1))
                .unwrap();
        }
        registry
            .register_candidate(abi("pending", /*value*/ 1, /*previous*/ None))
            .unwrap();
        let before = registry.checkpoint();
        let mut restored = RuntimeModuleRegistryV1::restore_checkpoint_bytes(
            &registry.checkpoint_bytes(),
            before.checkpoint_digest,
        )
        .unwrap();
        assert_eq!(restored.checkpoint(), before);
        assert!(restored.snapshot().active.is_empty());
        let mut conflict = abi("conflict", /*value*/ 1, /*previous*/ None);
        conflict.authoritative_domains = BTreeSet::from([id("domain.persisted")]);
        restored.register_candidate(conflict.clone()).unwrap();
        assert_eq!(
            restored.activate_bootstrap(&conflict.module_id, conflict.generation),
            Err(Error::AuthoritativeWriterConflict(id("domain.persisted")))
        );
        if lifecycle == RuntimeModuleLifecycleV1::Quarantined {
            restored
                .begin_retire(&id("persisted"), generation(1))
                .unwrap();
        }
        restored
            .finish_retire(&id("persisted"), generation(1))
            .unwrap();
        restored
            .activate_bootstrap(&conflict.module_id, conflict.generation)
            .unwrap();
    }
}

#[test]
fn stale_valid_backup_cannot_replace_current_retirement_or_quarantine() {
    let mut live = active();
    let old = live.checkpoint();
    live.quarantine(&id("persisted"), generation(1)).unwrap();
    let current = live.checkpoint();
    assert_eq!(
        RuntimeModuleRegistryV1::restore_checkpoint(old, current.checkpoint_digest).unwrap_err(),
        Error::CheckpointNotCurrent
    );
    assert_eq!(live.checkpoint(), current);
    let mut tampered = current.clone();
    tampered.active_reservations.clear();
    assert_eq!(
        RuntimeModuleRegistryV1::restore_checkpoint(tampered.clone(), current.checkpoint_digest)
            .unwrap_err(),
        Error::CheckpointDigestMismatch
    );
    resign(&mut tampered);
    assert_eq!(
        RuntimeModuleRegistryV1::restore_checkpoint(tampered, current.checkpoint_digest)
            .unwrap_err(),
        Error::CheckpointNotCurrent
    );
    assert_eq!(
        RuntimeModuleRegistryV1::restore_checkpoint(current.clone(), Digest32::ZERO).unwrap_err(),
        Error::CheckpointNotCurrent
    );
    assert_eq!(live.checkpoint(), current);
    live.begin_retire(&id("persisted"), generation(1)).unwrap();
    live.finish_retire(&id("persisted"), generation(1)).unwrap();
    let retired = live.checkpoint();
    assert_eq!(
        RuntimeModuleRegistryV1::restore_checkpoint(current, retired.checkpoint_digest)
            .unwrap_err(),
        Error::CheckpointNotCurrent,
    );
    assert_eq!(live.checkpoint(), retired);
}

#[test]
fn structurally_invalid_checkpoints_fail_even_with_matching_roots() {
    let original = active().checkpoint();
    let cases: Vec<InvalidCase> = vec![
        (|c| c.active_reservations.clear(), Error::CheckpointInvalid),
        (|c| c.records.clear(), Error::CheckpointInvalid),
        (
            |c| c.records[0].lifecycle = RuntimeModuleLifecycleV1::Registered,
            Error::CheckpointInvalid,
        ),
        (|c| c.generation_fences.clear(), Error::CheckpointInvalid),
        (
            |c| c.generation_fences[0].first_generation = generation(2),
            Error::CheckpointInvalid,
        ),
        (
            |c| c.records.push(c.records[0].clone()),
            Error::CheckpointDuplicate,
        ),
        (
            |c| c.active_reservations.push(c.active_reservations[0].clone()),
            Error::CheckpointDuplicate,
        ),
        (
            |c| c.generation_fences.push(c.generation_fences[0].clone()),
            Error::CheckpointDuplicate,
        ),
        (
            |c| c.records[0].selection_digest = Some(digest("partial")),
            Error::MissingPromotionEvidence,
        ),
        (
            |c| c.records[0].canary_digest = Some(Digest32::ZERO),
            Error::CheckpointInvalid,
        ),
    ];
    for (mutate, expected) in cases {
        let mut malformed = original.clone();
        mutate(&mut malformed);
        resign(&mut malformed);
        assert_eq!(restore(malformed).unwrap_err(), expected);
    }
    let mut conflict = active();
    bootstrap(&mut conflict, abi("other", /*value*/ 1, /*previous*/ None));
    let mut checkpoint = conflict.checkpoint();
    checkpoint.records[0].abi.authoritative_domains =
        checkpoint.records[1].abi.authoritative_domains.clone();
    resign(&mut checkpoint);
    assert_eq!(
        restore(checkpoint).unwrap_err(),
        Error::AuthoritativeWriterConflict(id("domain.persisted"))
    );
}

#[test]
fn retired_identity_cap_survives_compaction_restore_and_allows_existing_identity() {
    let mut registry = RuntimeModuleRegistryV1::new();
    for index in 0..MAX_RUNTIME_MODULE_IDENTITIES {
        let value = abi(
            &format!("retired-{index}"),
            /*value*/ 1,
            /*previous*/ None,
        );
        bootstrap(&mut registry, value.clone());
        registry
            .begin_retire(&value.module_id, value.generation)
            .unwrap();
        registry
            .finish_retire(&value.module_id, value.generation)
            .unwrap();
    }
    let mut restored = restore(registry.checkpoint()).unwrap();
    let before = restored.checkpoint();
    assert_eq!(
        restored.register_candidate(abi("overflow", /*value*/ 1, /*previous*/ None)),
        Err(Error::Bounds)
    );
    assert_eq!(restored.checkpoint(), before);
    assert_eq!(
        restored.register_candidate(abi("retired-0", /*value*/ 1, /*previous*/ None)),
        Err(Error::InvalidGeneration)
    );
    restored
        .register_candidate(abi("retired-0", /*value*/ 2, /*previous*/ None))
        .unwrap();
    assert_eq!(
        restored.activate_bootstrap(&id("retired-0"), generation(2)),
        Err(Error::InvalidLifecycleTransition)
    );
    assert_eq!(
        restored.greatest_admitted_generation(&id("retired-0")),
        Some(generation(2))
    );
    let mut excessive = before;
    excessive
        .generation_fences
        .push(RuntimeModuleGenerationFenceV1 {
            module_id: id("overflow"),
            first_generation: generation(1),
            greatest_generation: generation(1),
        });
    assert_eq!(restore(excessive).unwrap_err(), Error::Bounds);
}

#[test]
fn collection_abi_and_pending_bounds_are_checked_before_restore() {
    let original = active().checkpoint();
    for mutate in [
        (|c: &mut RuntimeModuleRegistryCheckpointV1| {
            c.records = vec![c.records[0].clone(); MAX_RETAINED_RUNTIME_RECORDS + 1]
        }) as fn(&mut RuntimeModuleRegistryCheckpointV1),
        |c| c.active_reservations = vec![c.active_reservations[0].clone(); MAX_RUNTIME_MODULES + 1],
        |c| {
            c.records[0].abi.dependencies =
                vec![id("dependency"); super::super::MAX_MODULE_DEPENDENCIES + 1]
        },
    ] {
        let mut oversized = original.clone();
        mutate(&mut oversized);
        assert_eq!(restore(oversized).unwrap_err(), Error::Bounds);
    }
    let mut registry = RuntimeModuleRegistryV1::new();
    for index in 0..MAX_PENDING_RUNTIME_MODULES {
        registry
            .register_candidate(abi(
                &format!("pending-{index}"),
                /*value*/ 1,
                /*previous*/ None,
            ))
            .unwrap();
    }
    let mut checkpoint = registry.checkpoint();
    let mut extra = checkpoint.records[0].clone();
    extra.abi.module_id = id("extra");
    checkpoint.records.push(extra);
    checkpoint
        .generation_fences
        .push(RuntimeModuleGenerationFenceV1 {
            module_id: id("extra"),
            first_generation: generation(1),
            greatest_generation: generation(1),
        });
    resign(&mut checkpoint);
    assert_eq!(restore(checkpoint).unwrap_err(), Error::Bounds);
}

#[path = "module_runtime_checkpoint_wire_tests.rs"]
mod wire_tests;
