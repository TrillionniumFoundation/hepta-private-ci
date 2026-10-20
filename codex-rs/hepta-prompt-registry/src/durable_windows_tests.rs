
use super::*;

#[test]
fn full_private_registry_roundtrip_reopens_without_resetting_owner_history() {
    let temporary = tempfile::tempdir().expect("temporary owner");
    let root = temporary.path().join("registry");
    let original = super::super::DurablePromptRegistry::open_state_dir(&root, 64)
        .expect("real retained Windows registry startup");
    let digest = original
        .registry()
        .expect("initialized registry")
        .snapshot_digest();
    drop(original);
    let recovered = super::super::DurablePromptRegistry::open_state_dir(&root, 64)
        .expect("reopen the exact persisted authoritative registry");
    assert_eq!(
        recovered
            .registry()
            .expect("recovered registry")
            .snapshot_digest(),
        digest
    );
    drop(recovered);

    // A newly created file alias must fail closed even when the bytes are
    // canonical. Never repair the hardlink or fabricate an empty registry.
    std::fs::hard_link(root.join("registry.json"), root.join("linked-registry"))
        .expect("NTFS hardlink fixture");
    assert!(matches!(
        super::super::DurablePromptRegistry::open_state_dir(&root, 64),
        Err(DurableRegistryError::UnsafeStateDirectory)
    ));
}

#[test]
fn hard_link_is_rejected_before_registry_bytes_are_read() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("registry");
    let directory = prepare_directory(&root).expect("private directory");
    drop(open_private(&directory, "registry.json", Access::Create).expect("private child"));
    std::fs::hard_link(root.join("registry.json"), root.join("other")).expect("create hard link");
    assert!(matches!(
        open_private(&directory, "registry.json", Access::Read),
        Err(DurableRegistryError::UnsafeStateDirectory)
    ));
}
