//! Actual native operations on exclusively owned temporary objects.

use super::PrivateFile;
use super::RetainedPrivateDirectory;
use pretty_assertions::assert_eq;
use std::ffi::OsStr;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::ptr;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetKernelObjectSecurity;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;

fn root() -> (
    tempfile::TempDir,
    std::path::PathBuf,
    RetainedPrivateDirectory,
) {
    let outer = tempfile::tempdir().expect("owned outer scratch");
    let path = outer.path().join("owner");
    let directory = RetainedPrivateDirectory::create_new(&path).expect("exclusive private root");
    (outer, path, directory)
}

fn descriptor(file: &File) -> Vec<u8> {
    let information = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    let mut length = 0;
    // SAFETY: one held scratch-object handle; first query obtains required size.
    unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as _,
            information,
            ptr::null_mut(),
            0,
            &mut length,
        )
    };
    assert!(length > 0 && length <= 65536);
    let mut bytes = vec![0u8; length as usize];
    // SAFETY: allocation has the returned size and remains live for the call.
    assert_ne!(
        unsafe {
            GetKernelObjectSecurity(
                file.as_raw_handle() as _,
                information,
                bytes.as_mut_ptr().cast(),
                length,
                &mut length,
            )
        },
        0
    );
    bytes.truncate(length as usize);
    bytes
}

