//! Feature-gated test-only durable recovery-grant nonce reservation.
//! This journal MUST be an independently owner-pinned stable directory,
//! not freshly selected by a submitted grant/caller. An indeterminate
//! reservation is never cleared or retried automatically: HOLD.
//!
//! Reservations are O_EXCL before any Witness ACK. This is NOT a
//! globally replicated nonce owner, independent product authority,
//! trusted clock, actual crash/powercut durability attestation, or
//! an approval to repair the original market PAPER ledger.
use std::fs::{self, File};
use std::io::Write;
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
        // On UNIX, open the exact DIRECTORY handle without following a
        // symlink, then compare fstat and lstat identities. No caller may
        // substitute a different original nonce owner during this open.
        #[cfg(unix)]
        {
            use rustix::fs::{self as unixfs, Mode, OFlags};
            use std::os::unix::fs::{MetadataExt, PermissionsExt};
            let before = fs::symlink_metadata(path)
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
            if !before.is_dir() || before.file_type().is_symlink()
                || before.permissions().mode() & 0o777 != 0o700
                // Safe rustix wrapper, preserving forbid(unsafe_code).
                || before.uid()!=rustix::process::geteuid().as_raw()
            {
                return Err(AckOnlyRecoveryError::NonceStoreUnavailable);
            }
            let directory = File::from(
                unixfs::open(
                    path,
                    OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                    Mode::empty(),
                )
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?,
            );
            let opened = directory
                .metadata()
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
            let after = fs::symlink_metadata(path)
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
            if !opened.is_dir()
                || opened.dev() != before.dev()
                || opened.ino() != before.ino()
                || after.dev() != opened.dev()
                || after.ino() != opened.ino()
                || after.uid() != opened.uid()
                || after.permissions().mode() & 0o777 != 0o700
            {
                return Err(AckOnlyRecoveryError::NonceStoreUnavailable);
            }
            directory
                .sync_all()
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
            Ok(Self {
                directory,
                path: path.to_owned(),
            })
        }
        #[cfg(not(unix))]
        {
            let _ = path;
            Err(AckOnlyRecoveryError::NonceStoreUnavailable)
        }
    }

    pub(crate) fn reserve(
        &mut self,
        grant: &AckOnlyRecoveryGrantV1,
    ) -> Result<Digest32, AckOnlyRecoveryError> {
        self.reserve_with_after_check(grant, || {})
    }

    #[cfg(test)]
    pub(crate) fn reserve_with_test_rebind(
        &mut self,
        grant: &AckOnlyRecoveryGrantV1,
        injected_rebind: impl FnOnce(),
    ) -> Result<Digest32, AckOnlyRecoveryError> {
        self.reserve_with_after_check(grant, injected_rebind)
    }

    /// Private injection seam used ONLY for adversarial tests to arrange an
    /// exact rename+rebind BETWEEN the precheck and dirfd-relative create.
    /// In production the closure is hardwired to the empty no-op above.
    fn reserve_with_after_check(
        &mut self,
        grant: &AckOnlyRecoveryGrantV1,
        after_precheck: impl FnOnce(),
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
        // Test-only race hook: even if the OWNER directory pathname is
        // renamed or replaced NOW, all subsequent filesystem creation is
        // rooted in the open directory FD, never redirected to new path.
        after_precheck();
        let mut filename = String::from("nonce-");
        for part in grant.grant_nonce.as_array() {
            use std::fmt::Write as _;
            write!(filename, "{part:02x}")
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        }
        // Every grant that attempts to use the SAME nonce in this
        // authoritative original owner directory maps to ONE file.
        // Create the deterministic name RELATIVE TO THE PINNED OPEN DIRFD.
        // The old OpenOptions::open(self.path.join(...)) would re-resolve the
        // path after the inode check, leaving a TOCTOU redirection window.
        #[cfg(unix)]
        let mut file = {
            use rustix::fs::{Mode, OFlags, openat};
            // Safe rustix openat resolves only relative to the pinned
            // open directory handle and preserves forbid(unsafe_code).
            let flags =
                OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC;
            let mode = Mode::from_bits_truncate(0o600);
            match openat(&self.directory, filename.as_str(), flags, mode) {
                Ok(fd) => File::from(fd),
                Err(error) if error == rustix::io::Errno::EXIST => {
                    return Err(AckOnlyRecoveryError::NonceAlreadyReservedOrIndeterminate);
                }
                Err(_) => return Err(AckOnlyRecoveryError::NonceStoreUnavailable),
            }
        };
        #[cfg(not(unix))]
        let mut file: File = {
            return Err(AckOnlyRecoveryError::NonceStoreUnavailable);
        };
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
        // Refuse success if the submitted owner path was replaced while
        // fsync ran; the nonce remains reserved in the original dirfd.
        // Never delete an ambiguous reservation or proceed to Witness ACK.
        #[cfg(unix)]
        {
            use std::os::unix::fs::{MetadataExt, PermissionsExt};
            let actual = self
                .directory
                .metadata()
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
            let visible = fs::symlink_metadata(&self.path)
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
            if !visible.is_dir()
                || visible.file_type().is_symlink()
                || visible.dev() != actual.dev()
                || visible.ino() != actual.ino()
                || visible.uid() != actual.uid()
                || visible.permissions().mode() & 0o777 != 0o700
            {
                return Err(AckOnlyRecoveryError::NonceStoreUnavailable);
            }
        }
        Ok(receipt)
    }
}
