use super::OutputParent;
use crate::durable::secure_read;
use crate::durable::write_private_new;
use crate::test_support::private_tempdir;
use crate::test_support::windows_custody::grant;
use crate::test_support::windows_custody::world_sid;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;

#[test]
fn new_output_is_private_and_existing_destination_is_never_replaced() {
    let temporary = private_tempdir("private create-only output");
    let path = temporary.path().join("assessment");
    write_private_new(&path, b"first").expect("private output and real parent flush");
    assert_eq!(secure_read(&path, 64).unwrap(), b"first");
    assert!(write_private_new(&path, b"second").is_err());
    assert_eq!(secure_read(&path, 64).unwrap(), b"first");
}

#[test]
fn nonprivate_or_missing_output_parent_never_creates_an_artifact() {
    let temporary = private_tempdir("nonprivate output parent");
    let root = temporary.path();
    let parent = OutputParent::open(root).expect("private positive control");
    drop(parent);
    grant(root, world_sid(), FILE_GENERIC_READ, /*flags*/ 0);
    let path = root.join("assessment");
    assert!(write_private_new(&path, b"not written").is_err());
    assert!(!path.exists());
    let missing = root.join("missing");
    assert!(write_private_new(&missing.join("assessment"), b"not written").is_err());
    assert!(!missing.exists());
}

#[test]
fn parent_path_handle_disagreement_rejects_even_when_both_are_private() {
    let first = private_tempdir("first output parent");
    let second = private_tempdir("different private parent");
    let parent = OutputParent::open(first.path()).unwrap();
    parent.verify(first.path()).unwrap();
    OutputParent::open(second.path()).expect("other parent is valid, not a setup failure");
    assert!(parent.verify(second.path()).is_err());
}

#[test]
fn parent_replacement_is_blocked_while_retained_and_possible_after_drop() {
    let temporary = private_tempdir("pinned output parent");
    let root = temporary.path().join("output");
    let moved = temporary.path().join("moved");
    drop(codex_utils_path::open_private_state_directory(&root).unwrap());
    let parent = OutputParent::open(&root).unwrap();
    assert!(
        std::fs::rename(&root, &moved).is_err(),
        "retained parent denies delete sharing"
    );
    parent.verify(&root).unwrap();
    drop(parent);
    std::fs::rename(&root, &moved).expect("same attack must be possible after guard release");
    drop(codex_utils_path::open_private_state_directory(&root).unwrap());
    let replacement = OutputParent::open(&root).unwrap();
    assert!(
        replacement.verify(&moved).is_err(),
        "different private directory identity rejects"
    );
}

#[test]
fn parent_acl_drift_after_acquisition_fails_revalidation_and_sync() {
    let temporary = private_tempdir("output parent drift");
    let parent = OutputParent::open(temporary.path()).unwrap();
    parent.verify(temporary.path()).unwrap();
    grant(
        temporary.path(),
        world_sid(),
        FILE_GENERIC_READ,
        /*flags*/ 0,
    );
    assert!(parent.verify(temporary.path()).is_err());
    assert!(parent.sync(temporary.path()).is_err());
}

thread_local! {
    static BEFORE_SYNC: std::cell::RefCell<Option<Box<dyn FnOnce(&std::path::Path)>>> =
        const { std::cell::RefCell::new(None) };
}

pub(super) fn before_sync(parent: &std::path::Path) {
    BEFORE_SYNC.with(|hook| {
        let action = hook.borrow_mut().take();
        if let Some(action) = action {
            action(parent);
        }
    });
}

#[test]
fn output_parent_drift_before_flush_rejects_and_cleans_only_the_new_file() {
    let temporary = private_tempdir("late output parent drift");
    let original = temporary.path().join("original");
    write_private_new(&original, b"untouched").unwrap();
    let output = temporary.path().join("assessment");
    BEFORE_SYNC.with(|hook| {
        *hook.borrow_mut() = Some(Box::new(|parent| {
            grant(parent, world_sid(), FILE_GENERIC_READ, /*flags*/ 0);
        }))
    });
    assert!(write_private_new(&output, b"not persisted").is_err());
    assert!(
        BEFORE_SYNC.with(|hook| hook.borrow().is_none()),
        "attack hook must run"
    );
    assert!(
        !output.exists(),
        "cleanup removes its newly owned handle only"
    );
    assert_eq!(std::fs::read(&original).unwrap(), b"untouched");
}

