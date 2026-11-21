use std::ffi::OsString;
use std::fs;

use super::DurablePromptRegistry;
use super::DurableRegistryError;

#[test]
fn unsupported_platform_open_does_not_create_registry_state() -> std::io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("registry");
    assert!(!root.try_exists()?);

    let opened = DurablePromptRegistry::open_state_dir(&root, 64);

    assert!(matches!(
        opened,
        Err(DurableRegistryError::UnsafeStateDirectory)
    ));
    assert!(!root.try_exists()?);
    assert!(fs::read_dir(temporary.path())?.next().is_none());
    Ok(())
}

#[test]
fn unsupported_platform_open_preserves_existing_directory_on_retry() -> std::io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("registry");
    fs::create_dir(&root)?;
    let sentinel = root.join("sentinel");
    let original = b"existing state must remain unchanged";
    fs::write(&sentinel, original)?;

    for _ in 0..2 {
        let opened = DurablePromptRegistry::open_state_dir(&root, 64);
        assert!(matches!(
            opened,
            Err(DurableRegistryError::UnsafeStateDirectory)
        ));
    }

    let entries = fs::read_dir(&root)?
        .map(|entry| entry.map(|entry| entry.file_name()))
        .collect::<std::io::Result<Vec<_>>>()?;
    assert_eq!(entries, vec![OsString::from("sentinel")]);
    assert_eq!(fs::read(&sentinel)?, original.to_vec());
    Ok(())
}
