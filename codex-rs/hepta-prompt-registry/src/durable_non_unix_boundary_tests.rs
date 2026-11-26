use crate::DurablePromptRegistry;
use crate::DurableRegistryError;
use crate::TestMust;

#[test]
fn unsupported_backend_refuses_new_store_without_creating_state() {
    let temporary = tempfile::tempdir().must("temporary owner root");
    let root = temporary.path().join("registry");

    let result = DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64);

    assert!(matches!(
        result,
        Err(DurableRegistryError::UnsafeStateDirectory)
    ));
    assert!(!root.exists());
    let entries = std::fs::read_dir(temporary.path())
        .must("read owner root")
        .collect::<std::io::Result<Vec<_>>>()
        .must("read owner entries");
    assert!(entries.is_empty());
}

#[test]
fn unsupported_backend_refuses_existing_store_without_mutating_owner_bytes() {
    let temporary = tempfile::tempdir().must("temporary owner root");
    let root = temporary.path().join("registry");
    std::fs::create_dir(&root).must("create existing registry root");
    let marker = root.join("owner-state");
    let original = b"pre-existing owner state";
    std::fs::write(&marker, original).must("seed owner bytes");

    let result = DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64);

    assert!(matches!(
        result,
        Err(DurableRegistryError::UnsafeStateDirectory)
    ));
    assert_eq!(
        std::fs::read(&marker).must("read owner bytes"),
        original.to_vec()
    );
    let entries = std::fs::read_dir(&root)
        .must("read registry root")
        .map(|entry| entry.map(|entry| entry.file_name()))
        .collect::<std::io::Result<Vec<_>>>()
        .must("read registry entries");
    assert_eq!(entries, vec![std::ffi::OsString::from("owner-state")]);
    let owner_entries = std::fs::read_dir(temporary.path())
        .must("read owner root")
        .map(|entry| entry.map(|entry| entry.file_name()))
        .collect::<std::io::Result<Vec<_>>>()
        .must("read owner entries");
    assert_eq!(owner_entries, vec![std::ffi::OsString::from("registry")]);
}
