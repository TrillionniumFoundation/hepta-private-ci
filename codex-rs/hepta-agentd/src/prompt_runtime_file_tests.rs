
use super::super::AgentdPromptRuntimeOwner;
use super::super::LOCK_FILE;
use super::super::NEXT_FILE;
use super::super::STATE_FILE;
use super::*;

#[cfg(unix)]
fn external_target(root: &Path) -> PathBuf {
    use std::os::unix::fs::PermissionsExt;

    let target = root.join("outside-owner-state");
    fs::write(&target, b"external contents must survive").expect("external target");
    fs::set_permissions(&target, fs::Permissions::from_mode(0o644)).expect("external mode");
    target
}

#[cfg(unix)]
fn target_snapshot(path: &Path) -> (Vec<u8>, u32) {
    use std::os::unix::fs::MetadataExt;

    (
        fs::read(path).expect("external contents"),
        fs::symlink_metadata(path)
            .expect("external metadata")
            .mode()
            & 0o777,
    )
}

#[cfg(unix)]
#[test]
fn lock_symlink_rejection_preserves_external_contents_and_permissions() {
    use std::os::unix::fs::symlink;

    let temporary = tempfile::tempdir().expect("private fixture");
    let root = temporary.path().join("runtime");
    PromptDirectory::open(&root).expect("private runtime directory");
    let target = external_target(temporary.path());
    let before = target_snapshot(&target);
    symlink(&target, root.join(LOCK_FILE)).expect("pre-existing lock symlink");
    assert!(matches!(
        AgentdPromptRuntimeOwner::open_state_dir(&root),
        Err(AgentdPromptRuntimeError::CorruptState)
    ));
    assert_eq!(target_snapshot(&target), before);
}

#[cfg(unix)]
#[test]
fn next_symlink_rejection_preserves_external_contents_and_permissions() {
    use std::os::unix::fs::symlink;

    let temporary = tempfile::tempdir().expect("private fixture");
    let root = temporary.path().join("runtime");
    let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("owner");
    let target = external_target(temporary.path());
    let before = target_snapshot(&target);
    symlink(&target, root.join(NEXT_FILE)).expect("pre-existing next symlink");
    assert_eq!(
        owner.commit_state(|_| Ok(())),
        Err(AgentdPromptRuntimeError::CorruptState)
    );
    assert_eq!(target_snapshot(&target), before);
    assert!(!root.join(STATE_FILE).exists());
}

#[cfg(unix)]
#[test]
fn state_symlink_is_rejected_without_reading_or_changing_its_target() {
    use std::os::unix::fs::symlink;

    let temporary = tempfile::tempdir().expect("private fixture");
    let root = temporary.path().join("runtime");
    PromptDirectory::open(&root).expect("private runtime directory");
    let target = external_target(temporary.path());
    let before = target_snapshot(&target);
    symlink(&target, root.join(STATE_FILE)).expect("state symlink");
    assert!(matches!(
        AgentdPromptRuntimeOwner::open_state_dir(&root),
        Err(AgentdPromptRuntimeError::CorruptState)
    ));
    assert_eq!(target_snapshot(&target), before);
}

#[cfg(unix)]
#[test]
fn hard_linked_mutable_files_are_rejected_before_truncation() {
    use std::os::unix::fs::PermissionsExt;

    let temporary = tempfile::tempdir().expect("private fixture");
    let target = external_target(temporary.path());
    fs::set_permissions(&target, fs::Permissions::from_mode(0o600)).expect("private target mode");
    let before = target_snapshot(&target);
    for name in [LOCK_FILE, NEXT_FILE] {
        let root = temporary.path().join(name);
        let directory = PromptDirectory::open(&root).expect("private runtime directory");
        fs::hard_link(&target, root.join(name)).expect("hard-link alias");
        assert!(matches!(
            directory.open_mutable(name),
            Err(AgentdPromptRuntimeError::CorruptState)
        ));
        assert_eq!(target_snapshot(&target), before);
    }
}

#[test]
fn nonregular_mutable_paths_are_rejected() {
    for name in [LOCK_FILE, NEXT_FILE] {
        let temporary = tempfile::tempdir().expect("private fixture");
        fs::create_dir(temporary.path().join(name)).expect("nonregular store entry");
        let directory = PromptDirectory::open(temporary.path()).expect("private runtime directory");
        assert!(matches!(
            directory.open_mutable(name),
            Err(AgentdPromptRuntimeError::CorruptState)
        ));
    }
}

