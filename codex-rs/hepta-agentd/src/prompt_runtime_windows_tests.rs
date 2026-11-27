use std::io::Write;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use anyhow::Result;
use codex_utils_path::windows_private_fs::PrivateDirectory;
use codex_utils_path::windows_private_fs::snapshot_private_file;
use pretty_assertions::assert_eq;

use super::AgentdPromptRuntimeError;
use super::LOCK_FILE;
use super::NEXT_FILE;
use super::PromptRuntimeState;
use super::PromptRuntimeStore;
use super::STATE_FILE;

#[test]
fn runtime_store_rejects_parent_rename_while_its_lock_file_is_open() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("runtime");
    let retained_path = temp.path().join("retained");
    let (store, state) = PromptRuntimeStore::open(&path)?;
    assert_eq!(state, PromptRuntimeState::default());
    assert!(matches!(
        PromptRuntimeStore::open(&path),
        Err(AgentdPromptRuntimeError::StateLocked)
    ));
    store.persist(&state)?;
    let directory_before = snapshot_private_file(store.directory.as_file())?;
    let lock_before = snapshot_private_file(&store._lock)?;
    let bytes_before = std::fs::read(path.join(STATE_FILE))?;
    // MS-FSA forbids renaming a directory with an open child. Keep the live
    // production lock and verify the OS refusal preserves identity and data.
    let error = std::fs::rename(&path, &retained_path).unwrap_err();
    assert_eq!(error.raw_os_error(), Some(5));
    assert!(path.is_dir());
    assert!(!retained_path.exists());
    assert!(directory_before.same_file(&snapshot_private_file(store.directory.as_file())?));
    assert!(lock_before.same_file(&snapshot_private_file(&store._lock)?));
    assert_eq!(std::fs::read(path.join(STATE_FILE))?, bytes_before);
    store.persist(&state)?;
    assert!(matches!(
        PromptRuntimeStore::open(&path),
        Err(AgentdPromptRuntimeError::StateLocked)
    ));
    drop(store);
    let (_reopened, actual) = PromptRuntimeStore::open(&path)?;
    assert_eq!(actual, state);
    Ok(())
}

#[test]
fn runtime_store_reopens_and_keeps_its_retained_directory_after_rename() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("runtime");
    let retained_path = temp.path().join("retained");
    let directory = PrivateDirectory::open_or_create(&path)?;
    // With no open child, the OS permits the rename. Build the store from the
    // original retained directory, then acquire the actual production lock.
    std::fs::rename(&path, &retained_path)?;
    let replacement = PrivateDirectory::open_or_create(&path)?;
    let lock = directory.open_write(LOCK_FILE)?;
    lock.try_lock()?;
    let store = PromptRuntimeStore {
        directory,
        _lock: lock,
        fail_directory_sync_after_rename_once: AtomicBool::new(false),
    };
    let state = PromptRuntimeState::default();
    assert!(matches!(
        PromptRuntimeStore::open(&retained_path),
        Err(AgentdPromptRuntimeError::StateLocked)
    ));
    store.persist(&state)?;
    assert!(!replacement.entry_exists(STATE_FILE)?);
    assert!(retained_path.join(STATE_FILE).exists());
    drop(store);
    let (_reopened, actual) = PromptRuntimeStore::open(&retained_path)?;
    assert_eq!(actual, state);
    Ok(())
}

#[test]
fn runtime_store_rejects_linked_next_file_before_truncating() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("runtime");
    let (store, state) = PromptRuntimeStore::open(&path)?;
    let directory = PrivateDirectory::open_existing(&path)?;
    let mut file = directory.create_new(NEXT_FILE)?;
    file.write_all(b"must remain intact")?;
    file.sync_all()?;
    std::fs::hard_link(path.join(NEXT_FILE), path.join("alias"))?;
    assert_eq!(
        store.persist(&state),
        Err(AgentdPromptRuntimeError::Unavailable)
    );
    assert_eq!(std::fs::read(path.join(NEXT_FILE))?, b"must remain intact");
    assert!(!directory.entry_exists(STATE_FILE)?);
    Ok(())
}

#[test]
fn runtime_store_reports_post_publication_durability_failure() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("runtime");
    let (store, state) = PromptRuntimeStore::open(&path)?;
    store
        .fail_directory_sync_after_rename_once
        .store(true, Ordering::Release);
    assert_eq!(
        store.persist(&state),
        Err(AgentdPromptRuntimeError::IndeterminateDurability)
    );
    assert!(path.join(STATE_FILE).exists());
    drop(store);
    let (_reopened, actual) = PromptRuntimeStore::open(&path)?;
    assert_eq!(actual, state);
    Ok(())
}
