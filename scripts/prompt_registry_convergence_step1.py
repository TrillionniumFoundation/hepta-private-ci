#!/usr/bin/env python3
# Triggered only after the one-shot workflow exists in the branch history.
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if new in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"expected one replacement in {path}, found {text.count(old)}")
    target.write_text(text.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-prompt-registry/src/durable.rs",
    """    pub fn open_state_dir(
        directory: &Path,
        maximum_records: usize,
    ) -> Result<Self, DurableRegistryError> {
        let (mut store, stored) = Store::open(directory)?;
""",
    """    pub fn open_state_dir(
        directory: &Path,
        maximum_records: usize,
    ) -> Result<Self, DurableRegistryError> {
        // Validate caller policy before touching the state directory. A rejected
        // first open must not leave a lock sentinel that makes a corrected retry
        // look like a previously initialized store whose manifest disappeared.
        if maximum_records == 0 {
            return Err(DurableRegistryError::Core(Error::ZeroCapacity));
        }
        let (mut store, stored) = Store::open(directory)?;
""",
)

replace_once(
    "codex-rs/hepta-prompt-registry/src/durable.rs",
    """                || !active_profiles.insert((
                    binding.factor_id.clone(),
                    binding.model_digest,
                    binding.tokenizer_digest,
""",
    """                || !active_profiles.insert((
                    binding.factor_id.clone(),
                    binding.model_id.clone(),
                    binding.model_version.clone(),
                    binding.model_digest,
                    binding.tokenizer_digest,
""",
)

path = Path("codex-rs/hepta-prompt-registry/src/durable_payloads_tests.rs")
text = path.read_text()
if "fn distinct_model_versions_remain_reopenable()" not in text:
    text += r'''

#[test]
fn distinct_model_versions_remain_reopenable() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner.commit(|core| add_payload(core, 0)).must("first profile");

    let current = owner.registry().must("current");
    let mut second = current
        .realization_bindings
        .get(&id("realization:0"))
        .must("first binding")
        .clone();
    let payload = current
        .realization_payloads
        .get(&id("realization:0"))
        .must("first payload")
        .to_vec();
    second.realization_id = id("realization:second-version");
    second.model_version = "v2".into();
    owner
        .register_realization_payload_v2(second, payload, None)
        .must("second model version");
    let expected = owner.registry().must("registry").clone();
    drop(owner);

    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen");
    assert_eq!(reopened.registry().must("registry"), &expected);
}

#[test]
fn rejected_first_configuration_leaves_directory_retryable() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&path, 0),
        Err(DurableRegistryError::Core(Error::ZeroCapacity))
    ));
    assert!(!path.join("registry.lock").exists());
    assert!(!path.join("registry.json").exists());

    let owner = DurablePromptRegistry::open_state_dir(&path, 64).must("corrected retry");
    assert_eq!(owner.registry().must("registry").revision().get(), 1);
}
'''
    path.write_text(text)