#[cfg(unix)]
#[test]
fn directory_symlink_rejection_preserves_external_directory_permissions() {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    let temporary = tempfile::tempdir().expect("private fixture");
    let target = temporary.path().join("external");
    fs::create_dir(&target).expect("external directory");
    fs::set_permissions(&target, fs::Permissions::from_mode(0o755)).expect("external mode");
    let alias = temporary.path().join("runtime");
    symlink(&target, &alias).expect("runtime directory symlink");
    assert!(matches!(
        AgentdPromptRuntimeOwner::open_state_dir(&alias),
        Err(AgentdPromptRuntimeError::CorruptState)
    ));
    assert_eq!(
        fs::metadata(target).expect("external metadata").mode() & 0o777,
        0o755
    );
}

#[cfg(unix)]
#[test]
fn file_replacement_after_open_is_rejected_before_publication() {
    let temporary = tempfile::tempdir().expect("private fixture");
    let directory = PromptDirectory::open(temporary.path()).expect("private runtime directory");
    let next = directory.open_mutable(NEXT_FILE).expect("next snapshot");
    fs::rename(
        temporary.path().join(NEXT_FILE),
        temporary.path().join("parked"),
    )
    .expect("park opened file");
    directory.open_mutable(NEXT_FILE).expect("replacement file");
    assert_eq!(
        directory.publish(&next, STATE_FILE),
        Err(AgentdPromptRuntimeError::CorruptState)
    );
    assert!(!temporary.path().join(STATE_FILE).exists());
}

#[test]
fn normal_owner_sequence_preserves_lock_and_reopens_exact_staged_state() {
    use codex_hepta_codex_adapter::PromptRuntimeAttachmentV1;
    use codex_hepta_codex_adapter::PromptRuntimeDeveloperFragmentV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    let temporary = tempfile::tempdir().expect("private fixture");
    let root = temporary.path().join("runtime");
    let attachment = PromptRuntimeAttachmentV1::new(
        StableId::new("compilation:protected-runtime").expect("compilation"),
        Digest32::of_bytes(b"attachment"),
        Digest32::of_bytes(b"payload"),
        "gpt-test",
        10_000,
        vec![PromptRuntimeDeveloperFragmentV1::new("Verify before dispatch.").expect("fragment")],
    )
    .expect("attachment");
    let key = super::super::PromptRuntimeKey {
        thread_id: "thread:protected-runtime".to_owned(),
        turn_id: "turn:protected-runtime".to_owned(),
    };
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("owner");
        assert!(matches!(
            AgentdPromptRuntimeOwner::open_state_dir(&root),
            Err(AgentdPromptRuntimeError::StateLocked)
        ));
        let mut stale = owner
            .store
            .as_ref()
            .expect("durable store")
            .root
            .open_mutable(NEXT_FILE)
            .expect("uncommitted predecessor file");
        std::io::Write::write_all(&mut stale.file, b"stale incomplete publication bytes")
            .expect("uncommitted predecessor bytes");
        drop(stale);
        owner
            .commit_state(|state| {
                state.staged.insert(key.clone(), attachment.clone());
                Ok(())
            })
            .expect("persist first staged state");
        assert_eq!(owner.staged_count().expect("staged count"), 1);
    }
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen staged owner");
        let state = owner.state.lock().expect("state lock");
        assert_eq!(state.staged.get(&key), Some(&attachment));
        drop(state);
        owner
            .commit_state(|state| {
                state.staged.remove(&key);
                Ok(())
            })
            .expect("persist removal");
    }
    let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen final owner");
    assert_eq!(owner.staged_count().expect("final staged count"), 0);
}

#[cfg(unix)]
#[test]
fn a_replaced_lock_inode_cannot_publish_under_the_retired_lock() {
    let temporary = tempfile::tempdir().expect("private fixture");
    let root = temporary.path().join("runtime");
    let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("owner");
    fs::rename(root.join(LOCK_FILE), root.join("retired-lock")).expect("retire lock inode");
    owner
        .store
        .as_ref()
        .expect("durable store")
        .root
        .open_mutable(LOCK_FILE)
        .expect("replacement lock inode");
    assert_eq!(
        owner.commit_state(|_| Ok(())),
        Err(AgentdPromptRuntimeError::CorruptState)
    );
    assert!(!root.join(STATE_FILE).exists());
}
