//! Restore preserves selected writer reservations; checksums are not lifecycle proofs.

use std::collections::BTreeSet;

use pretty_assertions::assert_eq;

use super::*;
use crate::RuntimeModuleAbiV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture identity")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid fixture generation")
}

fn abi(value: u64, predecessor: Option<u64>) -> RuntimeModuleAbiV1 {
    RuntimeModuleAbiV1 {
        module_id: id("module.persisted"),
        owner_id: id("owner.persisted"),
        generation: generation(value),
        implementation_digest: Digest32::of_bytes(format!("implementation:{value}").as_bytes()),
        candidate_artifact_digest: Digest32::of_bytes(format!("artifact:{value}").as_bytes()),
        predecessor_generation: predecessor.map(generation),
        rollback_predecessor_digest: predecessor
            .map(|previous| Digest32::of_bytes(format!("implementation:{previous}").as_bytes()))
            .unwrap_or(Digest32::ZERO),
        state_class: RuntimeModuleStateClassV1::Stateful,
        dependencies: Vec::new(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: BTreeSet::from([id("domain.persisted")]),
        effect_scope: BTreeSet::new(),
    }
}

fn selected_registry() -> Result<RuntimeModuleRegistryV1, RuntimeModuleRegistryError> {
    let mut registry = RuntimeModuleRegistryV1::new();
    registry.register_candidate(abi(/*value*/ 1, /*predecessor*/ None))?;
    registry.activate_bootstrap(&id("module.persisted"), generation(/*value*/ 1))?;
    Ok(registry)
}

#[test]
fn active_record_cannot_restore_without_its_reservation() -> Result<(), RuntimeModuleRegistryError>
{
    let mut checkpoint = selected_registry()?.checkpoint();
    checkpoint.active_reservations.clear();
    checkpoint.checkpoint_digest = checkpoint_digest(&checkpoint);
    assert!(matches!(
        RuntimeModuleRegistryV1::restore_checkpoint(checkpoint),
        Err(RuntimeModuleRegistryError::CheckpointInvalid)
    ));
    Ok(())
}

#[test]
fn quiescing_record_cannot_restore_without_its_reservation()
-> Result<(), RuntimeModuleRegistryError> {
    let mut registry = selected_registry()?;
    registry.begin_retire(&id("module.persisted"), generation(/*value*/ 1))?;
    let mut checkpoint = registry.checkpoint();
    checkpoint.active_reservations.clear();
    checkpoint.checkpoint_digest = checkpoint_digest(&checkpoint);
    assert!(matches!(
        RuntimeModuleRegistryV1::restore_checkpoint(checkpoint),
        Err(RuntimeModuleRegistryError::CheckpointInvalid)
    ));
    Ok(())
}

#[test]
fn another_selected_generation_does_not_cover_an_orphan_active_record()
-> Result<(), RuntimeModuleRegistryError> {
    let mut registry = selected_registry()?;
    registry.register_candidate(abi(/*value*/ 2, /*predecessor*/ Some(1)))?;
    let mut checkpoint = registry.checkpoint();
    let successor = checkpoint
        .records
        .iter_mut()
        .find(|record| record.abi.generation == generation(/*value*/ 2))
        .expect("registered successor");
    successor.lifecycle = RuntimeModuleLifecycleV1::Active;
    checkpoint.checkpoint_digest = checkpoint_digest(&checkpoint);
    assert!(matches!(
        RuntimeModuleRegistryV1::restore_checkpoint(checkpoint),
        Err(RuntimeModuleRegistryError::CheckpointInvalid)
    ));
    Ok(())
}

#[test]
fn unselected_quarantined_candidate_keeps_its_valid_checkpoint()
-> Result<(), RuntimeModuleRegistryError> {
    let mut registry = RuntimeModuleRegistryV1::new();
    registry.register_candidate(abi(/*value*/ 1, /*predecessor*/ None))?;
    registry.quarantine(&id("module.persisted"), generation(/*value*/ 1))?;
    let checkpoint = registry.checkpoint();
    let restored = RuntimeModuleRegistryV1::restore_checkpoint(checkpoint.clone())?;
    assert_eq!(restored.checkpoint(), checkpoint);
    assert_eq!(restored.active_generation(&id("module.persisted")), None);
    Ok(())
}

#[test]
fn selected_quarantined_writer_keeps_its_reservation_after_restore()
-> Result<(), RuntimeModuleRegistryError> {
    let mut registry = selected_registry()?;
    registry.quarantine(&id("module.persisted"), generation(/*value*/ 1))?;
    let checkpoint = registry.checkpoint();
    let restored = RuntimeModuleRegistryV1::restore_checkpoint(checkpoint.clone())?;
    assert_eq!(restored.checkpoint(), checkpoint);
    assert_eq!(
        restored.active_generation(&id("module.persisted")),
        Some(generation(/*value*/ 1))
    );
    assert!(restored.snapshot().active.is_empty());
    Ok(())
}

#[test]
fn retired_record_without_reservation_keeps_its_valid_checkpoint()
-> Result<(), RuntimeModuleRegistryError> {
    let mut registry = selected_registry()?;
    registry.begin_retire(&id("module.persisted"), generation(/*value*/ 1))?;
    registry.finish_retire(&id("module.persisted"), generation(/*value*/ 1))?;
    let checkpoint = registry.checkpoint();
    let restored = RuntimeModuleRegistryV1::restore_checkpoint(checkpoint.clone())?;
    assert_eq!(restored.checkpoint(), checkpoint);
    assert_eq!(restored.active_generation(&id("module.persisted")), None);
    Ok(())
}
