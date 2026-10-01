//! Opened artifact handles and private service snapshots. Byte limits remain
//! enforced if a selected file grows before or during the read.

#[cfg(target_os = "linux")]
use std::fs;
use std::fs::File;
#[cfg(target_os = "linux")]
use std::fs::OpenOptions;
use std::io::Read;
#[cfg(target_os = "linux")]
use std::io::Write;
#[cfg(target_os = "linux")]
use std::os::unix::fs::OpenOptionsExt;
#[cfg(target_os = "linux")]
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use sha2::Digest;
use sha2::Sha256;

use super::BrowserServoError;

#[path = "browser_servo_artifact_stream.rs"]
mod stream;
use stream::stream_bounded;

pub(super) struct ServiceSnapshot {
    _directory: tempfile::TempDir,
    path: PathBuf,
}

impl ServiceSnapshot {
    pub(super) fn path(&self) -> &Path {
        &self.path
    }
}

pub(super) fn open_bounded(path: &Path, maximum: usize) -> Result<File, BrowserServoError> {
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (path, maximum);
        Err(BrowserServoError::Unavailable(
            "private Browser artifact opening requires Linux".into(),
        ))
    }
    #[cfg(target_os = "linux")]
    {
        let input = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
            .map_err(|error| {
                BrowserServoError::Invalid(format!("cannot open {}: {error}", path.display()))
            })?;
        let metadata = input.metadata().map_err(|error| {
            BrowserServoError::Invalid(format!("cannot inspect opened {}: {error}", path.display()))
        })?;
        if !metadata.is_file() || metadata.len() == 0 || metadata.len() > maximum as u64 {
            return Err(BrowserServoError::Invalid(format!(
                "{} must open as a nonempty regular file within its byte limit",
                path.display()
            )));
        }
        Ok(input)
    }
}

pub(super) fn verify_file_digest(
    path: &Path,
    expected: [u8; 32],
    maximum: usize,
) -> Result<(), BrowserServoError> {
    let mut input = open_bounded(path, maximum)?;
    let mut digest = Sha256::new();
    stream_bounded(&mut input, maximum, |bytes| {
        digest.update(bytes);
        Ok(())
    })
    .map_err(|error| {
        BrowserServoError::Invalid(format!("cannot read bounded {}: {error}", path.display()))
    })?;
    let actual: [u8; 32] = digest.finalize().into();
    if actual != expected {
        return Err(BrowserServoError::BindingMismatch(format!(
            "{} digest does not match selected Browser artifact",
            path.display()
        )));
    }
    Ok(())
}

pub(super) fn snapshot_service(
    input: &mut impl Read,
    expected: [u8; 32],
    maximum: usize,
) -> Result<ServiceSnapshot, BrowserServoError> {
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (input, expected, maximum);
        Err(BrowserServoError::Unavailable(
            "private Browser service snapshots require Linux".into(),
        ))
    }
    #[cfg(target_os = "linux")]
    {
        let directory = tempfile::Builder::new()
            .prefix("hepta-browser-service-")
            .tempdir()
            .map_err(|error| {
                BrowserServoError::Unavailable(format!("cannot stage service: {error}"))
            })?;
        fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).map_err(
            |error| {
                BrowserServoError::Unavailable(format!("cannot protect service directory: {error}"))
            },
        )?;
        let path = directory.path().join("service.mjs");
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .map_err(|error| {
                BrowserServoError::Unavailable(format!("cannot stage service: {error}"))
            })?;
        let mut digest = Sha256::new();
        stream_bounded(input, maximum, |bytes| {
            digest.update(bytes);
            output.write_all(bytes)
        })
        .map_err(|error| {
            BrowserServoError::Invalid(format!("cannot copy bounded service: {error}"))
        })?;
        let actual: [u8; 32] = digest.finalize().into();
        if actual != expected {
            return Err(BrowserServoError::BindingMismatch(
                "service snapshot digest does not match selected Browser artifact".into(),
            ));
        }
        output
            .set_permissions(fs::Permissions::from_mode(0o400))
            .and_then(|()| output.sync_all())
            .map_err(|error| {
                BrowserServoError::Unavailable(format!("cannot seal service snapshot: {error}"))
            })?;
        Ok(ServiceSnapshot {
            _directory: directory,
            path,
        })
    }
}
