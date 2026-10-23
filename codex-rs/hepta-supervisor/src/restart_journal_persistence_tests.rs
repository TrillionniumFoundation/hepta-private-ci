use std::cell::Cell;
use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;

use super::*;

fn companion(attempts: u32) -> RestartBudgetJournal {
    RestartBudgetJournal::new(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
        ReleaseId::parse("release-a").expect("release"),
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts,
            window_started_unix_millis: (attempts > 0).then_some(2_000),
        },
    )
    .expect("journal")
}

fn identity(file: &File) -> (u64, u64, i64, i64, u64) {
    let metadata = file.metadata().expect("metadata");
    (
        metadata.dev(),
        metadata.ino(),
        metadata.mtime(),
        metadata.mtime_nsec(),
        metadata.len(),
    )
}

#[test]
fn identical_canonical_records_preserve_inode_and_mtime_without_losing_main_state() {
    let dir = tempfile::tempdir().expect("temp");
    let journal = companion(0);
    write_restart_journal(dir.path(), &journal).expect("initial publication");
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let original = File::open(&path).expect("hold original inode");
    let original_identity = identity(&original);
    for _ in 0..8 {
        write_restart_journal(dir.path(), &journal).expect("durable unchanged journal");
        assert_eq!(
            identity(&File::open(&path).expect("current")),
            original_identity
        );
    }

    let main = RestartBudgetState {
        schema_version: 1,
        window_started_unix_ms: 2_000,
        attempts: 2,
        pending: true,
        next_eligible_unix_ms: 2_050,
    };
    write_main_restart_budget(dir.path(), &main).expect("real main mutation");
    let with_main = File::open(&path).expect("hold main publication");
    let with_main_identity = identity(&with_main);
    assert_ne!(with_main_identity.1, original_identity.1);
    write_restart_journal(dir.path(), &journal).expect("fresh merge preserves main");
    assert_eq!(
        identity(&File::open(&path).expect("current")),
        with_main_identity
    );
    assert_eq!(
        read_main_restart_budget(dir.path()).expect("main"),
        Some(main)
    );

    let changed = companion(1);
    write_restart_journal(dir.path(), &changed).expect("real companion mutation");
    assert_ne!(
        identity(&File::open(&path).expect("changed")).1,
        with_main_identity.1
    );
    assert_eq!(
        read_restart_journal(dir.path()).expect("companion"),
        Some(changed)
    );
}

#[test]
fn legacy_equivalent_projection_is_still_migrated_to_canonical_bytes() {
    let dir = tempfile::tempdir().expect("temp");
    let journal = companion(1);
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    std::fs::write(&path, serde_json::to_vec(&journal).expect("legacy bytes")).expect("legacy");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).expect("private");
    let legacy = File::open(&path).expect("hold legacy");
    write_restart_journal(dir.path(), &journal).expect("canonical migration");
    assert_ne!(
        identity(&File::open(&path).expect("canonical")).1,
        identity(&legacy).1
    );
    let canonical: RestartRecord =
        serde_json::from_slice(&std::fs::read(path).expect("bytes")).expect("canonical codec");
    canonical.validate().expect("canonical checksum");
    assert_eq!(canonical.companion, Some(journal));
}

#[test]
fn corrupt_existing_record_is_not_repaired_by_an_unchanged_write() {
    let dir = tempfile::tempdir().expect("temp");
    let journal = companion(0);
    write_restart_journal(dir.path(), &journal).expect("initial");
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let corrupt = b"{\"schema_version\":2,\"record_sha256\":\"invalid\"}";
    std::fs::write(&path, corrupt).expect("corrupt");
    assert!(write_restart_journal(dir.path(), &journal).is_err());
    assert_eq!(
        std::fs::read(path).expect("retained corrupt evidence"),
        corrupt
    );
}

#[test]
fn descriptor_binding_rejects_a_file_replaced_after_path_validation() {
    let dir = tempfile::tempdir().expect("temp");
    write_restart_journal(dir.path(), &companion(0)).expect("initial");
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let validated = std::fs::symlink_metadata(&path).expect("path validated");
    let original = File::open(&path).expect("retain original inode");
    let replacement = dir.path().join("replacement.json");
    let bytes = std::fs::read(&path).expect("canonical bytes");
    std::fs::write(&replacement, &bytes).expect("replacement");
    std::fs::rename(replacement, &path).expect("replace between validation and open");

    assert!(open_record_file(&path, &validated).is_err());
    assert_eq!(std::fs::read(&path).expect("unchanged replacement"), bytes);
    assert_ne!(
        identity(&original).1,
        identity(&File::open(path).expect("current")).1
    );
}

#[test]
fn descriptor_binding_rejects_symlink_to_identical_canonical_bytes() {
    let dir = tempfile::tempdir().expect("temp");
    let journal = companion(0);
    write_restart_journal(dir.path(), &journal).expect("initial");
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let validated = std::fs::symlink_metadata(&path).expect("path validated");
    let outside = dir.path().join("different-record.json");
    std::fs::rename(&path, &outside).expect("move original record");
    let original = File::open(&outside).expect("retain original");
    let original_identity = identity(&original);
    std::os::unix::fs::symlink(&outside, &path).expect("substitute symlink");

    assert!(open_record_file(&path, &validated).is_err());
    assert!(write_restart_journal(dir.path(), &journal).is_err());
    assert_eq!(identity(&original), original_identity);
    assert!(
        std::fs::symlink_metadata(path)
            .expect("retained link")
            .is_symlink()
    );
}

#[test]
fn visible_rename_after_directory_sync_failure_is_not_a_durable_acknowledgement() {
    let dir = tempfile::tempdir().expect("temp");
    let journal = companion(0);
    write_restart_journal(dir.path(), &journal).expect("initial");
    let mut changed = read_record(dir.path()).expect("read").expect("record");
    changed.companion = Some(companion(1));

    let unknown = write_record_with_io(
        dir.path(),
        changed.clone(),
        |staging, destination| {
            // The original staging file has already been synchronized. Model
            // the real publication cut after rename but before directory ACK.
            std::fs::rename(staging, destination)?;
            Err(std::io::Error::other("injected directory sync failure"))
        },
        |_, _| panic!("changed record cannot use unchanged synchronization"),
    );
    assert!(unknown.is_err());
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let visible = File::open(&path).expect("visible unacknowledged publication");
    let visible_identity = identity(&visible);
    assert_eq!(
        read_restart_journal(dir.path()).expect("visible"),
        Some(companion(1))
    );

    let sync_attempted = Cell::new(false);
    let still_unknown = write_record_with_io(
        dir.path(),
        changed.clone(),
        |_, _| panic!("identical bytes must not be republished"),
        |file, parent| {
            assert_eq!(identity(file), visible_identity);
            assert!(parent.metadata().expect("held parent").is_dir());
            file.sync_all()?;
            sync_attempted.set(true);
            Err(std::io::Error::other(
                "injected repeated directory sync failure",
            ))
        },
    );
    assert!(still_unknown.is_err());
    assert!(sync_attempted.get());
    write_record(dir.path(), changed).expect("real file and directory synchronization");
    assert_eq!(
        identity(&File::open(path).expect("durable current")),
        visible_identity
    );
}
