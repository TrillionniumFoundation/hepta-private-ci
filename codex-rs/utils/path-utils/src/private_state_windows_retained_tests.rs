use super::*;
use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use windows_sys::Win32::Foundation::ERROR_SHARING_VIOLATION;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_REVISION;
use windows_sys::Win32::Security::AddAccessAllowedAceEx;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::CreateWellKnownSid;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::ImpersonateSelf;
use windows_sys::Win32::Security::InitializeAcl;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Security::WinBuiltinAdministratorsSid;
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

enum ExtraGrant {
    Effective(i32),
    InheritOnly(i32),
}

fn replace_acl(file: &File, grant: ExtraGrant) {
    let (sid_kind, flags) = match grant {
        ExtraGrant::Effective(sid) => (sid, 0),
        ExtraGrant::InheritOnly(sid) => (sid, OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE | 0x08),
    };
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
                OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
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
                flags,
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
    replace_acl(&security, ExtraGrant::Effective(WinLocalSystemSid));
    assert_ne!(before, source.snapshot().unwrap());
    replace_acl(&security, ExtraGrant::Effective(WinWorldSid));
    assert!(source.snapshot().is_err());
    drop(source);
    assert!(root.open_file("db", PrivateFileMode::ReadSource).is_err());
    assert!(
        capture_private_security(&security, HandleKind::File).is_err(),
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
    let (temp, root) = fixture();
    let legacy_source = temp.path().join("private/source");
    let legacy_destination = temp.path().join("private/destination");
    std::fs::write(&legacy_source, b"source").unwrap();
    std::fs::write(&legacy_destination, b"destination").unwrap();
    assert_ne!(unsafe { ImpersonateSelf(SecurityImpersonation) }, 0);
    let _revert = Revert;
    let path = temp.path().join("must-not-exist");
    assert!(RetainedPrivateDirectory::open(&path, PrivateDirectoryMode::CreateNew).is_err());
    assert!(!path.exists());
    let legacy_root = temp.path().join("legacy-must-not-exist");
    assert!(super::super::open_private_state_directory(&legacy_root).is_err());
    assert!(!legacy_root.exists());
    assert!(
        super::super::open_private_state_child(
            root.as_file(),
            "legacy-child",
            super::super::PrivateFileAccess::Create
        )
        .is_err()
    );
    assert!(!temp.path().join("private/legacy-child").exists());
    assert!(
        super::super::replace_private_state_child(root.as_file(), "source", "destination").is_err()
    );
    drop(_revert);
    assert_eq!(std::fs::read(legacy_source).unwrap(), b"source");
    assert_eq!(std::fs::read(legacy_destination).unwrap(), b"destination");
}

fn dacl_bytes(file: &File) -> Vec<u8> {
    let mut dacl = ptr::null_mut();
    let mut descriptor = ptr::null_mut();
    assert_eq!(
        unsafe {
            GetSecurityInfo(
                file.as_raw_handle() as HANDLE,
                1,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                &mut dacl,
                ptr::null_mut(),
                &mut descriptor,
            )
        },
        0
    );
    assert!(!dacl.is_null() && !descriptor.is_null());
    let bytes =
        unsafe { std::slice::from_raw_parts(dacl.cast::<u8>(), (*dacl).AclSize as usize) }.to_vec();
    unsafe { LocalFree(descriptor as HLOCAL) };
    bytes
}

#[test]
fn public_inherit_only_grants_fail_directory_open_and_revalidation_without_repair() {
    let (temp, root) = fixture();
    let path = temp.path().join("private");
    let security = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .open(&path)
        .unwrap();
    replace_acl(&security, ExtraGrant::InheritOnly(WinWorldSid));
    let before = dacl_bytes(&security);
    assert!(root.snapshot().is_err());
    assert!(RetainedPrivateDirectory::open(&path, PrivateDirectoryMode::OpenExisting).is_err());
    // Demonstrate the actual exposure the directory check prevents, rather
    // than only testing the ACE scanner against synthetic bytes.
    let child_path = path.join("ordinary-sidecar");
    std::fs::write(&child_path, b"sidecar").unwrap();
    let child = File::open(child_path).unwrap();
    assert!(capture_private_security(&child, HandleKind::File).is_err());
    assert_eq!(
        before,
        dacl_bytes(&security),
        "validation must not repair the ACL"
    );
}

#[test]
fn trusted_inherit_only_grants_preserve_private_ordinary_children() {
    for sid in [WinLocalSystemSid, WinBuiltinAdministratorsSid] {
        let (temp, root) = fixture();
        let path = temp.path().join("private");
        let security = OpenOptions::new()
            .access_mode(READ_CONTROL | WRITE_DAC)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
            .open(&path)
            .unwrap();
        // Current user has inheritable full access; the additional trusted
        // principal receives an inherit-only read grant.
        replace_acl(&security, ExtraGrant::InheritOnly(sid));
        root.snapshot().unwrap();
        RetainedPrivateDirectory::open(&path, PrivateDirectoryMode::OpenExisting).unwrap();
        let child_path = path.join("ordinary-sidecar");
        std::fs::write(&child_path, b"sidecar").unwrap();
        let child = File::open(child_path).unwrap();
        capture_private_security(&child, HandleKind::File).expect("private effective child ACL");
    }
}
