use super::*;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::os::windows::fs::OpenOptionsExt;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::*;

#[path = "sqlite_recovery_windows_namespace_tests.rs"]
mod namespace;

struct Fixture {
    root: std::path::PathBuf,
    home: std::path::PathBuf,
    path: std::path::PathBuf,
    sqlite: super::super::SqliteConfig,
}

impl Fixture {
    fn new() -> anyhow::Result<Self> {
        let root = unique_temp_dir();
        let home = root.join("private-home");
        std::fs::create_dir_all(&root)?;
        // Match the product's atomic private-leaf creation, not a public
        // inherited DACL which the original guard must continue to reject.
        drop(codex_utils_path::open_private_state_directory(&home)?);
        let path = home.join("original.sqlite3");
        std::fs::write(&path, b"original database bytes")?;
        let sqlite = super::super::SqliteConfig::new_for_testing(home.as_path().abs());
        Ok(Self {
            root,
            home,
            path,
            sqlite,
        })
    }
    fn bundle() -> anyhow::Result<Self> {
        let fixture = Self::new()?;
        for suffix in ["-wal", "-shm", "-journal"] {
            std::fs::write(
                super::super::sqlite_sidecar_path(&fixture.path, suffix),
                suffix,
            )?;
        }
        Ok(fixture)
    }
    fn paths(&self) -> Vec<std::path::PathBuf> {
        ["", "-wal", "-shm", "-journal"]
            .map(|suffix| super::super::sqlite_sidecar_path(&self.path, suffix))
            .into()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

#[tokio::test]
async fn retained_windows_bundle_is_read_only_and_same_handles() -> anyhow::Result<()> {
    let fixture = Fixture::bundle()?;
    let before: Vec<_> = fixture
        .paths()
        .iter()
        .map(std::fs::read)
        .collect::<std::io::Result<_>>()?;
    let guard = fixture
        .sqlite
        .bind_existing_recovery_database(&fixture.path)?;
    let clone = guard.clone();
    assert!(Arc::ptr_eq(&guard.inner, &clone.inner));
    guard.verify_inspection_unchanged()?;
    assert!(matches!(
        fixture.sqlite.open_immutable_recovery_pool(&guard).await,
        Err(SqliteRecoveryError::Unavailable)
    ));
    assert!(matches!(
        fixture
            .sqlite
            .open_identity_bound_durable_evidence_pool(clone)
            .await,
        Err(SqliteRecoveryError::Unavailable)
    ));
    let after: Vec<_> = fixture
        .paths()
        .iter()
        .map(std::fs::read)
        .collect::<std::io::Result<_>>()?;
    assert_eq!(before, after);
    Ok(())
}

#[test]
fn retained_windows_replacement_uses_file_id_even_with_same_metadata() -> anyhow::Result<()> {
    for role in 0..4 {
        let fixture = Fixture::bundle()?;
        let guard = fixture
            .sqlite
            .bind_existing_recovery_database(&fixture.path)?;
        let path = &fixture.paths()[role];
        let original = File::open(path)?;
        let before = identity::file_id(&original)?;
        let metadata = basic(&original)?;
        let directory_metadata = basic(&guard.inner.parent.descriptor)?;
        let bytes = std::fs::read(path)?;
        std::fs::rename(path, fixture.home.join("retained-original"))?;
        std::fs::write(path, &bytes)?;
        let replacement = std::fs::OpenOptions::new()
            .access_mode(FILE_WRITE_ATTRIBUTES | FILE_READ_ATTRIBUTES | READ_CONTROL)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
            .open(path)?;
        // Restore all mutable metadata, including the parent directory, so
        // replacement must still fail through the immutable file ID.
        set_basic(&replacement, &metadata)?;
        let directory = std::fs::OpenOptions::new()
            .access_mode(FILE_WRITE_ATTRIBUTES | FILE_READ_ATTRIBUTES | READ_CONTROL)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
            .open(&fixture.home)?;
        set_basic(&directory, &directory_metadata)?;
        assert_eq!(basic_tuple(&basic(&replacement)?), basic_tuple(&metadata));
        assert_eq!(
            identity::snapshot(&directory, Kind::Directory)?,
            guard.inner.parent.snapshot
        );
        assert_eq!(
            security::private_security(&replacement)?,
            security::private_security(&original)?
        );
        assert_ne!(identity::file_id(&replacement)?, before);
        assert_eq!(std::fs::read(path)?, bytes);
        assert!(
            matches!(
                guard.verify_inspection_unchanged(),
                Err(SqliteRecoveryError::Indeterminate)
            ),
            "role {role}"
        );
    }
    Ok(())
}

#[test]
fn retained_windows_rejects_extra_links_for_each_component() -> anyhow::Result<()> {
    for role in 0..4 {
        let fixture = Fixture::bundle()?;
        let baseline = fixture
            .sqlite
            .bind_existing_recovery_database(&fixture.path)?;
        baseline.verify_inspection_unchanged()?;
        drop(baseline);
        std::fs::hard_link(&fixture.paths()[role], fixture.home.join("second-link"))?;
        assert!(
            matches!(
                fixture
                    .sqlite
                    .bind_existing_recovery_database(&fixture.path),
                Err(SqliteRecoveryError::Indeterminate)
            ),
            "role {role}"
        );
    }
    Ok(())
}

#[test]
fn retained_windows_rejects_new_sidecar_and_mutated_bytes() -> anyhow::Result<()> {
    for suffix in ["-wal", "-shm", "-journal"] {
        let fixture = Fixture::new()?;
        let guard = fixture
            .sqlite
            .bind_existing_recovery_database(&fixture.path)?;
        std::fs::write(
            super::super::sqlite_sidecar_path(&fixture.path, suffix),
            b"appeared",
        )?;
        assert!(matches!(
            guard.verify_inspection_unchanged(),
            Err(SqliteRecoveryError::Indeterminate)
        ));
    }
    for role in 0..4 {
        let fixture = Fixture::bundle()?;
        let guard = fixture
            .sqlite
            .bind_existing_recovery_database(&fixture.path)?;
        std::fs::write(&fixture.paths()[role], b"changed bytes and length")?;
        assert!(matches!(
            guard.verify_inspection_unchanged(),
            Err(SqliteRecoveryError::Indeterminate)
        ));
    }
    Ok(())
}

#[test]
fn retained_windows_rejects_parent_junction_and_replacement() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let alias = fixture.root.join("redirected-home");
    let junction = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/j"])
        .arg(&alias)
        .arg(&fixture.home)
        .output()?;
    assert!(
        junction.status.success(),
        "junction fixture: {}",
        String::from_utf8_lossy(&junction.stderr)
    );
    let redirected = super::super::SqliteConfig::new_for_testing(alias.as_path().abs());
    assert!(matches!(
        redirected.bind_existing_recovery_database(&alias.join("original.sqlite3")),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    // NTFS refuses MoveFileExW on a directory with an open child even when
    // every handle shares DELETE. Replace the real local namespace instead;
    // the original database and parent handles remain retained throughout.
    let replacement = Fixture::new()?;
    let mut namespace = namespace::DriveNamespace::create(&fixture.root)?;
    let home = namespace.home();
    let path = home.join("original.sqlite3");
    let sqlite = super::super::SqliteConfig::new_for_testing(home.as_path().abs());
    let guard = sqlite.bind_existing_recovery_database(&path)?;
    guard.verify_inspection_unchanged()?;
    let retained_id = identity::file_id(&guard.inner.database.descriptor)?;
    let original_basic = basic(&guard.inner.database.descriptor)?;
    let original_parent = basic(&guard.inner.parent.descriptor)?;
    let destination = std::fs::OpenOptions::new()
        .access_mode(FILE_WRITE_ATTRIBUTES | FILE_READ_ATTRIBUTES | READ_CONTROL)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .open(&replacement.path)?;
    set_basic(&destination, &original_basic)?;
    let directory = std::fs::OpenOptions::new()
        .access_mode(FILE_WRITE_ATTRIBUTES | FILE_READ_ATTRIBUTES | READ_CONTROL)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(&replacement.home)?;
    set_basic(&directory, &original_parent)?;
    assert_eq!(
        basic_tuple(&basic(&destination)?),
        basic_tuple(&original_basic)
    );
    assert_eq!(
        basic_tuple(&basic(&directory)?),
        basic_tuple(&original_parent)
    );
    assert_eq!(
        security::private_security(&directory)?,
        security::private_security(&guard.inner.parent.descriptor)?
    );
    assert_eq!(
        security::private_security(&destination)?,
        security::private_security(&guard.inner.database.descriptor)?
    );
    assert_ne!(
        identity::file_id(&directory)?,
        identity::file_id(&guard.inner.parent.descriptor)?
    );
    namespace.replace(&replacement.root)?;
    let actual = File::open(&path)?;
    assert_eq!(std::fs::read(&path)?, b"original database bytes");
    assert_ne!(identity::file_id(&actual)?, retained_id);
    assert_eq!(
        identity::file_id(&guard.inner.database.descriptor)?,
        retained_id
    );
    assert!(matches!(
        guard.verify_inspection_unchanged(),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    namespace.close()?;
    Ok(())
}

#[test]
fn retained_windows_rejects_foreign_read_grants() -> anyhow::Result<()> {
    for role in 0..4 {
        let fixture = Fixture::bundle()?;
        let guard = fixture
            .sqlite
            .bind_existing_recovery_database(&fixture.path)?;
        let file = std::fs::OpenOptions::new()
            .access_mode(READ_CONTROL | WRITE_DAC)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
            .open(&fixture.paths()[role])?;
        grant_world_read(&file)?;
        assert!(matches!(
            guard.verify_inspection_unchanged(),
            Err(SqliteRecoveryError::Indeterminate)
        ));
        assert!(matches!(
            fixture
                .sqlite
                .bind_existing_recovery_database(&fixture.path),
            Err(SqliteRecoveryError::Indeterminate)
        ));
    }
    Ok(())
}

#[tokio::test]
async fn cold_image_windows_reconnects_to_original_immutable_copy() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    std::fs::remove_file(&fixture.path)?;
    let source = fixture
        .sqlite
        .open_durable_evidence_pool(&fixture.path)
        .await?;
    sqlx::query("CREATE TABLE fact(value TEXT); INSERT INTO fact VALUES ('original')")
        .execute(&source)
        .await?;
    source.close().await;
    let original = std::fs::read(&fixture.path)?;
    let guard = fixture
        .sqlite
        .bind_existing_recovery_database(&fixture.path)?;
    let pool = fixture
        .sqlite
        .open_cold_image_read_only_pool(&guard)
        .await?;
    assert_eq!(std::fs::read(&fixture.path)?, original);
    sqlx::query("PRAGMA query_only = OFF")
        .execute(&pool)
        .await?;
    assert!(
        sqlx::query("UPDATE fact SET value = 'changed'")
            .execute(&pool)
            .await
            .is_err()
    );
    std::fs::write(&fixture.path, b"replaced source bytes")?;
    pool.acquire().await?.close().await?;
    let fact: String = sqlx::query_scalar("SELECT value FROM fact")
        .fetch_one(&pool)
        .await?;
    assert_eq!(fact, "original");
    pool.close().await;
    Ok(())
}

#[test]
fn retained_windows_does_not_repair_existing_shared_home() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let directory = std::fs::OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC | FILE_READ_ATTRIBUTES)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(&fixture.home)?;
    grant_world_read(&directory)?;
    let before = raw_security(&directory)?;
    let bytes = std::fs::read(&fixture.path)?;
    assert!(codex_utils_path::open_private_state_directory(&fixture.home).is_err());
    assert!(matches!(
        fixture
            .sqlite
            .bind_existing_recovery_database(&fixture.path),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    assert_eq!(raw_security(&directory)?, before);
    assert_eq!(std::fs::read(&fixture.path)?, bytes);
    Ok(())
}

fn raw_security(file: &File) -> anyhow::Result<Vec<u8>> {
    let information = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    let mut length = 0;
    // SAFETY: first call requests only the required size from the live handle.
    unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as _,
            information,
            std::ptr::null_mut(),
            0,
            &mut length,
        )
    };
    anyhow::ensure!(length > 0 && length <= 128 * 1024, "native security size");
    let mut words = vec![0usize; (length as usize).div_ceil(std::mem::size_of::<usize>())];
    // SAFETY: the aligned allocation holds the full declared buffer length.
    anyhow::ensure!(
        unsafe {
            GetKernelObjectSecurity(
                file.as_raw_handle() as _,
                information,
                words.as_mut_ptr().cast(),
                length,
                &mut length,
            )
        } != 0,
        "read original security descriptor"
    );
    Ok(
        unsafe { std::slice::from_raw_parts(words.as_ptr().cast::<u8>(), length as usize) }
            .to_vec(),
    )
}

fn grant_world_read(file: &File) -> anyhow::Result<()> {
    let descriptor = security::private_security(file)?;
    let mut original = vec![0usize; descriptor.len().div_ceil(std::mem::size_of::<usize>())];
    // SAFETY: both allocations hold descriptor.len bytes; alignment is retained.
    unsafe {
        std::ptr::copy_nonoverlapping(
            descriptor.as_ptr(),
            original.as_mut_ptr().cast(),
            descriptor.len(),
        )
    };
    let mut dacl = std::ptr::null_mut();
    let mut present = 0;
    let mut defaulted = 0;
    assert_ne!(
        unsafe {
            GetSecurityDescriptorDacl(
                original.as_mut_ptr().cast(),
                &mut present,
                &mut dacl,
                &mut defaulted,
            )
        },
        0
    );
    let mut world = [0usize; 9];
    let mut world_size = std::mem::size_of_val(&world) as u32;
    assert_ne!(
        unsafe {
            CreateWellKnownSid(
                WinWorldSid,
                std::ptr::null_mut(),
                world.as_mut_ptr().cast(),
                &mut world_size,
            )
        },
        0
    );
    let acl_size = u32::from(unsafe { (*dacl).AclSize }) + world_size + 32;
    let mut storage = vec![0usize; (acl_size as usize).div_ceil(std::mem::size_of::<usize>())];
    let acl: *mut ACL = storage.as_mut_ptr().cast();
    assert_ne!(unsafe { InitializeAcl(acl, acl_size, ACL_REVISION) }, 0);
    for index in 0..unsafe { (*dacl).AceCount } {
        let mut ace = std::ptr::null_mut();
        assert_ne!(unsafe { GetAce(dacl, u32::from(index), &mut ace) }, 0);
        let size = u32::from(unsafe { (*ace.cast::<ACE_HEADER>()).AceSize });
        assert_ne!(unsafe { AddAce(acl, ACL_REVISION, u32::MAX, ace, size) }, 0);
    }
    assert_ne!(
        unsafe {
            AddAccessAllowedAce(
                acl,
                ACL_REVISION,
                FILE_GENERIC_READ,
                world.as_mut_ptr().cast(),
            )
        },
        0
    );
    const SECURITY_DESCRIPTOR_REVISION: u32 = 1;
    let mut changed: SECURITY_DESCRIPTOR = unsafe { std::mem::zeroed() };
    assert_ne!(
        unsafe {
            InitializeSecurityDescriptor(
                std::ptr::from_mut(&mut changed).cast(),
                SECURITY_DESCRIPTOR_REVISION,
            )
        },
        0
    );
    assert_ne!(
        unsafe { SetSecurityDescriptorDacl(std::ptr::from_mut(&mut changed).cast(), 1, acl, 0) },
        0
    );
    assert_ne!(
        unsafe {
            SetKernelObjectSecurity(
                file.as_raw_handle() as _,
                DACL_SECURITY_INFORMATION,
                std::ptr::from_mut(&mut changed).cast(),
            )
        },
        0
    );
    Ok(())
}

fn basic(file: &File) -> anyhow::Result<FILE_BASIC_INFO> {
    let mut information: FILE_BASIC_INFO = unsafe { std::mem::zeroed() };
    // SAFETY: the live buffer exactly matches FileBasicInfo and its stated size.
    anyhow::ensure!(
        unsafe {
            GetFileInformationByHandleEx(
                file.as_raw_handle() as _,
                FileBasicInfo,
                std::ptr::from_mut(&mut information).cast(),
                std::mem::size_of::<FILE_BASIC_INFO>() as u32,
            )
        } != 0,
        "read basic identity: {}",
        std::io::Error::last_os_error()
    );
    Ok(information)
}

fn set_basic(file: &File, information: &FILE_BASIC_INFO) -> anyhow::Result<()> {
    // SAFETY: information has the exact layout/length required by FileBasicInfo.
    anyhow::ensure!(
        unsafe {
            SetFileInformationByHandle(
                file.as_raw_handle() as _,
                FileBasicInfo,
                std::ptr::from_ref(information).cast(),
                std::mem::size_of::<FILE_BASIC_INFO>() as u32,
            )
        } != 0,
        "restore mutable metadata: {}",
        std::io::Error::last_os_error()
    );
    Ok(())
}

fn basic_tuple(value: &FILE_BASIC_INFO) -> (i64, i64, i64, i64, u32) {
    (
        value.CreationTime,
        value.LastAccessTime,
        value.LastWriteTime,
        value.ChangeTime,
        value.FileAttributes,
    )
}
