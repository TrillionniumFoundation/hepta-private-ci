use super::PrivateSqliteDirectory;
use super::RetainedSqliteDirectory;
use super::super::PrivateStateDirectory;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::FileTimes;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::ptr;
use std::time::SystemTime;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_ATTRIBUTES;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;

fn refused<T>(result: io::Result<T>, operation: &str) -> io::Error {
    match result {
        Err(error) => error,
        Ok(_) => panic!("{operation}: unexpectedly succeeded"),
    }
}

#[test]
fn existing_only_opens_never_create_a_missing_directory() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("missing");
    assert_eq!(
        refused(RetainedSqliteDirectory::open_existing(&path), "read-only missing root").kind(),
        io::ErrorKind::NotFound
    );
    assert_eq!(
        refused(PrivateSqliteDirectory::open_existing(&path), "existing-only writer root").kind(),
        io::ErrorKind::NotFound
    );
    assert!(!path.exists());
    Ok(())
}

#[test]
fn create_new_preserves_existing_files_and_directory() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("private");
    let directory = PrivateSqliteDirectory::create_new(&path)?;
    let mut file = directory.create_new_file("database.sqlite")?;
    file.write_all(b"original evidence")?;
    file.sync_all()?;
    drop(file);
    directory.sync_all()?;
    assert_eq!(
        refused(directory.create_new_file("database.sqlite"), "CreateNew must collide").kind(),
        io::ErrorKind::AlreadyExists
    );
    assert_eq!(
        refused(PrivateSqliteDirectory::create_new(&path), "existing directory must collide").kind(),
        io::ErrorKind::AlreadyExists
    );
    assert_eq!(fs::read(path.join("database.sqlite"))?, b"original evidence");
    Ok(())
}

#[test]
fn ordinary_sqlite_filenames_inherit_private_acl_without_repair() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("private");
    let directory = PrivateSqliteDirectory::create_new(&path)?;
    let names = ["database.sqlite", "database.sqlite-wal", "database.sqlite-shm", "database.sqlite-journal"];
    for name in names {
        // Deliberately no explicit security descriptor, as with SQLite's normal
        // CreateFile calls. Real SQLx WAL/replay coverage belongs to the owner.
        fs::write(path.join(name), name.as_bytes())?;
    }
    drop(directory);
    let retained = RetainedSqliteDirectory::open_existing(&path)?;
    for name in names {
        let file = retained.retain_file(name)?;
        assert_eq!(file.read_bounded(/*maximum_bytes*/ 128)?, Some(name.as_bytes().to_vec()));
    }
    // The existing registry policy remains strictly non-inheritable.
    assert_eq!(
        refused(PrivateStateDirectory::open_or_create(&path), "separate registry ACL policy").kind(),
        io::ErrorKind::PermissionDenied
    );
    Ok(())
}

#[test]
fn retention_reads_exact_offsets_and_rejects_overflow_or_metadata_drift() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("private");
    let directory = PrivateSqliteDirectory::create_new(&path)?;
    let bytes: Vec<u8> = (0..131_071).map(|index| (index % 251) as u8).collect();
    directory.create_new_file("database.sqlite")?.write_all(&bytes)?;
    drop(directory);
    let retained = RetainedSqliteDirectory::open_existing(&path)?;
    let file = retained.retain_file("database.sqlite")?;
    for _ in 0..2 {
        assert_eq!(file.read_bounded(bytes.len() as u64)?, Some(bytes.clone()));
    }
    assert_eq!(
        refused(file.read_bounded(bytes.len() as u64 - 1), "bounded source read").kind(),
        io::ErrorKind::InvalidInput
    );
    // Attribute-only handles are not data writers. The identity check must also
    // reject an external metadata change, even while data-write sharing is denied.
    let attributes = OpenOptions::new().access_mode(FILE_WRITE_ATTRIBUTES)
        .open(path.join("database.sqlite"))?;
    attributes.set_times(FileTimes::new().set_modified(SystemTime::UNIX_EPOCH))?;
    assert!(file.verify_unchanged().is_err());
    Ok(())
}

#[test]
fn retained_sources_and_root_remain_pinned_until_last_owner_drops() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("private");
    let directory = PrivateSqliteDirectory::create_new(&path)?;
    directory.create_new_file("database.sqlite")?.write_all(b"retained")?;
    drop(directory);
    let retained = RetainedSqliteDirectory::open_existing(&path)?;
    let file = retained.retain_file("database.sqlite")?;
    drop(retained);
    assert!(OpenOptions::new().write(true).open(path.join("database.sqlite")).is_err());
    assert!(fs::remove_file(path.join("database.sqlite")).is_err());
    assert!(fs::rename(path.join("database.sqlite"), path.join("replacement")).is_err());
    assert!(fs::rename(&path, temporary.path().join("moved")).is_err());
    assert_eq!(file.read_bounded(/*maximum_bytes*/ 64)?, Some(b"retained".to_vec()));
    drop(file);
    fs::rename(&path, temporary.path().join("moved"))?;
    Ok(())
}

