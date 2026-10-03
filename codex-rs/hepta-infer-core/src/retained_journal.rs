//! Check the live owner's complete retained byte prefix before acknowledging it.
//! This process-local digest is not an independently retained rollback witness.

use std::fs;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use sha2::Digest;
use sha2::Sha256;

use super::Error;
use super::MAX_JOURNAL_BYTES;

#[derive(Clone, Copy)]
pub(super) enum Access {
    OwnerRead,
    OwnerReadWrite,
}

/// The current checkpoint is part of the retained recovery cut, not an archive.
#[derive(Clone, Debug)]
pub(super) struct Checkpoint {
    path: PathBuf,
    file: Arc<File>,
    bytes: u64,
    digest: [u8; 32],
}

impl Checkpoint {
    pub(super) fn new(path: PathBuf, file: File, bytes: &[u8]) -> Result<Self, Error> {
        let retained = Self {
            path,
            file: Arc::new(file),
            bytes: bytes.len() as u64,
            digest: Sha256::digest(bytes).into(),
        };
        retained.verify()?;
        Ok(retained)
    }

    pub(super) fn verify(&self) -> Result<(), Error> {
        verify(
            &self.path,
            &self.file,
            self.bytes,
            self.digest,
            Access::OwnerRead,
        )
    }
}

pub(super) fn verify(
    path: &Path,
    file: &File,
    expected_bytes: u64,
    expected_digest: [u8; 32],
    access: Access,
) -> Result<(), Error> {
    if expected_bytes > MAX_JOURNAL_BYTES {
        return Err(Error::CapacityExceeded);
    }
    verify_identity(path, file, expected_bytes, access)?;
    // A cloned descriptor shares its offset with the append-only writer. Every
    // verification rewinds it; every write uses the original O_APPEND handle.
    let mut reader = file.try_clone()?;
    reader.rewind()?;
    verify_bytes(&mut reader, expected_bytes, expected_digest)?;
    verify_identity(path, file, expected_bytes, access)?;
    Ok(())
}

fn verify_identity(
    path: &Path,
    file: &File,
    expected_bytes: u64,
    access: Access,
) -> Result<(), Error> {
    let named = fs::symlink_metadata(path)?;
    let opened = file.metadata()?;
    if named.len() > MAX_JOURNAL_BYTES || opened.len() > MAX_JOURNAL_BYTES {
        return Err(Error::CapacityExceeded);
    }
    if !named.file_type().is_file()
        || !opened.is_file()
        || named.len() != expected_bytes
        || opened.len() != expected_bytes
    {
        return Err(Error::CorruptJournal("retained journal identity or length"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        if named.dev() != opened.dev() || named.ino() != opened.ino() {
            return Err(Error::CorruptJournal("retained journal path replaced"));
        }
        let required = match access {
            Access::OwnerRead => 0o400,
            Access::OwnerReadWrite => 0o600,
        };
        let permissions = opened.permissions().mode();
        if permissions & required != required || permissions & 0o077 != 0 {
            return Err(Error::CorruptJournal("retained journal permissions"));
        }
    }
    #[cfg(windows)]
    {
        let _ = access;
        // Windows locks deny reads through separately opened handles even in
        // this process. Compare identities with a metadata-only handle; read
        // bytes exclusively through the cloned, already locked owner handle.
        let named_handle = winapi_util::Handle::from_path_any(path)?;
        let named_identity = winapi_util::file::information(&named_handle)?;
        let opened_identity = winapi_util::file::information(file)?;
        if named_identity.volume_serial_number() != opened_identity.volume_serial_number()
            || named_identity.file_index() != opened_identity.file_index()
            || named_identity.file_size() != expected_bytes
        {
            return Err(Error::CorruptJournal("retained journal path replaced"));
        }
    }
    #[cfg(not(any(unix, windows)))]
    return Err(Error::CorruptJournal(
        "unsupported retained file identity platform",
    ));
    Ok(())
}

fn verify_bytes(
    reader: &mut File,
    expected_bytes: u64,
    expected_digest: [u8; 32],
) -> Result<(), Error> {
    let mut bounded = reader.take(expected_bytes + 1);
    let mut buffer = [0_u8; 64 * 1024];
    let mut observed = 0_u64;
    let mut hasher = Sha256::new();
    loop {
        let count = bounded.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        observed += count as u64;
        if observed > expected_bytes {
            return Err(Error::CorruptJournal("retained journal grew"));
        }
        hasher.update(&buffer[..count]);
    }
    let observed_digest: [u8; 32] = hasher.finalize().into();
    if observed != expected_bytes || observed_digest != expected_digest {
        return Err(Error::CorruptJournal("retained journal content changed"));
    }
    Ok(())
}
