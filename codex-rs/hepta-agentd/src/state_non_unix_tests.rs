//! Unsupported-platform qualification must prove fail-closed behavior.
//! No permission-agnostic substitute for a Windows ACL owner is allowed.

#[test]
fn prompt_registry_rejects_non_unix_serving_without_private_owner() {
    use codex_hepta_prompt_registry::DurablePromptRegistry;
    use codex_hepta_prompt_registry::DurableRegistryError;

    let directory = tempfile::tempdir().expect("test directory");
    let path = directory.path().join("prompt-registry");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 16),
        Err(DurableRegistryError::UnsafeStateDirectory)
    ));
}