#[test]
fn an_existing_writer_prevents_retention_and_absence_is_not_a_missing_observation() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("private");
    let directory = PrivateSqliteDirectory::create_new(&path)?;
    let writer = directory.create_new_file("database.sqlite")?;
    let retained = RetainedSqliteDirectory::open_existing(&path)?;
    assert!(retained.retain_file("database.sqlite").is_err());
    drop(writer);
    let absent = retained.retain_file("database.sqlite-wal")?;
    assert_eq!(absent.read_bounded(/*maximum_bytes*/ 64)?, None);
    fs::write(path.join("database.sqlite-wal"), b"new WAL")?;
    assert!(absent.verify_unchanged().is_err());
    Ok(())
}

#[test]
fn hard_links_wrong_types_and_non_component_names_are_errors() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("private");
    let directory = PrivateSqliteDirectory::create_new(&path)?;
    drop(directory.create_new_file("database.sqlite")?);
    fs::hard_link(path.join("database.sqlite"), path.join("alias"))?;
    fs::create_dir(path.join("directory"))?;
    let retained = RetainedSqliteDirectory::open_existing(&path)?;
    for name in ["database.sqlite", "alias", "directory"] {
        assert!(retained.retain_file(name).is_err(), "unsafe entry: {name}");
    }
    for name in ["", ".", "..", "../outside", "file:stream", "sub\\file"] {
        assert_eq!(refused(retained.retain_file(name), "single component").kind(), io::ErrorKind::InvalidInput);
    }
    Ok(())
}

#[test]
fn junction_roots_are_rejected_without_creating_the_target_child() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("private");
    let directory = PrivateSqliteDirectory::create_new(&path)?;
    let junction = temporary.path().join("junction");
    let output = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"]).arg(&junction).arg(&path).output()?;
    assert!(output.status.success(), "junction creation: {output:?}");
    assert!(RetainedSqliteDirectory::open_existing(&junction).is_err());
    assert!(PrivateSqliteDirectory::create_new(&junction.join("nested")).is_err());
    assert!(!path.join("nested").exists());
    fs::remove_dir(junction)?;
    drop(directory);
    Ok(())
}

#[test]
fn changed_null_and_foreign_dacls_are_rejected_without_repair() -> io::Result<()> {
    for descriptor_text in ["D:NO_ACCESS_CONTROL", "D:P(A;OICI;FA;;;WD)"] {
        let temporary = tempfile::tempdir()?;
        let path = temporary.path().join("private");
        let directory = PrivateSqliteDirectory::create_new(&path)?;
        let retained = RetainedSqliteDirectory::open_existing(&path)?;
        let wide: Vec<u16> = descriptor_text.encode_utf16().chain(std::iter::once(0)).collect();
        let mut descriptor = ptr::null_mut();
        // SAFETY: The input is terminated and the output belongs to LocalFree.
        let converted = unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(wide.as_ptr(), SDDL_REVISION_1, &mut descriptor, ptr::null_mut())
        };
        assert_ne!(converted, 0, "fixture descriptor: {}", io::Error::last_os_error());
        let mut present = 0;
        let mut defaulted = 0;
        let mut acl = ptr::null_mut();
        // SAFETY: Both queries borrow the live fixture descriptor and handle;
        // SetSecurityInfo copies the ACL before LocalFree releases its storage.
        let (queried, status) = unsafe {
            let queried = GetSecurityDescriptorDacl(descriptor, &mut present, &mut acl, &mut defaulted);
            let status = if queried != 0 {
                SetSecurityInfo(directory.file.as_raw_handle() as HANDLE, SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                    ptr::null_mut(), ptr::null_mut(), acl, ptr::null_mut())
            } else { u32::MAX };
            LocalFree(descriptor);
            (queried, status)
        };
        assert_ne!(queried, 0);
        assert_eq!(status, 0);
        assert!(retained.verify_unchanged().is_err());
        assert_eq!(refused(RetainedSqliteDirectory::open_existing(&path), "unsafe ACL").kind(), io::ErrorKind::PermissionDenied);
        assert_eq!(refused(PrivateSqliteDirectory::open_existing(&path), "no ACL repair").kind(), io::ErrorKind::PermissionDenied);
    }
    Ok(())
}
