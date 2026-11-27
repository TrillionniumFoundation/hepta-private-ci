use super::Access;
use super::PrivateDirectory;
use super::PrivateSqliteDirectory;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use std::process::Command;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;

#[path = "windows_private_owner_tests.rs"]
mod owner;

#[test]
fn writable_directory_handle_executes_the_real_flush() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let ordinary = fs::File::open(temporary.path());
    println!(
        "ordinary_directory_open={:?}",
        ordinary
            .as_ref()
            .err()
            .and_then(std::io::Error::raw_os_error)
    );
    let directory = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(0x0200_0000 | 0x0020_0000)
        .open(temporary.path())
        .expect("writable BACKUP_SEMANTICS directory");
    let result = directory.sync_all();
    println!(
        "writable_directory_flush={:?}",
        result.as_ref().err().and_then(std::io::Error::raw_os_error)
    );
    result.expect("real directory flush must succeed, not be ignored");
}

#[test]
fn private_state_replaces_atomically_and_reopens_with_the_same_acl() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("private");
    {
        let directory = PrivateDirectory::prepare(&root).expect("private NTFS directory");
        assert!(!directory.contains("state.json").expect("missing state"));
        let mut original = directory
            .open("state.json", Access::Create)
            .expect("original");
        original.write_all(b"old").expect("old bytes");
        original.sync_all().expect("old flush");
        drop(original);
        let mut old_reader = directory
            .open("state.json", Access::Read)
            .expect("old reader");
        let mut candidate = directory
            .open("state.next", Access::Create)
            .expect("candidate");
        candidate.write_all(b"new").expect("new bytes");
        candidate.sync_all().expect("new flush");
        directory
            .replace("state.next", "state.json")
            .expect("handle-relative atomic rename");
        directory.sync_all().expect("directory namespace flush");
        let mut bytes = Vec::new();
        old_reader
            .read_to_end(&mut bytes)
            .expect("retained old reader");
        assert_eq!(bytes, b"old");
        assert!(!directory.contains("state.next").expect("source renamed"));
    }
    let reopened = PrivateDirectory::prepare(&root).expect("same owner/DACL after reopen");
    let mut bytes = Vec::new();
    reopened
        .open("state.json", Access::Read)
        .expect("new state")
        .read_to_end(&mut bytes)
        .expect("new bytes");
    assert_eq!(bytes, b"new");
}

#[test]
fn private_directory_preserves_exclusive_writer_locking() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let directory =
        PrivateDirectory::prepare(&temporary.path().join("private")).expect("private directory");
    let first = directory
        .open("owner.lock", Access::Create)
        .expect("first lock");
    let second = directory
        .open("owner.lock", Access::Create)
        .expect("second lock");
    first.try_lock().expect("first exclusive writer");
    assert!(second.try_lock().is_err());
    drop(first);
    second.try_lock().expect("released writer lock");
}

#[test]
fn strict_private_inspection_cannot_create_write_replace_or_flush() -> std::io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    let directory = PrivateDirectory::create_new(&root)?;
    let mut original = directory.open("state", Access::CreateNew)?;
    original.write_all(b"retained")?;
    original.sync_all()?;
    drop(original);
    directory.sync_all()?;
    assert!(matches!(
        PrivateDirectory::create_new(&root),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists
    ));
    let read_only = PrivateDirectory::inspect(&root)?;
    let mut observed = Vec::new();
    read_only
        .open("state", Access::Read)?
        .read_to_end(&mut observed)?;
    assert_eq!(observed, b"retained");
    for access in [Access::Write, Access::Create, Access::CreateNew] {
        assert!(matches!(
            read_only.open("state", access),
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied
        ));
    }
    assert!(matches!(
        read_only.replace("state", "other"),
        Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied
    ));
    assert!(matches!(
        read_only.sync_all(),
        Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied
    ));
    assert!(!root.join("other").exists());
    assert_eq!(fs::read(root.join("state"))?, b"retained");
    PrivateDirectory::open_existing(&root)?.sync_all()?;
    assert!(PrivateDirectory::open_existing(&temporary.path().join("missing")).is_err());
    assert!(!temporary.path().join("missing").exists());
    Ok(())
}

