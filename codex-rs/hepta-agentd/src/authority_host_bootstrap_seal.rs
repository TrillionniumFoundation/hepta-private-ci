//! Root-only producer for the single sealed bootstrap descriptor. The original
//! issuer, lease, peer and checkpoint validation remain the launcher's job.

use crate::HOST_AUTHORITY_BOOTSTRAP_BOUND;
use crate::HOST_AUTHORITY_BOOTSTRAP_V1;
use crate::HostAuthorityPublicBootstrapV1;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::fs::MetadataExt;

const REQUIRED_SEALS: i32 =
    libc::F_SEAL_WRITE | libc::F_SEAL_GROW | libc::F_SEAL_SHRINK | libc::F_SEAL_SEAL;

/// Encode the trusted launcher's original public values into one root-owned,
/// unlinked, mode-0400 memfd. The descriptor is never exposed before all four
/// seals and the complete byte-for-byte readback succeed. There is no ordinary
/// file fallback. This function supplies custody, not authority validation or
/// a new bootstrap source; the same root PID must retain its pidfd and serve.
pub fn seal_host_authority_bootstrap(bundle: &HostAuthorityPublicBootstrapV1) -> io::Result<File> {
    require_root()?;
    if bundle.schema_version != 1
        || bundle.operation != HOST_AUTHORITY_BOOTSTRAP_V1
        || bundle.root.uid != 0
        || bundle.root.pid != std::process::id()
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "bootstrap must name its actual root producer",
        ));
    }
    seal_bytes(&encode_public_bootstrap(bundle)?)
}

pub(crate) fn encode_public_bootstrap(
    bundle: &HostAuthorityPublicBootstrapV1,
) -> io::Result<Vec<u8>> {
    let mut bytes = BoundedBytes(Vec::new());
    serde_json::to_writer(&mut bytes, bundle).map_err(io::Error::other)?;
    Ok(bytes.0)
}

fn require_root() -> io::Result<()> {
    // SAFETY: geteuid takes no arguments and returns the kernel's current UID.
    if unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "bootstrap producer requires actual root",
        ));
    }
    Ok(())
}

pub(crate) fn seal_bytes(bytes: &[u8]) -> io::Result<File> {
    require_root()?;
    if bytes.is_empty() || bytes.len() > HOST_AUTHORITY_BOOTSTRAP_BOUND {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "bootstrap exceeds the fixed descriptor bound",
        ));
    }
    // SAFETY: the static name is NUL-terminated; successful memfd_create returns
    // a new owned descriptor, never inherited or visible to the consumer yet.
    let raw = unsafe {
        libc::memfd_create(
            c"hepta-authority-bootstrap".as_ptr(),
            libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING,
        )
    };
    if raw < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: the successful call above transfers exactly this fresh descriptor.
    let mut file = unsafe { File::from_raw_fd(raw) };
    file.write_all(bytes)?;
    // SAFETY: both calls operate only on our live owned file descriptor.
    if unsafe { libc::fchmod(raw, 0o400) } != 0
        || unsafe { libc::fcntl(raw, libc::F_ADD_SEALS, REQUIRED_SEALS) } != 0
    {
        return Err(io::Error::last_os_error());
    }
    validate_sealed(&file, bytes.len() as u64)?;
    file.rewind()?;
    let mut retained = Vec::with_capacity(bytes.len());
    Read::by_ref(&mut file)
        .take(HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 + 1)
        .read_to_end(&mut retained)?;
    if retained != bytes {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "sealed bootstrap readback differs",
        ));
    }
    file.rewind()?;
    Ok(file)
}

pub(crate) fn validate_sealed(file: &File, expected_len: u64) -> io::Result<()> {
    let metadata = file.metadata()?;
    // SAFETY: F_GET_SEALS reads the seals of our retained live descriptor.
    let seals = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GET_SEALS) };
    if seals < 0 {
        return Err(io::Error::last_os_error());
    }
    if !metadata.is_file()
        || metadata.uid() != 0
        || metadata.nlink() != 0
        || metadata.mode() & 0o7777 != 0o400
        || metadata.len() != expected_len
        || seals & REQUIRED_SEALS != REQUIRED_SEALS
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "bootstrap descriptor custody or seals differ",
        ));
    }
    Ok(())
}

struct BoundedBytes(Vec<u8>);

impl Write for BoundedBytes {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > HOST_AUTHORITY_BOOTSTRAP_BOUND.saturating_sub(self.0.len()) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "bootstrap exceeds the fixed descriptor bound",
            ));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
#[path = "authority_host_bootstrap_seal_tests.rs"]
mod tests;
