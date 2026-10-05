use super::*;
use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use windows_sys::Win32::Foundation::ERROR_SHARING_VIOLATION;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_REVISION;
use windows_sys::Win32::Security::AddAccessAllowedAceEx;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::CreateWellKnownSid;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::ImpersonateSelf;
use windows_sys::Win32::Security::InitializeAcl;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Security::WinLocalSystemSid;
use windows_sys::Win32::Security::WinWorldSid;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

fn fixture() -> (tempfile::TempDir, RetainedPrivateDirectory) {
    let temp = tempfile::tempdir().expect("tempdir on local NTFS");
    let root = RetainedPrivateDirectory::open(
        &temp.path().join("private"),
        PrivateDirectoryMode::CreateNew,
    )
    .expect("private root");
    (temp, root)
}

fn sharing_violation(result: io::Result<impl Sized>) {
    assert_eq!(
        result.err().expect("sharing violation").raw_os_error(),
        Some(ERROR_SHARING_VIOLATION as i32)
    );
}

#[test]
fn creates_private_objects_and_sidecars_without_repairing_existing_objects() {
    let (temp, root) = fixture();
    let generation = root
        .open_directory("generation", PrivateDirectoryMode::CreateNew)
        .unwrap();
    let file = generation
        .open_file("db", PrivateFileMode::CreateNew)
        .unwrap();
    assert!(file.snapshot().unwrap().security.control & SE_DACL_PROTECTED != 0);
    drop(file);
    let first = generation
        .open_file("db", PrivateFileMode::ReadSource)
        .unwrap()
        .snapshot()
        .unwrap();
    std::fs::write(temp.path().join("private/generation/db-wal"), b"sidecar").unwrap();
    generation
        .open_file("db-wal", PrivateFileMode::ReadSource)
        .expect("inherited private sidecar");
    assert!(
        generation
            .open_file("db", PrivateFileMode::CreateNew)
            .is_err()
    );
    let reopened = generation
        .open_file("db", PrivateFileMode::ReadSource)
        .unwrap();
    assert_eq!(first, reopened.snapshot().unwrap());
    assert!(
        generation
            .open_file("missing", PrivateFileMode::ReadSource)
            .is_err()
    );
    assert!(!temp.path().join("private/generation/missing").exists());
}

#[test]
fn source_prevents_writes_rename_delete_and_replacement_but_allows_readers() {
    let (temp, root) = fixture();
    let mut created = root.open_file("db", PrivateFileMode::CreateNew).unwrap();
    created.0.write_all(b"retained source").unwrap();
    drop(created);
    let source = root.open_file("db", PrivateFileMode::ReadSource).unwrap();
    let before = source.snapshot().unwrap();
    let path = temp.path().join("private/db");
    sharing_violation(OpenOptions::new().write(true).open(&path));
    sharing_violation(std::fs::rename(&path, temp.path().join("private/moved")));
    sharing_violation(std::fs::remove_file(&path));
    assert!(root.open_file("db", PrivateFileMode::CreateNew).is_err());
    assert!(source.as_file().write_all(b"forbidden").is_err());
    let mut reader = root.open_file("db", PrivateFileMode::ReadSource).unwrap();
    let mut contents = Vec::new();
    reader.0.read_to_end(&mut contents).unwrap();
    assert_eq!(contents, b"retained source");
    assert_eq!(before, source.snapshot().unwrap());
}

#[test]
fn lock_shares_read_write_handles_but_not_delete_and_root_allows_flush_access() {
    let (temp, root) = fixture();
    let first = root
        .open_file("store.lock", PrivateFileMode::CreateNewLock)
        .unwrap();
    let second = root
        .open_file("store.lock", PrivateFileMode::OpenLock)
        .unwrap();
    assert_eq!(first.snapshot().unwrap(), second.snapshot().unwrap());
    // This tests sharing only; byte-range lock ownership belongs to the caller.
    sharing_violation(
        OpenOptions::new()
            .access_mode(DELETE)
            .open(temp.path().join("private/store.lock")),
    );
    let durability = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .open(temp.path().join("private"))
        .unwrap();
    assert_eq!(
        root.snapshot().unwrap(),
        snapshot(&durability, HandleKind::Directory).unwrap()
    );
    sharing_violation(std::fs::rename(
        temp.path().join("private"),
        temp.path().join("moved"),
    ));
}

#[test]
fn rejects_existing_hardlinks_and_wrong_kinds() {
    let (temp, root) = fixture();
    drop(root.open_file("db", PrivateFileMode::CreateNew).unwrap());
    std::fs::hard_link(temp.path().join("private/db"), temp.path().join("alias")).unwrap();
    assert!(root.open_file("db", PrivateFileMode::ReadSource).is_err());
    drop(
        root.open_directory("directory", PrivateDirectoryMode::CreateNew)
            .unwrap(),
    );
    assert!(
        root.open_file("directory", PrivateFileMode::ReadSource)
            .is_err()
    );
    assert!(
        root.open_directory("db", PrivateDirectoryMode::OpenExisting)
            .is_err()
    );
}