#[test]
fn sqlite_directory_create_new_never_adopts_existing_roots() -> std::io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    let directory = PrivateSqliteDirectory::create_new(&root)?;
    let mut file = directory.open("kept.sqlite3", Access::CreateNew)?;
    file.write_all(b"unchanged")?;
    file.sync_all()?;
    drop(file);
    directory.sync_all()?;
    let before = directory.snapshot()?;
    let broad = temporary.path().join("ordinary");
    fs::create_dir(&broad)?;
    for existing in [&root, &broad] {
        let reader = OpenOptions::new()
            .access_mode(windows_sys::Win32::Storage::FileSystem::READ_CONTROL)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(existing)?;
        let security = owner::FileSecurity::read(&reader)?;
        assert!(matches!(
            PrivateSqliteDirectory::create_new(existing),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists
        ));
        assert!(security.unchanged(&owner::FileSecurity::read(&reader)?));
    }
    assert_eq!(directory.snapshot()?, before);
    assert_eq!(fs::read(root.join("kept.sqlite3"))?, b"unchanged");
    Ok(())
}

#[test]
fn sqlite_inheritance_is_owner_only_and_does_not_weaken_the_default_policy() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("sqlite");
    let directory = PrivateSqliteDirectory::prepare(&root).expect("private SQLite root");
    let root_reader = OpenOptions::new()
        .access_mode(windows_sys::Win32::Storage::FileSystem::READ_CONTROL)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(&root)
        .expect("read-only fixture security handle");
    let root_security = owner::FileSecurity::read(&root_reader).expect("validated root security");
    // NULL SECURITY_ATTRIBUTES inherits the DACL, but its default owner need
    // not equal TokenUser. Independently observe that owner before predicting
    // the validator's result; neither outcome permits an ACL/owner repair.
    for name in ["ordinary.sqlite3", "ordinary.sqlite3-wal"] {
        fs::write(root.join(name), b"ordinary").expect("ordinary native creation");
        let source = fs::File::open(root.join(name)).expect("fixture reader");
        let before = owner::FileSecurity::read(&source).expect("original owner and DACL");
        assert!(before.has_inherited_owner_ace(&root_security));
        let owner_matches_user = before.same_owner(&root_security);
        println!("ordinary_creation_owner_matches_effective_user={owner_matches_user}");
        match directory.open(name, Access::Read) {
            Ok(_) => assert!(owner_matches_user, "a foreign owner must be rejected"),
            Err(error) => {
                assert!(
                    !owner_matches_user,
                    "valid owner and inherited DACL: {error}"
                );
                assert_eq!(error.kind(), std::io::ErrorKind::PermissionDenied);
            }
        }
        let after = owner::FileSecurity::read(&source).expect("security after inspection");
        assert!(
            before.unchanged(&after),
            "inspection must not repair security"
        );
        assert_eq!(
            fs::read(root.join(name)).expect("unchanged bytes"),
            b"ordinary"
        );
    }
    // Creation-time explicit owner with an absent DACL inherits the root ACE.
    // This is a synthetic native fixture, not a claim about unmodified SQLite.
    for name in ["explicit.sqlite3", "explicit.sqlite3-wal"] {
        let mut file = root_security
            .create_with_inherited_dacl(&root.join(name))
            .expect("creation-time owner and inherited DACL");
        file.write_all(b"explicit").expect("fixture bytes");
        file.sync_all().expect("fixture flush");
        let security = owner::FileSecurity::read(&file).expect("created file security");
        assert!(security.same_owner(&root_security));
        assert!(security.has_inherited_owner_ace(&root_security));
        directory
            .open(name, Access::Read)
            .expect("private inherited file");
        assert_eq!(fs::read(root.join(name)).expect("exact bytes"), b"explicit");
    }
    assert!(
        PrivateDirectory::prepare(&root).is_err(),
        "strict non-inheriting policy is unchanged"
    );
    let strict_root = temporary.path().join("strict");
    let strict = PrivateDirectory::prepare(&strict_root).expect("strict directory");
    strict
        .open("database.sqlite3", Access::CreateNew)
        .expect("explicit private file");
    PrivateSqliteDirectory::inspect(&strict_root)
        .expect("read-only strict root inspection")
        .open("database.sqlite3", Access::Read)
        .expect("explicit private file inspection");
    assert!(
        PrivateSqliteDirectory::open_writable(&strict_root).is_err(),
        "writing sidecars requires explicit inheritance policy"
    );
}

#[test]
fn sqlite_inspection_never_creates_repairs_or_flushes_source_objects() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("sqlite");
    let writer = PrivateSqliteDirectory::prepare(&root).expect("private root");
    fs::write(root.join("database.sqlite3"), b"original").expect("source");
    let before = writer.snapshot().expect("before");
    let inspected = PrivateSqliteDirectory::inspect(&root).expect("read-only inspection");
    assert_eq!(inspected.snapshot().expect("after"), before);
    assert!(inspected.open("must-not-exist", Access::CreateNew).is_err());
    assert!(
        inspected.sync_all().is_err(),
        "inspection is never a write-flush capability"
    );
    assert!(!root.join("must-not-exist").exists());
    assert!(PrivateSqliteDirectory::inspect(&temporary.path().join("missing")).is_err());
    assert!(!temporary.path().join("missing").exists());
    let broad = temporary.path().join("ordinary");
    fs::create_dir(&broad).expect("ordinary inherited root");
    assert!(PrivateSqliteDirectory::inspect(&broad).is_err());
    assert!(
        PrivateSqliteDirectory::prepare(&broad).is_err(),
        "existing ACL is not repaired"
    );
    assert_eq!(
        fs::read(root.join("database.sqlite3")).expect("source bytes"),
        b"original"
    );
}

