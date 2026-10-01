use super::super::AgentdPromptRuntimeOwner;
use super::super::LOCK_FILE;
use super::super::NEXT_FILE;
use super::super::STATE_FILE;
use super::*;

#[cfg(unix)]
fn staged_attachment_fixture() -> (
    super::super::PromptRuntimeKey,
    codex_hepta_codex_adapter::PromptRuntimeAttachmentV1,
) {
    use codex_hepta_codex_adapter::PromptRuntimeAttachmentV1;
    use codex_hepta_codex_adapter::PromptRuntimeDeveloperFragmentV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    let attachment = PromptRuntimeAttachmentV1::new(
        StableId::new("compilation:protected-runtime").expect("compilation"),
        Digest32::of_bytes(b"attachment"),
        Digest32::of_bytes(b"payload"),
        "gpt-test",
        /*deadline_ms*/ 10_000,
        vec![PromptRuntimeDeveloperFragmentV1::new("Verify before dispatch.").expect("fragment")],
    )
    .expect("attachment");
    let key = super::super::PromptRuntimeKey {
        thread_id: "thread:protected-runtime".to_owned(),
        turn_id: "turn:protected-runtime".to_owned(),
    };
    (key, attachment)
}

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
fn open_fifo_without_waiting(
    fifo: &Path,
    opener: impl FnOnce() -> Result<(), AgentdPromptRuntimeError> + Send + 'static,
) -> Result<(), AgentdPromptRuntimeError> {
    use std::os::unix::fs::OpenOptionsExt;
    use std::sync::mpsc;
    use std::time::Duration;

    let (sender, receiver) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        sender.send(opener()).expect("send guarded open result");
    });
    let observed = receiver.recv_timeout(Duration::from_secs(/*secs*/ 2));
    if observed.is_err() {
        // Release a regressed blocking reader before reporting its original
        // timeout, so the negative regression cannot leave a hung worker.
        let keeper = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(fifo)
            .expect("release regressed FIFO reader");
        receiver
            .recv_timeout(Duration::from_secs(/*secs*/ 2))
            .expect("regressed reader finishes after cleanup keeper");
        drop(keeper);
    }
    worker.join().expect("open worker exits");
    observed.expect("FIFO replacement must not wait for a writer")
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
    let before_state = owner.state.lock().expect("state snapshot").clone();
    let (key, attachment) = staged_attachment_fixture();
    assert_eq!(
        owner.commit_state(|state| {
            state.staged.insert(key, attachment);
            Ok(())
        }),
        Err(AgentdPromptRuntimeError::CorruptState)
    );
    assert_eq!(*owner.state.lock().expect("unchanged state"), before_state);
    assert_eq!(target_snapshot(&target), before);
    assert_eq!(
        fs::read_link(root.join(NEXT_FILE)).expect("retained symlink"),
        target
    );
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

#[cfg(unix)]
#[test]
fn inspected_state_fifo_replacement_does_not_wait_for_a_writer() {
    use std::process::Command;

    let temporary = tempfile::tempdir().expect("private fixture");
    let directory = PromptDirectory::open(temporary.path()).expect("private runtime directory");
    let path = directory.path.join(STATE_FILE);
    let mut source = directory
        .open_mutable(STATE_FILE)
        .expect("regular state file");
    std::io::Write::write_all(&mut source.file, b"original state bytes").expect("state bytes");
    drop(source);
    let before = fs::symlink_metadata(&path).expect("inspected state file");
    validate_file(&before, &directory.before).expect("regular state admission");
    let retained = directory.path.join("retained-state");
    fs::rename(&path, &retained).expect("retain original inode after inspection");
    let retained_before = target_snapshot(&retained);
    assert!(
        Command::new("mkfifo")
            .args(["-m", "600"])
            .arg(&path)
            .status()
            .expect("POSIX mkfifo")
            .success()
    );
    let fifo = path.clone();
    let observed = open_fifo_without_waiting(&fifo, move || {
        directory.open_inspected_existing(path, before).map(|_| ())
    });
    assert_eq!(target_snapshot(&retained), retained_before);
    assert_eq!(observed, Err(AgentdPromptRuntimeError::CorruptState));
}

