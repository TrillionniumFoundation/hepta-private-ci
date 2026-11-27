use super::*;

#[test]
fn native_owner_reopens_and_rejects_a_second_writer() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("registry");
    let registry =
        DurablePromptRegistry::open_state_dir(&root, 16).expect("private native registry");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&root, 16),
        Err(DurableRegistryError::StateLocked)
    ));
    let digest = registry
        .registry()
        .expect("authoritative registry")
        .snapshot_digest();
    drop(registry);
    let reopened = DurablePromptRegistry::open_state_dir(&root, 16).expect("native reopen");
    assert_eq!(
        reopened
            .registry()
            .expect("reopened authoritative registry")
            .snapshot_digest(),
        digest
    );
}

#[test]
fn native_post_rename_failure_poisoning_requires_reopen() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("registry");
    let mut registry =
        DurablePromptRegistry::open_state_dir(&root, 16).expect("private native registry");
    registry.fail_directory_sync_after_rename_once();
    let factor = PromptFactor {
        factor_id: StableId::new("factor:native").expect("factor id"),
        proposer_id: StableId::new("proposer:native").expect("proposer id"),
        semantic_version: StableId::new("v1").expect("semantic version"),
        semantic_purpose: "synthetic durability qualification".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![StableId::new("dimension:truth").expect("dimension")],
        content_digest: Digest32::of_bytes(b"synthetic factor"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    let factor_id = factor.factor_id.clone();
    assert!(matches!(
        registry.register_factor(factor),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    assert!(registry.requires_reopen());
    assert!(matches!(
        registry.registry(),
        Err(DurableRegistryError::ReopenRequired)
    ));
    drop(registry);
    let reopened =
        DurablePromptRegistry::open_state_dir(&root, 16).expect("reconcile after real rename");
    assert!(
        reopened
            .registry()
            .expect("reconciled registry")
            .factor(&factor_id)
            .is_some()
    );
}