#[test]
fn literal_names_cannot_address_streams_devices_or_other_directories() {
    let (_temp, root) = fixture();
    for name in [
        "",
        ".",
        "..",
        "a/../db",
        "a\\db",
        "db:stream",
        "db\0",
        "db.",
        "db ",
        "NUL",
        "com1.log",
        "LPT¹",
        "a*",
        "a?",
    ] {
        assert!(
            root.open_file(name, PrivateFileMode::CreateNew).is_err(),
            "{name:?}"
        );
    }
}

#[test]
fn rejects_junction_ancestors_and_children() {
    let (temp, root) = fixture();
    let target = temp.path().join("private/target");
    drop(
        root.open_directory("target", PrivateDirectoryMode::CreateNew)
            .unwrap(),
    );
    let alias = temp.path().join("private/alias");
    let output = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&alias)
        .arg(&target)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "junction creation failed: {output:?}"
    );
    assert!(
        root.open_directory("alias", PrivateDirectoryMode::OpenExisting)
            .is_err()
    );
    assert!(
        RetainedPrivateDirectory::open(&alias.join("new"), PrivateDirectoryMode::CreateNew)
            .is_err()
    );
    assert!(!target.join("new").exists());
    std::fs::remove_dir(alias).unwrap();
}

fn replace_acl(file: &File, sid_kind: i32) {
    let user = CurrentUser::read().unwrap();
    let mut sid = [0_u32; 17];
    let mut length = std::mem::size_of_val(&sid) as u32;
    assert_ne!(
        unsafe {
            CreateWellKnownSid(
                sid_kind,
                ptr::null_mut(),
                sid.as_mut_ptr().cast(),
                &mut length,
            )
        },
        0
    );
    let mut storage = [0_u32; 128];
    let dacl = storage.as_mut_ptr().cast::<ACL>();
    assert_ne!(
        unsafe { InitializeAcl(dacl, std::mem::size_of_val(&storage) as u32, ACL_REVISION) },
        0
    );
    assert_ne!(
        unsafe {
            AddAccessAllowedAceEx(
                dacl,
                ACL_REVISION,
                0,
                super::super::FILE_ALL_ACCESS,
                user.sid(),
            )
        },
        0
    );
    assert_ne!(
        unsafe {
            AddAccessAllowedAceEx(
                dacl,
                ACL_REVISION,
                0,
                FILE_GENERIC_READ,
                sid.as_mut_ptr().cast(),
            )
        },
        0
    );
    assert_eq!(
        unsafe {
            SetSecurityInfo(
                file.as_raw_handle() as HANDLE,
                1,
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                dacl,
                ptr::null_mut(),
            )
        },
        0
    );
}

#[test]
fn public_acl_is_rejected_without_permission_repair_and_trusted_acl_drift_is_seen() {
    let (temp, root) = fixture();
    drop(root.open_file("db", PrivateFileMode::CreateNew).unwrap());
    let security = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .open(temp.path().join("private/db"))
        .unwrap();
    let source = root.open_file("db", PrivateFileMode::ReadSource).unwrap();
    let before = source.snapshot().unwrap();
    replace_acl(&security, WinLocalSystemSid);
    assert_ne!(before, source.snapshot().unwrap());
    replace_acl(&security, WinWorldSid);
    assert!(source.snapshot().is_err());
    drop(source);
    assert!(root.open_file("db", PrivateFileMode::ReadSource).is_err());
    assert!(
        capture_private_security(&security).is_err(),
        "open must not repair public ACL"
    );
}

#[test]
fn delete_pending_objects_are_rejected_even_with_a_retained_handle() {
    use windows_sys::Win32::Storage::FileSystem::FILE_DISPOSITION_INFO;
    use windows_sys::Win32::Storage::FileSystem::FileDispositionInfo;
    use windows_sys::Win32::Storage::FileSystem::SetFileInformationByHandle;
    let (temp, root) = fixture();
    drop(root.open_file("db", PrivateFileMode::CreateNew).unwrap());
    let file = OpenOptions::new()
        .read(true)
        .access_mode(FILE_GENERIC_READ | DELETE)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .open(temp.path().join("private/db"))
        .unwrap();
    let info = FILE_DISPOSITION_INFO { DeleteFile: 1 };
    assert_ne!(
        unsafe {
            SetFileInformationByHandle(
                file.as_raw_handle() as HANDLE,
                FileDispositionInfo,
                (&info as *const FILE_DISPOSITION_INFO).cast(),
                size_of::<FILE_DISPOSITION_INFO>() as u32,
            )
        },
        0
    );
    assert!(snapshot(&file, HandleKind::File).is_err());
    assert!(root.open_file("db", PrivateFileMode::ReadSource).is_err());
}

#[test]
fn impersonating_execution_is_rejected_before_creation() {
    struct Revert;
    impl Drop for Revert {
        fn drop(&mut self) {
            assert_ne!(unsafe { RevertToSelf() }, 0);
        }
    }
    let temp = tempfile::tempdir().unwrap();
    assert_ne!(unsafe { ImpersonateSelf(SecurityImpersonation) }, 0);
    let _revert = Revert;
    let path = temp.path().join("must-not-exist");
    assert!(RetainedPrivateDirectory::open(&path, PrivateDirectoryMode::CreateNew).is_err());
    assert!(!path.exists());
}
