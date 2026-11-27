//! Secure prompt admission requires the existing durable owner platform contract.

use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;

#[test]
fn unsupported_prompt_owner_does_not_publish_payloads_or_admission_state() {
    let temporary = tempfile::tempdir().expect("prompt owner fixture");
    let directory = temporary.path().join("registry");
    let result = DurablePromptRegistry::open_state_dir(&directory, /*maximum_records*/ 64);
    assert!(matches!(
        result,
        Err(DurableRegistryError::UnsafeStateDirectory)
    ));
    assert!(!directory.exists());
}
