//! Immutable executable bytes for the existing PoN effect adapter.
//!
//! This owns one operation-local file, not a process supervisor, durable journal,
//! permission, or model installer. Linux 6.3+ x86_64/aarch64 is explicit; other
//! platforms fail before dispatch rather than falling back to pathname execution.
//! Dynamic loader/libraries and the kernel remain part of the trusted host.
use std::fs::File;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

pub(super) struct PinnedExecutable {
    // Keep the exact sealed object alive through child spawn and exchange.
    _file: File,
    path: PathBuf,
}

impl PinnedExecutable {
    pub(super) fn path(&self) -> &Path {
        &self.path
    }

    #[cfg(not(all(target_os = "linux", any(target_arch = "x86_64", target_arch = "aarch64"))))]
    pub(super) fn prepare(
        _source: &Path,
        _expected_sha256: &str,
        _deadline: Instant,
    ) -> io::Result<Self> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "PoN immutable executable requires Linux sealed executable objects",
        ))
    }

    #[cfg(all(target_os = "linux", any(target_arch = "x86_64", target_arch = "aarch64")))]
    pub(super) fn prepare(
        source: &Path,
        expected_sha256: &str,
        deadline: Instant,
    ) -> io::Result<Self> {
        linux::prepare(source, expected_sha256, deadline)
    }
}

#[cfg(all(target_os = "linux", any(target_arch = "x86_64", target_arch = "aarch64")))]
mod linux {
    use super::*;
    use sha2::Digest;
    use sha2::Sha256;
    use std::fs::OpenOptions;
    use std::io::Read;
    use std::io::Seek;
    use std::io::SeekFrom;
    use std::io::Write;
    use std::os::fd::AsRawFd;
    use std::os::fd::FromRawFd;
    use std::os::fd::OwnedFd;
    use std::os::raw::c_char;
    use std::os::raw::c_int;
    use std::os::raw::c_uint;
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    // Linux UAPI values on the two explicitly supported architectures. No
    // variadic call uses a pointer argument; both sealing commands take ints.
    const MFD_CLOEXEC: c_uint = 1;
    const MFD_ALLOW_SEALING: c_uint = 2;
    const MFD_EXEC: c_uint = 0x10;
    const F_ADD_SEALS: c_int = 1033;
    const F_GET_SEALS: c_int = 1034;
    const REQUIRED_SEALS: c_int = 1 | 2 | 4 | 8 | 0x20;
    const O_NONBLOCK: c_int = 0x800;
    const O_NOFOLLOW: c_int = 0x20000;
    const MAX_BYTES: u64 = 256 * 1024 * 1024;

    unsafe extern "C" {
        fn memfd_create(name: *const c_char, flags: c_uint) -> c_int;
        fn fcntl(fd: c_int, operation: c_int, ...) -> c_int;
    }

    fn check_deadline(deadline: Instant) -> io::Result<()> {
        if Instant::now() >= deadline {
            return Err(io::Error::new(io::ErrorKind::TimedOut, "PoN executable deadline"));
        }
        Ok(())
    }

    pub(super) fn prepare(
        source: &Path,
        expected_sha256: &str,
        deadline: Instant,
    ) -> io::Result<PinnedExecutable> {
        check_deadline(deadline)?;
        if !source.is_absolute() || source.canonicalize()? != source {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "PoN executable path"));
        }
        // NOFOLLOW closes the final-component symlink race. NONBLOCK prevents
        // a replacement FIFO from blocking open before fstat rejects it.
        let mut input = OpenOptions::new()
            .read(true)
            .custom_flags(O_NONBLOCK | O_NOFOLLOW)
            .open(source)?;
        let metadata = input.metadata()?;
        let mode = metadata.permissions().mode();
        if !metadata.is_file() || metadata.len() == 0 || metadata.len() > MAX_BYTES
            || mode & 0o022 != 0 || mode & 0o111 == 0
        {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "PoN executable metadata"));
        }
        // SAFETY: a static NUL-terminated name and Linux-defined flags are
        // passed. Success returns a new descriptor owned only by this call.
        let raw = unsafe { memfd_create(c"hepta-pon-executable".as_ptr(), MFD_CLOEXEC | MFD_ALLOW_SEALING | MFD_EXEC) };
        if raw < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: raw is a newly created valid descriptor, transferred exactly
        // once to OwnedFd. Every subsequent early return closes it via RAII.
        let owned = unsafe { OwnedFd::from_raw_fd(raw) };
        let mut file = File::from(owned);
        let mut buffer = [0_u8; 64 * 1024];
        let mut total = 0_u64;
        loop {
            check_deadline(deadline)?;
            let n = input.read(&mut buffer)?;
            if n == 0 { break; }
            total = total.checked_add(n as u64).ok_or_else(|| io::Error::other("PoN executable length"))?;
            if total > MAX_BYTES {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "PoN executable length"));
            }
            file.write_all(&buffer[..n])?;
        }
        drop(input);
        file.set_permissions(std::fs::Permissions::from_mode(0o500))?;
        // Seal BEFORE hashing: even a concurrent rewrite while copying must
        // result in the exact expected sealed bytes, or this operation refuses.
        // SAFETY: file owns a live descriptor; this command takes an int mask.
        if unsafe { fcntl(file.as_raw_fd(), F_ADD_SEALS, REQUIRED_SEALS) } < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: F_GET_SEALS has no third argument and reads a live descriptor.
        let seals = unsafe { fcntl(file.as_raw_fd(), F_GET_SEALS) };
        if seals < 0 || seals & REQUIRED_SEALS != REQUIRED_SEALS {
            return Err(io::Error::other("PoN executable seal readback"));
        }
        file.seek(SeekFrom::Start(0))?;
        let mut magic = [0_u8; 4];
        file.read_exact(&mut magic)?;
        if magic != *b"\x7fELF" {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "PoN executable must be ELF, not an interpreter script"));
        }
        file.seek(SeekFrom::Start(0))?;
        let mut hash = Sha256::new();
        loop {
            check_deadline(deadline)?;
            let n = file.read(&mut buffer)?;
            if n == 0 { break; }
            hash.update(&buffer[..n]);
        }
        if format!("{:x}", hash.finalize()) != expected_sha256 {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "PoN executable digest mismatch"));
        }
        check_deadline(deadline)?;
        // The child inherits this fd until ELF exec; CLOEXEC then closes it.
        // Keep the owner alive until the exchange ends, never resolve source again.
        let path = PathBuf::from(format!("/proc/self/fd/{}", file.as_raw_fd()));
        Ok(PinnedExecutable { _file: file, path })
    }
}

#[cfg(all(test, target_os = "linux", any(target_arch = "x86_64", target_arch = "aarch64")))]
#[path = "automation_effect_host_pon_executable_tests.rs"]
mod tests;