#[cfg(feature = "windows-custody-privileged-tests")]
#[test]
fn redirected_output_parent_rejects_without_creating_in_the_valid_private_target() {
    let temporary = private_tempdir("redirected output parent");
    let target = temporary.path().join("target");
    let link = temporary.path().join("link");
    drop(codex_utils_path::open_private_state_directory(&target).unwrap());
    OutputParent::open(&target).expect("otherwise valid private output target");
    std::os::windows::fs::symlink_dir(&target, &link)
        .expect("authorized native directory-reparse fixture must be created");
    assert!(write_private_new(&link.join("assessment"), b"must not appear").is_err());
    assert!(!target.join("assessment").exists());
}

#[test]
fn retained_parent_create_rejects_rooted_traversal_and_ntfs_stream_names() {
    use std::ffi::OsStr;
    let temporary = private_tempdir("relative create names");
    let parent = OutputParent::open(temporary.path()).unwrap();
    let ordinary =
        codex_utils_path::create_private_recovery_copy(&parent.file, OsStr::new("ordinary"))
            .expect("one ordinary new regular child is a positive control");
    super::FileSnapshot::capture(&ordinary, "ordinary new child").unwrap();
    drop(ordinary);
    for name in [
        "",
        ".",
        "..",
        "../escape",
        "sub/child",
        "sub\\child",
        "child/",
        "\\rooted",
        "C:\\absolute",
        "C:drive-relative",
        "\\\\server\\share\\child",
        "\\\\.\\device",
        "ordinary:stream",
        "ordinary::$DATA",
        "child::$INDEX_ALLOCATION",
        "nul\0tail",
    ] {
        assert!(
            codex_utils_path::create_private_recovery_copy(&parent.file, OsStr::new(name)).is_err(),
            "unsupported child spelling must reject: {name:?}"
        );
    }
    assert_eq!(
        std::fs::read_dir(temporary.path()).unwrap().count(),
        1,
        "rejected child names must not create a different standalone entry"
    );
    assert!(
        secure_read(&temporary.path().join("ordinary"), 64)
            .unwrap()
            .is_empty()
    );
    for name in [
        "ordinary:stream",
        "ordinary::$DATA",
        "child::$INDEX_ALLOCATION",
    ] {
        assert!(
            write_private_new(&temporary.path().join(name), b"must not enter a stream").is_err()
        );
    }
    assert_eq!(std::fs::read_dir(temporary.path()).unwrap().count(), 1);
    assert!(
        secure_read(&temporary.path().join("ordinary"), 64)
            .unwrap()
            .is_empty()
    );
    let stream_error = std::fs::File::open(temporary.path().join("ordinary:stream"))
        .expect_err("a rejected named stream must remain absent, not just absent from read_dir");
    assert_eq!(stream_error.kind(), std::io::ErrorKind::NotFound);
}

#[test]
fn read_only_private_directory_exercises_native_sync_helper_error_propagation() {
    let temporary = private_tempdir("native readonly directory flush control");
    let path = temporary.path();
    OutputParent::open(path)
        .unwrap()
        .sync(path)
        .expect("writable native flush control");
    let file = codex_utils_path::open_existing_private_state_directory(path)
        .expect("valid private read-only directory, not failed setup");
    let identity = super::DirectoryIdentity::capture(&file).unwrap();
    // Deliberately exercise the existing helper boundary, not the public
    // constructor's write-capable acquisition or a G5 post-admission fault.
    let retained = OutputParent { file, identity };
    retained
        .verify(path)
        .expect("same type/owner/DACL/path checks must admit");
    let direct = retained
        .file
        .sync_all()
        .expect_err("read-only native handle must fail flush");
    assert!(
        direct.raw_os_error().is_some(),
        "real OS error, not synthetic errno"
    );
    let propagated = retained
        .sync(path)
        .expect_err("helper must not swallow native flush failure");
    match propagated {
        crate::AcceptanceError::Io(error) => {
            eprintln!("native directory sync error: direct={direct:?} propagated={error:?}");
            assert_eq!(error.raw_os_error(), direct.raw_os_error());
        }
        other => panic!("must propagate the actual IO error, not admission rejection: {other:?}"),
    }
    retained
        .verify(path)
        .expect("private object and identity remain valid after failure");
    OutputParent::open(path)
        .unwrap()
        .sync(path)
        .expect("writable flush still succeeds");
}
