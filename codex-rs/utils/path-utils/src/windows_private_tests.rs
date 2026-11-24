use super::Access;
use super::PrivateDirectory;
use std::fs;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use std::process::Command;

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
