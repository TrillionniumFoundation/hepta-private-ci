use super::*;
use crate::TestMust;
use pretty_assertions::assert_eq;

fn factor(name: &str) -> PromptFactor {
    PromptFactor {
        factor_id: StableId::new(name).must("factor id"),
        proposer_id: StableId::new("proposer:windows").must("proposer id"),
        semantic_version: StableId::new("v1").must("version"),
        semantic_purpose: "Windows durable owner recovery".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![StableId::new("dimension:truth").must("dimension")],
        content_digest: Digest32::of_bytes(name.as_bytes()),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }
}

#[test]
fn windows_owner_is_exclusive_and_reopens_the_exact_committed_registry() {
    let temp = tempfile::tempdir().must("tempdir");
    let root = temp.path().join("registry");
    let mut owner =
        DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64).must("open");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64),
        Err(DurableRegistryError::StateLocked)
    ));
    let factor = factor("factor:persisted");
    owner.register_factor(factor.clone()).must("commit");
    let digest = owner.registry().must("registry").snapshot_digest();
    drop(owner);
    let reopened =
        DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64).must("reopen");
    let registry = reopened.registry().must("registry");
    assert_eq!(registry.snapshot_digest(), digest);
    assert_eq!(registry.factor(&factor.factor_id), Some(&factor));
}

#[test]
fn windows_post_rename_sync_failure_poisoning_requires_real_reopen() {
    let temp = tempfile::tempdir().must("tempdir");
    let root = temp.path().join("registry");
    let mut owner =
        DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64).must("open");
    let committed = factor("factor:indeterminate");
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.register_factor(committed.clone()),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    assert!(owner.requires_reopen());
    assert!(matches!(
        owner.registry(),
        Err(DurableRegistryError::ReopenRequired)
    ));
    assert!(matches!(
        owner.register_factor(factor("factor:forbidden-while-poisoned")),
        Err(DurableRegistryError::ReopenRequired)
    ));
    drop(owner);
    let reopened =
        DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64).must("reconcile");
    assert_eq!(
        reopened
            .registry()
            .must("registry")
            .factor(&committed.factor_id),
        Some(&committed)
    );
}

#[test]
fn windows_precommit_failure_and_truncated_snapshot_remain_fail_closed() {
    let temp = tempfile::tempdir().must("tempdir");
    let root = temp.path().join("registry");
    let mut owner =
        DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64).must("open");
    let predecessor = factor("factor:predecessor");
    owner
        .register_factor(predecessor)
        .must("commit predecessor");
    let digest = owner.registry().must("registry").snapshot_digest();
    let bytes = std::fs::read(root.join("registry.json")).must("snapshot");
    owner.fail_storage_full_before_rename_once();
    assert!(matches!(
        owner.register_factor(factor("factor:failed")),
        Err(DurableRegistryError::StorageFull)
    ));
    assert!(!owner.requires_reopen());
    assert_eq!(owner.registry().must("registry").snapshot_digest(), digest);
    drop(owner);
    assert_eq!(
        std::fs::read(root.join("registry.json")).must("unchanged"),
        bytes
    );
    let reopened = DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64)
        .must("reopen predecessor");
    assert_eq!(
        reopened.registry().must("registry").snapshot_digest(),
        digest
    );
    drop(reopened);
    std::fs::write(root.join("registry.json"), &bytes[..bytes.len() / 2]).must("truncate");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64),
        Err(DurableRegistryError::Corrupt)
    ));
}