#[cfg(unix)]
#[test]
fn inspected_directory_fifo_replacement_does_not_wait_for_a_writer() {
    use std::os::unix::fs::MetadataExt;
    use std::process::Command;

    let temporary = tempfile::tempdir().expect("private fixture");
    let directory = PromptDirectory::open(&temporary.path().join("runtime"))
        .expect("private runtime directory");
    let physical = directory.path.clone();
    let before = fs::symlink_metadata(&physical).expect("inspected canonical directory");
    validate_directory(&before).expect("regular directory admission");
    let marker = external_target(&physical);
    let marker_before = target_snapshot(&marker);
    let retained = temporary.path().join("retained-directory");
    fs::rename(&physical, &retained).expect("retain inspected directory");
    assert!(
        Command::new("mkfifo")
            .args(["-m", "600"])
            .arg(&physical)
            .status()
            .expect("POSIX mkfifo")
            .success()
    );
    let fifo = physical.clone();
    assert_eq!(
        open_fifo_without_waiting(&fifo, move || open_directory_handle(&physical).map(|_| ())),
        Err(AgentdPromptRuntimeError::Unavailable)
    );
    let after = fs::symlink_metadata(&retained).expect("retained directory metadata");
    assert_eq!(
        (after.dev(), after.ino(), after.uid(), after.mode()),
        (before.dev(), before.ino(), before.uid(), before.mode())
    );
    assert_eq!(
        target_snapshot(&retained.join("outside-owner-state")),
        marker_before
    );
}

#[cfg(unix)]
#[test]
fn inspected_state_symlink_replacement_is_rejected_without_changing_its_target() {
    let temporary = tempfile::tempdir().expect("private fixture");
    let directory = PromptDirectory::open(temporary.path()).expect("private runtime directory");
    let path = directory.path.join(STATE_FILE);
    let mut source = directory
        .open_mutable(STATE_FILE)
        .expect("regular state file");
    std::io::Write::write_all(&mut source.file, b"original state bytes").expect("state bytes");
    drop(source);
    let before = fs::symlink_metadata(&path).expect("inspected state file");
    validate_file(&before, &directory.before).expect("regular state admission");
    let retained = directory.path.join("retained-state");
    fs::rename(&path, &retained).expect("retain original inode after inspection");
    let retained_before = target_snapshot(&retained);
    std::os::unix::fs::symlink(&retained, &path).expect("replace selected leaf with a symlink");
    assert!(matches!(
        directory.open_inspected_existing(path.clone(), before),
        Err(AgentdPromptRuntimeError::Unavailable)
    ));
    assert_eq!(target_snapshot(&retained), retained_before);
    assert_eq!(
        fs::read_link(path).expect("retained replacement symlink"),
        retained
    );
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
    let retired_before = target_snapshot(&root.join("retired-lock"));
    let replacement_before = target_snapshot(&root.join(LOCK_FILE));
    let before_state = owner.state.lock().expect("state snapshot").clone();
    let (key, attachment) = staged_attachment_fixture();
    assert_eq!(
        owner.commit_state(|state| {
            state.staged.insert(key, attachment);
            Ok(())
        }),
        Err(AgentdPromptRuntimeError::CorruptState)
    );
    assert_eq!(*owner.state.lock().expect("unchanged state"), before_state);
    assert_eq!(target_snapshot(&root.join("retired-lock")), retired_before);
    assert_eq!(target_snapshot(&root.join(LOCK_FILE)), replacement_before);
    assert!(!root.join(NEXT_FILE).exists());
    assert!(!root.join(STATE_FILE).exists());
}

#[cfg(unix)]
#[test]
fn owner_directory_entry_changes_preserve_the_live_store_identity() {
    use std::os::unix::fs::MetadataExt;

    let temporary = tempfile::tempdir().expect("private fixture");
    let root = temporary.path().join("runtime");
    let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("owner");
    let before = fs::metadata(&root).expect("owner directory");
    fs::create_dir(root.join("owner-child")).expect("trusted owner directory entry");
    let after = fs::metadata(&root).expect("same owner directory");
    assert_eq!((after.dev(), after.ino()), (before.dev(), before.ino()));
    let (key, attachment) = staged_attachment_fixture();
    owner
        .commit_state(|state| {
            state.staged.insert(key.clone(), attachment.clone());
            Ok(())
        })
        .expect("publish with a live directory");
    assert!(root.join(STATE_FILE).is_file());
    assert_eq!(owner.staged_count().expect("published staged count"), 1);
    drop(owner);
    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen published state");
    assert_eq!(reopened.staged_count().expect("staged count"), 1);
    assert_eq!(
        reopened
            .state
            .lock()
            .expect("persisted state")
            .staged
            .get(&key),
        Some(&attachment)
    );
}
