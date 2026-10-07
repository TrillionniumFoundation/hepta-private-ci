//! Immutable executable-byte binding for an existing provider adapter.
//! This object proves a byte identity, not an execution or final-use permission.
//! The host must retain it until the complete child exchange has ended. Dynamic
//! libraries, interpreters, environment and the local kernel remain trusted.
use crate::Sha256Digest;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Debug)]
pub struct VerifiedExecutableImage {
    #[cfg(target_os = "linux")]
    file: std::fs::File,
    original: PathBuf,
}

impl VerifiedExecutableImage {
    /// Copy from one nonblocking, no-follow file descriptor, seal the copy, then
    /// hash the sealed bytes. No later pathname or same-inode mutation can change
    /// the retained executable image. An elapsed deadline grants no image.
    pub fn open(
        path: &Path,
        expected: &Sha256Digest,
        max_bytes: u64,
        deadline: Instant,
    ) -> io::Result<Self> {
        #[cfg(target_os = "linux")]
        {
            use rustix::fs::{MemfdFlags, Mode, OFlags, SealFlags};
            use sha2::{Digest, Sha256};
            use std::fs::File;
            use std::io::{Read, Seek, SeekFrom, Write};
            use std::os::fd::AsRawFd;
            use std::os::unix::fs::PermissionsExt;

            let check_deadline = || {
                if Instant::now() >= deadline {
                    Err(io::Error::new(io::ErrorKind::TimedOut, "executable image deadline"))
                } else {
                    Ok(())
                }
            };
            check_deadline()?;
            if !path.is_absolute() || path.canonicalize()? != path || max_bytes == 0 {
                return Err(io::Error::new(io::ErrorKind::InvalidInput, "executable image path"));
            }
            let source = rustix::fs::open(
                path,
                OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW | OFlags::NONBLOCK,
                Mode::empty(),
            )?;
            let mut source = File::from(source);
            let metadata = source.metadata()?;
            if !metadata.is_file()
                || metadata.len() == 0
                || metadata.len() > max_bytes
                || metadata.permissions().mode() & 0o022 != 0
                || metadata.permissions().mode() & 0o111 == 0
            {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "executable image metadata"));
            }
            let fd = rustix::fs::memfd_create(
                c"hepta-provider-executable",
                MemfdFlags::CLOEXEC | MemfdFlags::ALLOW_SEALING,
            )?;
            let mut image = File::from(fd);
            let mut buffer = [0_u8; 64 * 1024];
            let mut length = 0_u64;
            loop {
                check_deadline()?;
                let n = source.read(&mut buffer)?;
                if n == 0 {
                    break;
                }
                length = length.checked_add(n as u64).ok_or_else(|| {
                    io::Error::new(io::ErrorKind::InvalidData, "executable image length")
                })?;
                if length > max_bytes {
                    return Err(io::Error::new(io::ErrorKind::InvalidData, "executable image limit"));
                }
                image.write_all(&buffer[..n])?;
            }
            if length == 0 || length != metadata.len() {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "executable image changed length"));
            }
            rustix::fs::fchmod(&image, Mode::from_bits_truncate(0o500))?;
            let seals = SealFlags::SEAL | SealFlags::SHRINK | SealFlags::GROW | SealFlags::WRITE;
            rustix::fs::fcntl_add_seals(&image, seals)?;
            if !rustix::fs::fcntl_get_seals(&image)?.contains(seals) {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "executable image seals"));
            }
            image.seek(SeekFrom::Start(0))?;
            let mut hasher = Sha256::new();
            loop {
                check_deadline()?;
                let n = image.read(&mut buffer)?;
                if n == 0 {
                    break;
                }
                hasher.update(&buffer[..n]);
            }
            let observed = Sha256Digest::parse(format!("{:x}", hasher.finalize()))
                .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
            if &observed != expected {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "executable image digest"));
            }
            // Close the writable descriptor before exec (ETXTBSY), retaining one
            // sealed, read-only descriptor. No inherited descriptor is needed:
            // the child opens the live host's proc descriptor path at exec.
            let file = File::open(format!("/proc/self/fd/{}", image.as_raw_fd()))?;
            drop(image);
            check_deadline()?;
            Ok(Self { file, original: path.to_owned() })
        }
        #[cfg(not(target_os = "linux"))]
        {
            let _ = (path, expected, max_bytes, deadline);
            Err(io::Error::new(io::ErrorKind::Unsupported, "sealed executable image requires Linux"))
        }
    }

    /// Create the ordinary command from the held image, not the source pathname.
    /// Keep this object alive through child startup and the complete exchange.
    pub fn command(&self) -> std::process::Command {
        #[cfg(target_os = "linux")]
        {
            use std::os::fd::AsRawFd;
            use std::os::unix::process::CommandExt;
            let mut command = std::process::Command::new(format!(
                "/proc/{}/fd/{}", std::process::id(), self.file.as_raw_fd()
            ));
            command.arg0(&self.original);
            command
        }
        #[cfg(not(target_os = "linux"))]
        {
            // No instance can be constructed on this platform. Never return a
            // mutable-path command as a fallback.
            let _ = &self.original;
            unreachable!("unsupported executable image")
        }
    }
}

#[cfg(test)]
#[path = "verified_executable_tests.rs"]
mod tests;
