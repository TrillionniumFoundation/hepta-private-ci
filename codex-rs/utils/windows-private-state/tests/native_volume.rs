#![cfg(windows)]

use codex_utils_windows_private_state::mechanism::identity;
use codex_utils_windows_private_state::volume::inspect_local_ntfs;
use std::error::Error;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OVERLAPPED;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;

type Result<T = ()> = std::result::Result<T, Box<dyn Error>>;
static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Result<Self> {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let sequence = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-local-volume-{}-{nonce}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&path)?;
        Ok(Self(path))
    }

    fn create_file(&self) -> io::Result<File> {
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
            .open(self.0.join("object"))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        // Only known fresh test leaves; never recurse through a reparse point.
        let _ = fs::remove_file(self.0.join("object"));
        let _ = fs::remove_file(self.0.join("held"));
        let _ = fs::remove_dir(&self.0);
    }
}

fn completed(stage: &str) {
    println!(
        "HEPTA_LOCAL_NTFS_OBSERVATION {{\"stage\":\"{stage}\",\"owner_supported\":false,\"trusted_parent\":false,\"power_loss_qualified\":false}}"
    );
}

#[test]
fn native_local_ntfs_file_and_directory_report_same_volume() -> Result {
    let fixture = Fixture::new()?;
    let file = fixture.create_file()?;
    let directory = OpenOptions::new()
        .read(true)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(&fixture.0)?;
    let file_observed = inspect_local_ntfs(&file)?;
    let directory_observed = inspect_local_ntfs(&directory)?;
    assert_eq!(file_observed.object, identity(&file)?);
    assert_eq!(directory_observed.object, identity(&directory)?);
    assert_eq!(
        file_observed.object.volume,
        directory_observed.object.volume
    );
    assert_ne!(file_observed.filesystem_flags & 0x8, 0);
    assert_ne!(directory_observed.filesystem_flags & 0x8, 0);
    assert_eq!(file_observed.device_characteristics & 0x10, 0);
    assert_eq!(directory_observed.device_characteristics & 0x10, 0);
    completed("local_ntfs_complete");
    Ok(())
}

#[test]
fn native_nondisk_handle_is_rejected() -> Result {
    let device = File::open(r"\\.\NUL")?;
    let error = inspect_local_ntfs(&device)
        .err()
        .ok_or("NUL was admitted as a disk volume")?;
    assert_eq!(error.kind(), io::ErrorKind::InvalidInput);
    completed("nondisk_complete");
    Ok(())
}

#[test]
fn native_volume_observation_stays_bound_to_renamed_held_object() -> Result {
    let fixture = Fixture::new()?;
    let held = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .custom_flags(FILE_FLAG_OVERLAPPED)
        .open(fixture.0.join("object"))?;
    let original = inspect_local_ntfs(&held)?;
    fs::rename(fixture.0.join("object"), fixture.0.join("held"))?;
    let replacement = fixture.create_file()?;
    assert_ne!(identity(&replacement)?, original.object);
    assert_eq!(inspect_local_ntfs(&held)?, original);
    completed("held_binding_complete");
    Ok(())
}
