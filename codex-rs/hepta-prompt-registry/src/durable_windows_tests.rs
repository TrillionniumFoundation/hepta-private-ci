use super::DurablePromptRegistry;
use super::DurableRegistryError;
use crate::FactorSource;
use crate::Lifecycle;
use crate::PromptFactor;
use crate::TestMust;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

fn factor() -> PromptFactor {
    PromptFactor {
        factor_id: StableId::new("factor:windows").must("factor id"),
        proposer_id: StableId::new("proposer:windows").must("proposer id"),
        semantic_version: StableId::new("v1").must("semantic version"),
        semantic_purpose: "preserve durable state across restart".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![StableId::new("dimension:truth").must("dimension")],
        content_digest: Digest32::of_bytes(b"windows factor"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }
}

#[test]
fn native_windows_registry_reopens_exact_mutation_and_fences_second_writer() {
    let temporary = tempfile::tempdir().must("temporary root");
    let root = temporary.path().join("registry");
    let mut first = DurablePromptRegistry::open_state_dir(&root, 64).must("open owner");
    first.register_factor(factor()).must("durable mutation");
    let digest = first.registry().must("registry").snapshot_digest();
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&root, 64),
        Err(DurableRegistryError::StateLocked)
    ));
    drop(first);
    let recovered = DurablePromptRegistry::open_state_dir(&root, 64).must("recover owner");
    assert_eq!(
        recovered.registry().must("registry").snapshot_digest(),
        digest
    );
    assert_eq!(
        recovered
            .registry()
            .must("registry")
            .factor(&factor().factor_id),
        Some(&factor())
    );
}

#[test]
fn native_windows_post_rename_failure_poisoning_survives_recovery() {
    let temporary = tempfile::tempdir().must("temporary root");
    let root = temporary.path().join("registry");
    let mut owner = DurablePromptRegistry::open_state_dir(&root, 64).must("open owner");
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.register_factor(factor()),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    assert!(owner.requires_reopen());
    assert!(matches!(
        owner.registry(),
        Err(DurableRegistryError::ReopenRequired)
    ));
    drop(owner);
    let recovered = DurablePromptRegistry::open_state_dir(&root, 64).must("reconcile rename");
    assert_eq!(
        recovered
            .registry()
            .must("registry")
            .factor(&factor().factor_id),
        Some(&factor())
    );
}

#[test]
fn native_windows_precommit_storage_failure_retains_predecessor() {
    let temporary = tempfile::tempdir().must("temporary root");
    let root = temporary.path().join("registry");
    let mut owner = DurablePromptRegistry::open_state_dir(&root, 64).must("open owner");
    let digest = owner.registry().must("registry").snapshot_digest();
    owner.fail_storage_full_before_rename_once();
    assert!(matches!(
        owner.register_factor(factor()),
        Err(DurableRegistryError::StorageFull)
    ));
    assert!(!owner.requires_reopen());
    assert_eq!(owner.registry().must("registry").snapshot_digest(), digest);
    drop(owner);
    let recovered = DurablePromptRegistry::open_state_dir(&root, 64).must("recover predecessor");
    assert_eq!(
        recovered.registry().must("registry").snapshot_digest(),
        digest
    );
}

#[test]
fn native_windows_corrupt_payload_header_is_rejected() {
    let temporary = tempfile::tempdir().must("temporary root");
    let root = temporary.path().join("registry");
    let owner = DurablePromptRegistry::open_state_dir(&root, 64).must("open owner");
    drop(owner);
    let payload_path = root.join("registry.payloads");
    let mut bytes = std::fs::read(&payload_path).must("original payload header");
    bytes[0] ^= 1;
    std::fs::write(payload_path, bytes).must("corrupt fixture");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&root, 64),
        Err(DurableRegistryError::Corrupt)
    ));
}