#[test]
fn sqlite_snapshots_detect_drift_and_failed_candidate_cleanup_binds_the_handle() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("sqlite");
    let directory = PrivateSqliteDirectory::prepare(&root).expect("private root");
    let mut original = directory
        .open("candidate", Access::CreateNew)
        .expect("candidate");
    original.write_all(b"old").expect("old bytes");
    original.sync_all().expect("flush");
    let snapshot = directory
        .file_snapshot(&original)
        .expect("original snapshot");
    fs::write(root.join("candidate"), b"changed length").expect("source drift");
    assert!(
        directory
            .verify_file("candidate", &original, snapshot)
            .is_err()
    );
    directory
        .replace("candidate", "retained")
        .expect("move original");
    directory
        .open("candidate", Access::CreateNew)
        .expect("replacement")
        .write_all(b"replacement")
        .expect("replacement bytes");
    directory
        .remove_created(original)
        .expect("remove the actual original by handle");
    assert!(!root.join("retained").exists());
    assert_eq!(
        fs::read(root.join("candidate")).expect("replacement survives"),
        b"replacement"
    );
    let before = directory.snapshot().expect("root snapshot");
    fs::write(root.join("sidecar"), b"new namespace entry").expect("sidecar");
    assert!(directory.verify_unchanged(&before).is_err());
}

#[test]
fn sqlite_namespace_witness_restarts_and_covers_multiple_native_pages() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("sqlite");
    let directory = PrivateSqliteDirectory::prepare(&root).expect("private root");
    // More than 64 KiB of native directory records; every capture must restart
    // and continue enumeration, without changing the current directory or using paths.
    for index in 0..300 {
        let name = format!("entry-{index:03}-{}", "x".repeat(180));
        directory
            .open(&name, Access::CreateNew)
            .expect("private entry");
    }
    let first = directory.snapshot().expect("complete namespace");
    assert_eq!(directory.snapshot().expect("restarted namespace"), first);
    let name = format!("entry-299-{}", "x".repeat(180));
    directory
        .replace(&name, "last-entry-renamed")
        .expect("rename last entry");
    assert!(directory.verify_unchanged(&first).is_err());
    let renamed = directory.snapshot().expect("new namespace");
    assert_eq!(
        directory.snapshot().expect("stable renamed namespace"),
        renamed
    );
}

#[test]
fn sqlite_canonical_name_comes_from_the_validated_handle() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("MiXeD-private");
    let directory = PrivateSqliteDirectory::prepare(&root).expect("private root");
    let canonical = directory
        .canonical_path()
        .expect("same-handle canonical name");
    assert_eq!(canonical, root.canonicalize().expect("OS canonical name"));
    let before = directory.snapshot().expect("private identity");
    for spelling in [
        root,
        canonical.clone(),
        temporary.path().join("mixed-private"),
    ] {
        let reopened = PrivateSqliteDirectory::inspect(&spelling).expect("same native directory");
        assert_eq!(
            reopened.canonical_path().expect("canonical name"),
            canonical
        );
        assert_eq!(reopened.snapshot().expect("same identity"), before);
    }
}

#[test]
fn one_character_target_uses_a_complete_rename_header() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let directory =
        PrivateDirectory::prepare(&temporary.path().join("private")).expect("private directory");
    let mut source = directory
        .open("n", Access::Create)
        .expect("one-character source");
    source.write_all(b"short leaf").expect("candidate bytes");
    source.sync_all().expect("candidate flush");
    directory
        .replace("n", "x")
        .expect("one-character target rename");
    directory.sync_all().expect("namespace flush");
    let mut bytes = Vec::new();
    directory
        .open("x", Access::Read)
        .expect("renamed file")
        .read_to_end(&mut bytes)
        .expect("renamed bytes");
    assert_eq!(bytes, b"short leaf");
}