fn grant_world_read(path: &Path) {
    // This deliberately unsafe fixture is our new scratch object only. Native
    // icacls supplies an actual foreign read ACE, independent of our predicate.
    let system = std::env::var_os("SystemRoot").expect("Windows system root");
    let output = std::process::Command::new(Path::new(&system).join("System32/icacls.exe"))
        .arg(path)
        .args(["/grant", "*S-1-1-0:(R)"])
        .output()
        .expect("native fixture ACL change");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn native_private_roundtrip_flush_and_read_only_custody() {
    let (_outer, path, directory) = root();
    let written = directory
        .write_new_child(OsStr::new("state"), b"committed")
        .expect("write and both real barriers");
    assert_eq!(
        written.read_bounded(64).expect("writer readback"),
        b"committed"
    );
    drop(written);
    directory
        .sync_verified()
        .expect("real retained directory flush");
    let reader =
        PrivateFile::open_existing(&path.join("state")).expect("read-only private artifact");
    assert_eq!(
        reader.read_bounded(64).expect("reopened bytes"),
        b"committed"
    );
    assert!(reader.read_bounded(3).is_err());
    assert!(
        reader.sync_verified().is_err(),
        "read-only flush cannot manufacture a writable capability"
    );
    assert!(
        std::fs::write(path.join("state"), b"changed").is_err(),
        "reader must exclude concurrent writers"
    );
    assert_eq!(
        reader
            .read_bounded(64)
            .expect("unchanged after refused writer"),
        b"committed"
    );
}

#[test]
fn native_atomic_replace_uses_original_retained_directory() {
    let (_outer, path, directory) = root();
    drop(
        directory
            .write_new_child(OsStr::new("state"), b"first")
            .expect("initial private artifact"),
    );
    let value = directory
        .atomic_replace_child(OsStr::new("state"), OsStr::new("state.next"), b"second")
        .expect("native relative rename and directory barrier");
    assert_eq!(
        value.read_bounded(64).expect("new retained identity"),
        b"second"
    );
    drop(value);
    assert!(!path.join("state.next").exists());
    assert_eq!(
        PrivateFile::open_existing(&path.join("state"))
            .expect("reopen replaced file")
            .read_bounded(64)
            .expect("read replaced bytes"),
        b"second"
    );
}

#[test]
fn native_foreign_read_directory_is_refused_without_acl_repair() {
    let outer = tempfile::tempdir().expect("scratch");
    let path = outer.path().join("public");
    std::fs::create_dir(&path).expect("new fixture directory");
    grant_world_read(&path);
    let held = OpenOptions::new()
        .read(true)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(&path)
        .expect("raw descriptor witness");
    let before = descriptor(&held);
    assert!(RetainedPrivateDirectory::open_existing(&path).is_err());
    assert!(RetainedPrivateDirectory::create_new(&path).is_err());
    assert!(PrivateFile::open_directory(&path).is_err());
    assert_eq!(descriptor(&held), before);
    assert_eq!(
        std::fs::read_dir(&path)
            .expect("unchanged fixture entries")
            .count(),
        0
    );
}

#[test]
fn native_checked_names_and_case_aliases_have_no_effect() {
    let (_outer, path, directory) = root();
    drop(
        directory
            .write_new_child(OsStr::new("Artifact"), b"sealed")
            .expect("ordinary actual file"),
    );
    for name in [
        ".",
        "..",
        "../escape",
        "sub\\escape",
        "file:stream",
        "file.",
        "file ",
        "CON",
        "lpt1.txt",
        "prefix\0suffix",
    ] {
        assert!(
            directory
                .write_new_child(OsStr::new(name), b"rejected")
                .is_err(),
            "name {name:?}"
        );
    }
    assert!(
        directory.open_child(OsStr::new("artifact")).is_err(),
        "replacement case alias"
    );
    assert!(
        directory
            .atomic_replace_child(OsStr::new("Artifact"), OsStr::new("ARTIFACT"), b"rejected")
            .is_err()
    );
    assert_eq!(std::fs::read_dir(&path).expect("entries").count(), 1);
    assert_eq!(
        std::fs::read(path.join("Artifact")).expect("original bytes"),
        b"sealed"
    );
}

#[test]
fn native_hardlink_cannot_be_read_hashed_or_replaced() {
    let (_outer, path, directory) = root();
    drop(
        directory
            .write_new_child(OsStr::new("state"), b"sealed")
            .expect("initial file"),
    );
    std::fs::hard_link(path.join("state"), path.join("alias")).expect("real second link");
    assert!(directory.open_child(OsStr::new("state")).is_err());
    assert!(
        directory
            .atomic_replace_child(OsStr::new("state"), OsStr::new("state.next"), b"rejected")
            .is_err()
    );
    assert!(!path.join("state.next").exists());
    assert_eq!(
        std::fs::read(path.join("alias")).expect("unmodified original linked object"),
        b"sealed"
    );
}

#[test]
fn native_retained_directory_replacement_fails_closed() {
    let (_outer, path, directory) = root();
    let moved = path.with_file_name("moved");
    std::fs::rename(&path, &moved).expect("move original held namespace");
    let replacement =
        RetainedPrivateDirectory::create_new(&path).expect("distinct private replacement");
    assert!(directory.verify().is_err());
    assert!(
        directory
            .write_new_child(OsStr::new("state"), b"rejected")
            .is_err()
    );
    assert!(!path.join("state").exists());
    assert!(!moved.join("state").exists());
    replacement
        .verify()
        .expect("new unrelated directory remains valid");
}

#[test]
fn native_sidecar_lock_excludes_second_writer_until_drop() {
    let (_outer, path, directory) = root();
    let held = directory
        .create_or_lock_child(OsStr::new("lock"))
        .expect("exclusive new native lock");
    assert!(directory.create_or_lock_child(OsStr::new("lock")).is_err());
    assert!(std::fs::write(path.join("lock"), b"rejected").is_err());
    held.verify().expect("unchanged retained lock");
    drop(held);
    let reacquired = directory
        .lock_existing_child(OsStr::new("lock"))
        .expect("real release on drop");
    reacquired
        .verify()
        .expect("existing lock qualified without repair");
    drop(reacquired);
    let missing = directory.lock_existing_child(OsStr::new("missing"));
    assert!(matches!(missing, Err(error) if error.kind() == io::ErrorKind::NotFound));
    assert!(!path.join("missing").exists());
}

#[test]
fn native_directory_acl_change_invalidates_original_custody() {
    let (_outer, path, directory) = root();
    grant_world_read(&path);
    assert!(directory.verify().is_err());
    assert!(
        directory
            .write_new_child(OsStr::new("state"), b"rejected")
            .is_err()
    );
    assert!(!path.join("state").exists());
}

#[test]
fn native_reparse_directory_is_refused_before_child_effect() {
    let (outer, path, directory) = root();
    let junction = outer.path().join("junction");
    let system = std::env::var_os("SystemRoot").expect("Windows system root");
    let output = std::process::Command::new(Path::new(&system).join("System32/cmd.exe"))
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&junction)
        .arg(&path)
        .output()
        .expect("create own fixture junction");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let admitted = RetainedPrivateDirectory::open_existing(&junction);
    let inspection = PrivateFile::open_directory(&junction);
    std::fs::remove_dir(&junction).expect("remove own junction before scratch cleanup");
    assert!(admitted.is_err());
    assert!(inspection.is_err());
    assert!(!path.join("state").exists());
    directory
        .verify()
        .expect("original target remains qualified");
}
