//! Feature-gated test-only durable recovery-grant nonce reservation.
//! This journal MUST be an independently owner-pinned stable directory,
//! not freshly selected by a submitted grant/caller. An indeterminate
//! reservation is never cleared or retried automatically: HOLD.
//!
//! Reservations are O_EXCL before any Witness ACK. This is NOT a
//! globally replicated nonce owner, independent product authority,
//! trusted clock, actual crash/powercut durability attestation, or
//! an approval to repair the original market PAPER ledger.
use rustix::fs::Mode;
use rustix::fs::OFlags;
use rustix::io::Errno;
use std::fmt::Write as _;
use std::fs;
use std::fs::File;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use crate::ack_only_recovery::AckOnlyRecoveryError;
use crate::ack_only_recovery::AckOnlyRecoveryGrantV1;

const DOMAIN: &[u8] = b"hepta.ackonly-qualification-reserved-once.v1";

pub struct AckOnlyGrantNonceJournalV1 {
    directory: File,
    path: PathBuf,
}
impl AckOnlyGrantNonceJournalV1 {
    /// The product host, never a submitted grant, supplies this preexisting
    /// owner-only and stable directory. No auto-create or symlink following.
    pub fn open_preexisting(path: &Path) -> Result<Self, AckOnlyRecoveryError> {
        let directory = File::from(
            rustix::fs::open(
                path,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?,
        );
        let journal = Self {
            directory,
            path: path.to_owned(),
        };
        journal.check_directory_identity()?;
        journal
            .directory
            .sync_all()
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        Ok(journal)
    }

    fn check_directory_identity(&self) -> Result<(), AckOnlyRecoveryError> {
        let saved = self
            .directory
            .metadata()
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        let live = fs::symlink_metadata(&self.path)
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        if !live.is_dir()
            || live.dev() != saved.dev()
            || live.ino() != saved.ino()
            || live.uid() != saved.uid()
            || saved.uid() != rustix::process::geteuid().as_raw()
            || live.permissions().mode() & 0o777 != 0o700
        {
            return Err(AckOnlyRecoveryError::NonceStoreUnavailable);
        }
        Ok(())
    }

    pub(crate) fn reserve(
        &mut self,
        grant: &AckOnlyRecoveryGrantV1,
    ) -> Result<Digest32, AckOnlyRecoveryError> {
        self.check_directory_identity()?;
        let mut filename = String::from("nonce-");
        for part in grant.grant_nonce.as_array() {
            write!(filename, "{part:02x}")
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        }
        // Resolve the nonce relative to the held directory, not the path
        // just checked. A concurrent rename cannot redirect the write.
        let mut file = match rustix::fs::openat(
            &self.directory,
            filename.as_str(),
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::RUSR | Mode::WUSR,
        ) {
            Ok(fd) => File::from(fd),
            Err(Errno::EXIST) => {
                return Err(AckOnlyRecoveryError::NonceAlreadyReservedOrIndeterminate);
            }
            Err(_) => return Err(AckOnlyRecoveryError::NonceStoreUnavailable),
        };
        file.set_permissions(fs::Permissions::from_mode(0o600))
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        let mut bytes = DOMAIN.to_vec();
        bytes.extend_from_slice(grant.grant_nonce.as_array());
        bytes.extend_from_slice(Digest32::of_bytes(&grant.signing_bytes()).as_array());
        bytes.extend_from_slice(&grant.recovery_signature);
        let receipt = Digest32::of_bytes(&bytes);
        // Never delete a possibly partially written reservation. Retain
        // it as an indeterminate proof requiring manual reconciliation.
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .and_then(|_| self.directory.sync_all())
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        self.check_directory_identity()?;
        Ok(receipt)
    }
}