#[test]
fn reparse_root_and_reparse_ancestor_never_reach_the_target() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let target = temporary.path().join("target");
    fs::create_dir(&target).expect("junction target");
    fs::write(target.join("marker"), b"unchanged").expect("target marker");
    let junction = temporary.path().join("redirect");
    let output = Command::new("cmd")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&junction)
        .arg(&target)
        .output()
        .expect("native junction tool");
    assert!(output.status.success(), "junction creation: {output:?}");
    assert!(PrivateDirectory::prepare(&junction).is_err());
    assert!(PrivateDirectory::prepare(&junction.join("child")).is_err());
    assert!(PrivateDirectory::create_new(&junction).is_err());
    assert!(PrivateDirectory::create_new(&junction.join("child")).is_err());
    assert!(PrivateDirectory::inspect(&junction).is_err());
    assert!(PrivateDirectory::open_existing(&junction).is_err());
    assert!(PrivateSqliteDirectory::inspect(&junction).is_err());
    assert!(PrivateSqliteDirectory::inspect(&junction.join("child")).is_err());
    assert!(PrivateSqliteDirectory::create_new(&junction).is_err());
    assert!(PrivateSqliteDirectory::create_new(&junction.join("child")).is_err());
    assert!(!target.join("child").exists());
    assert_eq!(
        fs::read(target.join("marker")).expect("unchanged target"),
        b"unchanged"
    );
    fs::remove_dir(junction).expect("remove only the junction");
}

#[test]
fn hard_links_and_non_leaf_names_are_rejected_before_editing() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("private");
    let directory = PrivateDirectory::prepare(&root).expect("private directory");
    let mut file = directory
        .open("source", Access::Create)
        .expect("private source");
    file.write_all(b"unchanged").expect("source bytes");
    file.sync_all().expect("source flush");
    drop(file);
    fs::hard_link(root.join("source"), temporary.path().join("alias"))
        .expect("synthetic hard link");
    assert!(directory.open("source", Access::Write).is_err());
    for name in [
        "../source",
        "source:stream",
        "sub/source",
        "sub\\source",
        "..",
        "",
    ] {
        assert!(
            directory.open(name, Access::Create).is_err(),
            "unsafe leaf: {name}"
        );
    }
    assert_eq!(
        fs::read(temporary.path().join("alias")).expect("retained bytes"),
        b"unchanged"
    );
}

#[test]
fn reparse_child_cannot_be_opened_or_used_as_a_replacement_target() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("private");
    let directory = PrivateDirectory::prepare(&root).expect("private directory");
    let target = temporary.path().join("target");
    fs::create_dir(&target).expect("external fixture directory");
    fs::write(target.join("marker"), b"unchanged").expect("fixture marker");
    let junction = root.join("redirect");
    let result = Command::new("cmd")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&junction)
        .arg(&target)
        .output()
        .expect("native junction tool");
    assert!(result.status.success(), "junction creation: {result:?}");
    assert!(directory.open("redirect", Access::Create).is_err());
    directory
        .open("candidate", Access::Create)
        .expect("private candidate");
    assert!(directory.replace("candidate", "redirect").is_err());
    assert!(
        directory
            .contains("candidate")
            .expect("candidate retained on rejection")
    );
    assert_eq!(
        fs::read(target.join("marker")).expect("retained target bytes"),
        b"unchanged"
    );
    fs::remove_dir(junction).expect("remove only the synthetic junction");
}

#[test]
fn broad_existing_dacl_is_rejected_without_automatic_repair() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("private");
    let directory = PrivateDirectory::prepare(&root).expect("new owner-only directory");
    // Only this disposable, content-free fixture is widened. No user/service
    // credential directory or existing machine ACL is read or changed.
    let result = Command::new("icacls")
        .arg(&root)
        .args(["/grant", "*S-1-1-0:(R)"])
        .output()
        .expect("native ACL fixture tool");
    assert!(result.status.success(), "synthetic ACL edit: {result:?}");
    assert!(
        directory
            .open("must-not-be-created", Access::Create)
            .is_err()
    );
    assert!(!root.join("must-not-be-created").exists());
    drop(directory);
    let before = Command::new("icacls")
        .arg(&root)
        .output()
        .expect("fixture ACL before");
    assert!(PrivateDirectory::prepare(&root).is_err());
    let after = Command::new("icacls")
        .arg(&root)
        .output()
        .expect("fixture ACL after");
    assert_eq!(
        before.stdout, after.stdout,
        "rejection must not repair an existing ACL"
    );
}

#[test]
fn retained_directory_cannot_be_rebound_by_path_rename() {
    let temporary = tempfile::tempdir().expect("synthetic directory");
    let root = temporary.path().join("private");
    let directory = PrivateDirectory::prepare(&root).expect("private directory");
    assert!(fs::rename(&root, temporary.path().join("moved")).is_err());
    directory
        .open("still-bound", Access::Create)
        .expect("retained root binding");
    assert!(root.join("still-bound").is_file());
}
