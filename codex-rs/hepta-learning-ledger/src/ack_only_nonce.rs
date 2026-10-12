//! Feature-gated test-only durable recovery-grant nonce reservation.
//! This journal MUST be an independently owner-pinned stable directory,
//! not freshly selected by a submitted grant/caller. An indeterminate
//! reservation is never cleared or retried automatically: HOLD.
//!
//! Reservations are O_EXCL before any Witness ACK. This is NOT a
//! globally replicated nonce owner, independent product authority,
//! trusted clock, actual crash/powercut durability attestation, or
//! an approval to repair the original market PAPER ledger.
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use codex_hepta_types::Digest32;

use crate::ack_only_recovery::{AckOnlyRecoveryError, AckOnlyRecoveryGrantV1};

const DOMAIN: &[u8] = b"hepta.ackonly-qualification-reserved-once.v1";

pub struct AckOnlyGrantNonceJournalV1 {
    directory: File,
    path: PathBuf,
}
impl AckOnlyGrantNonceJournalV1 {
    /// The product host, never a submitted grant, supplies this preexisting
    /// owner-only and stable directory. No auto-create or symlink following.
    pub fn open_preexisting(path: &Path) -> Result<Self, AckOnlyRecoveryError> {
        let metadata =
            fs::symlink_metadata(path).map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        if !metadata.is_dir() || metadata.file_type().is_symlink() {
            return Err(AckOnlyRecoveryError::NonceStoreUnavailable);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if metadata.permissions().mode() & 0o777 != 0o700 {
                return Err(AckOnlyRecoveryError::NonceStoreUnavailable);
            }
        }
        let directory =
            File::open(path).map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        directory
            .sync_all()
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        Ok(Self {
            directory,
            path: path.to_owned(),
        })
    }

    pub(crate) fn reserve(
        &mut self,
        grant: &AckOnlyRecoveryGrantV1,
    ) -> Result<Digest32, AckOnlyRecoveryError> {
        // Catch a swapped directory/symlink between initialization and
        // reservation. This is still a qualification-level check, NOT an
        // openat2 / mount-namespace proof of a product owner-pinned store.
        #[cfg(unix)]
        {
            use std::os::unix::fs::{MetadataExt, PermissionsExt};
            let saved = self
                .directory
                .metadata()
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
            let live = fs::symlink_metadata(&self.path)
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
            if !live.is_dir()
                || live.file_type().is_symlink()
                || live.dev() != saved.dev()
                || live.ino() != saved.ino()
                || live.uid() != saved.uid()
                || live.permissions().mode() & 0o777 != 0o700
            {
                return Err(AckOnlyRecoveryError::NonceStoreUnavailable);
            }
        }
        let mut filename = String::from("nonce-");
        for part in grant.grant_nonce.as_array() {
            use std::fmt::Write as _;
            write!(filename, "{part:02x}")
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        }
        // Every grant that attempts to use the SAME nonce in this
        // authoritative original owner directory maps to ONE file.
        let path = self.path.join(filename);
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = match options.open(&path) {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                return Err(AckOnlyRecoveryError::NonceAlreadyReservedOrIndeterminate);
            }
            Err(_) => return Err(AckOnlyRecoveryError::NonceStoreUnavailable),
        };
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            file.set_permissions(fs::Permissions::from_mode(0o600))
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        }
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
        Ok(receipt)
    }
}
