use super::*;
use crate::RuntimeModuleRetirementWitnessV1;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn abi() -> RuntimeModuleAbiV1 {
    RuntimeModuleAbiV1 {
        module_id: StableId::new("automation.taskflow").expect("module"),
        owner_id: StableId::new("automation-platform").expect("owner"),
        generation: Generation::new(7).expect("generation"),
        implementation_digest: Digest32::of_bytes(b"image"),
        candidate_artifact_digest: Digest32::of_bytes(b"candidate"),
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class: RuntimeModuleStateClassV1::Stateful,
        dependencies: vec![],
        input_ports: vec![],
        output_ports: vec![],
        authoritative_domains: [StableId::new("automation_schedule").expect("domain")]
            .into_iter()
            .collect(),
        effect_scope: Default::default(),
    }
}

#[test]
fn selection_reads_do_not_mutate_and_retirement_survives_owner_reopen() {
    let temp = tempfile::tempdir().expect("temporary owner");
    let path = temp.path().join("modules.json");
    let mut owner = DurableRuntimeModuleSupervisorV1::open(&path).expect("open");
    let module = abi();
    assert!(
        owner
            .module_selection("automation.taskflow")
            .expect("absent")
            .selected
            .is_none()
    );
    owner
        .register_bootstrap(module.clone())
        .expect("reviewed bootstrap");
    let bytes = std::fs::read(&path).expect("durable bytes");
    let selected = owner
        .module_selection("automation.taskflow")
        .expect("selected");
    assert_eq!(selected.selected.as_ref().expect("binding").generation, 7);
    assert_eq!(std::fs::read(&path).expect("unchanged"), bytes);
    assert!(owner.module_selection("../bad").is_err());
    drop(owner);
    let mut owner = DurableRuntimeModuleSupervisorV1::open(&path).expect("reopen");
    assert_eq!(
        owner
            .module_selection("automation.taskflow")
            .expect("recovered"),
        selected
    );
    let mut witness = RuntimeModuleRetirementWitnessV1 {
        drain_digest: Digest32::of_bytes(b"owner-drain"),
        reconciliation_digest: Digest32::of_bytes(b"owner-reconciliation"),
        unknown_effect_count: 1,
    };
    assert!(
        owner
            .retire_after_reconciliation(&module.module_id, module.generation, witness.clone())
            .is_err()
    );
    assert_eq!(
        owner
            .module_selection("automation.taskflow")
            .expect("still active"),
        selected
    );
    witness.unknown_effect_count = 0;
    owner
        .retire_after_reconciliation(&module.module_id, module.generation, witness)
        .expect("trusted retirement witness");
    assert!(
        owner
            .module_selection("automation.taskflow")
            .expect("retired")
            .selected
            .is_none()
    );
    drop(owner);
    let mut reopened = DurableRuntimeModuleSupervisorV1::open(&path).expect("retired reopen");
    assert!(
        reopened
            .module_selection("automation.taskflow")
            .expect("absent after restart")
            .selected
            .is_none()
    );
    assert!(
        reopened.register_bootstrap(module).is_err(),
        "old generation cannot resurrect"
    );
}
