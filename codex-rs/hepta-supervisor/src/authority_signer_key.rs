//! Explicit owned-seed import. The caller chooses the algorithm and role;
//! no key bytes are generated, printed, persisted or used for an inferred role.
use super::*;
use std::fs::OpenOptions;
use zeroize::Zeroizing;

fn validate_file(file: &File) -> Result<(), ExternalSignerError> {
    let metadata = file.metadata().map_err(ExternalSignerError::KeyIo)?;
    if !metadata.is_file() || metadata.len() > MAX_SIGNING_KEY_INPUT_BYTES as u64 {
        return Err(ExternalSignerError::KeySource(
            "key input must be a bounded regular file".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let owner = rustix::process::geteuid().as_raw();
        if metadata.mode() & 0o077 != 0 || metadata.uid() != owner {
            return Err(ExternalSignerError::KeySource(
                "key file must be owned by the caller and inaccessible to group/world".to_string(),
            ));
        }
    }
    Ok(())
}

pub(super) fn from_path(path: &Path) -> Result<Zeroizing<[u8; 32]>, ExternalSignerError> {
    if !path.is_absolute() {
        return Err(ExternalSignerError::KeySource(
            "key path must be absolute".to_string(),
        ));
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.custom_flags(0x0020_0000);
    }
    let mut file = options.open(path).map_err(ExternalSignerError::KeyIo)?;
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if file
            .metadata()
            .map_err(ExternalSignerError::KeyIo)?
            .file_attributes()
            & 0x400
            != 0
        {
            return Err(ExternalSignerError::KeySource(
                "key path must not be a reparse point".to_string(),
            ));
        }
    }
    validate_file(&file)?;
    read_seed(&mut file)
}

#[cfg(unix)]
pub(super) fn from_fd(fd: i32) -> Result<Zeroizing<[u8; 32]>, ExternalSignerError> {
    use std::os::fd::FromRawFd;
    if fd < 0 {
        return Err(ExternalSignerError::KeySource(
            "key fd must be non-negative".to_string(),
        ));
    }
    // SAFETY: fcntl creates a new close-on-exec descriptor; the original remains
    // caller-owned. File takes the successful result exactly once.
    let duplicate = unsafe { libc::fcntl(fd, libc::F_DUPFD_CLOEXEC, 0) };
    if duplicate < 0 {
        return Err(ExternalSignerError::KeyIo(std::io::Error::last_os_error()));
    }
    let mut file = unsafe { File::from_raw_fd(duplicate) };
    validate_file(&file)?;
    read_seed(&mut file)
}

#[cfg(not(unix))]
pub(super) fn from_fd(_fd: i32) -> Result<Zeroizing<[u8; 32]>, ExternalSignerError> {
    Err(ExternalSignerError::KeySource(
        "--key-fd requires a Unix owned regular descriptor".to_string(),
    ))
}

fn read_seed(file: &mut File) -> Result<Zeroizing<[u8; 32]>, ExternalSignerError> {
    let mut bytes = Zeroizing::new(Vec::new());
    file.take((MAX_SIGNING_KEY_INPUT_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(ExternalSignerError::KeyIo)?;
    if bytes.len() > MAX_SIGNING_KEY_INPUT_BYTES {
        return Err(ExternalSignerError::KeyEncoding);
    }
    if bytes.len() == 32 {
        let mut seed = Zeroizing::new([0; 32]);
        seed.copy_from_slice(&bytes);
        return Ok(seed);
    }
    let text = std::str::from_utf8(&bytes)
        .map_err(|_| ExternalSignerError::KeyEncoding)?
        .trim();
    if text.len() != 64 {
        return Err(ExternalSignerError::KeyEncoding);
    }
    let mut seed = Zeroizing::new([0; 32]);
    for (index, pair) in text.as_bytes().chunks_exact(2).enumerate() {
        seed[index] = (hex_value(pair[0])? << 4) | hex_value(pair[1])?;
    }
    Ok(seed)
}
