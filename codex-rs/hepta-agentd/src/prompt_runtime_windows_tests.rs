use std::io::Write;
use std::sync::atomic::Ordering;

use anyhow::Result;
use codex_utils_path::windows_private_fs::PrivateDirectory;
use pretty_assertions::assert_eq;

use super::AgentdPromptRuntimeError;
use super::NEXT_FILE;
use super::PromptRuntimeState;
use super::PromptRuntimeStore;
use super::STATE_FILE;

#[test]
fn runtime_store_reopens_and_keeps_its_retained_directory_after_rename() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("runtime");
    let retained_path = temp.path().join("retained");
    let (store, state) = PromptRuntimeStore::open(&path)?;
    assert_eq!(state, PromptRuntimeState::default());
    assert!(matches!(
        PromptRuntimeStore::open(&path),
        Err(AgentdPromptRuntimeError::StateLocked)
    ));
    std::fs::rename(&path, &retained_path)?;
    let replacement = PrivateDirectory::open_or_create(&path)?;
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
