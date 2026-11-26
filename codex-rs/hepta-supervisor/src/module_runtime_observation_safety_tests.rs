use super::*;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;

#[test]
fn serving_absence_does_not_erase_quiescing_or_quarantined_reservations() {
    let module_id = StableId::new("feature.sample").expect("module");
    let generation = Generation::new(1).expect("generation");
    let mut owner = RuntimeModuleSupervisorV1::new();
    owner
        .register_bootstrap(RuntimeModuleAbiV1 {
            module_id: module_id.clone(),
            owner_id: StableId::new("feature-owner").expect("owner"),
            generation,
            implementation_digest: Digest32::of_bytes(b"image"),
            candidate_artifact_digest: Digest32::of_bytes(b"candidate"),
            predecessor_generation: None,
            rollback_predecessor_digest: Digest32::ZERO,
            state_class: RuntimeModuleStateClassV1::Stateful,
            dependencies: vec![],
            input_ports: vec![],
            output_ports: vec![],
            authoritative_domains: [StableId::new("sample_data").expect("domain")]
                .into_iter()
                .collect(),
            effect_scope: Default::default(),
        })
        .expect("bootstrap");
    assert_eq!(
        owner.selected_module_phase(&module_id).expect("phase"),
        Some(RuntimeModuleLifecycleV1::Active)
    );
    owner
        .registry
        .begin_retire(&module_id, generation)
        .expect("drain");
    assert!(owner.topology().active.is_empty());
    assert_eq!(
        owner.selected_module_phase(&module_id).expect("phase"),
        Some(RuntimeModuleLifecycleV1::Quiescing)
    );
    owner
        .registry
        .quarantine(&module_id, generation)
        .expect("quarantine");
    assert!(owner.topology().active.is_empty());
    assert_eq!(
        owner.selected_module_phase(&module_id).expect("phase"),
        Some(RuntimeModuleLifecycleV1::Quarantined)
    );
    let restored =
        RuntimeModuleSupervisorV1::restore_checkpoint(owner.checkpoint()).expect("recovery");
    assert!(restored.topology().active.is_empty());
    assert_eq!(
        restored
            .selected_module_phase(&module_id)
            .expect("recovered phase"),
        Some(RuntimeModuleLifecycleV1::Quarantined)
    );
}
