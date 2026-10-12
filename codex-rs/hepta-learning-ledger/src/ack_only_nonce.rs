//! FEATURE-GATED TEST ONLY: persist a *target-event* reservation BEFORE
//! persisting the separate RecoveryGrant nonce, and both BEFORE witness ACK.
//! Neither file is ever deleted/replaced/reissued on indeterminate outcomes.
//!
//! Storage authority is LOCAL: the PRODUCT host must pin the same owner dir
//! across all workers, hosts and clones. This code is NOT a global owner,
//! escrow signer, trusted time source or production RecoveryAuthority.
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};

use codex_hepta_types::Digest32;

use crate::ack_only_recovery::{AckOnlyRecoveryError, AckOnlyRecoveryGrantV1};

const NONCE_DOMAIN: &[u8] = b"hepta.ackonly-qualification-reserved-once.v2";
const TARGET_DOMAIN: &[u8] = b"hepta.ackonly-qualification-event-target-once.v1";

pub struct AckOnlyGrantNonceJournalV1 {
    directory: File,
    path: PathBuf,
}

impl AckOnlyGrantNonceJournalV1 {
    /// The product host, never an incoming grant, must provision a fixed,
    /// independently owner-pinned private nonce journal. Default feature OFF.
    pub fn open_preexisting(path: &Path) -> Result<Self, AckOnlyRecoveryError> {
        #[cfg(unix)]
        {
            use rustix::fs::{self as unixfs, Mode, OFlags};
            use std::os::unix::fs::{MetadataExt, PermissionsExt};
            let before = fs::symlink_metadata(path)
                .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
            if !before.is_dir()
                || before.file_type().is_symlink()
                || before.permissions().mode() & 0o777 != 0o700
                || before.uid() != rustix::process::geteuid().as_raw()
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

    /// A grant's *target* fingerprint deliberately EXCLUDES grant ID, nonce,
    /// issuance window and signature. Two independently valid DIFFERENT
    /// RecoveryGrants for the SAME durable original event must collide.
    fn target_digest(grant: &AckOnlyRecoveryGrantV1) -> Digest32 {
        let mut bytes = TARGET_DOMAIN.to_vec();
        for digest in [
            grant.ledger_binding,
            grant.objective_digest,
            grant.original_authentication_digest,
            grant.previous_witness.chain_digest,
            grant.target_anchor.chain_digest,
            grant.target_event_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&grant.previous_witness.sequence.to_be_bytes());
        bytes.extend_from_slice(&grant.target_anchor.sequence.to_be_bytes());
        let id = grant.original_record_id.as_str().as_bytes();
        bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(id);
        Digest32::of_bytes(&bytes)
    }

    fn hex(digest: Digest32) -> String {
        const DIGITS: &[u8; 16] = b"0123456789abcdef";
        let mut value = String::with_capacity(64);
        for byte in digest.as_array() {
            value.push(char::from(DIGITS[usize::from(byte >> 4)]));
            value.push(char::from(DIGITS[usize::from(byte & 0x0f)]));
        }
        value
    }

    fn ensure_owner_path_is_original_fd(&self) -> Result<(), AckOnlyRecoveryError> {
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
            Ok(())
        }
        #[cfg(not(unix))]
        {
            Err(AckOnlyRecoveryError::NonceStoreUnavailable)
        }
    }

    /// Never resolve a mutable pathname for file creation. The held dirfd
    /// must remain authoritative even across rename+rebind TOCTOU attempts.
    fn create_once(
        &self,
        filename: &str,
        already_used: AckOnlyRecoveryError,
    ) -> Result<File, AckOnlyRecoveryError> {
        #[cfg(unix)]
        {
            use rustix::fs::{Mode, OFlags, openat};
            let flags =
                OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC;
            match openat(
                &self.directory,
                filename,
                flags,
                Mode::from_bits_truncate(0o600),
            ) {
                Ok(fd) => Ok(File::from(fd)),
                Err(error) if error == rustix::io::Errno::EXIST => Err(already_used),
                Err(_) => Err(AckOnlyRecoveryError::NonceStoreUnavailable),
            }
        }
        #[cfg(not(unix))]
        {
            let _ = (filename, already_used);
            Err(AckOnlyRecoveryError::NonceStoreUnavailable)
        }
    }

    fn persist_one(&self, mut file: File, data: &[u8]) -> Result<(), AckOnlyRecoveryError> {
        // Every partial reservation is permanent HOLD. Even if sync fails,
        // no filename is removed or rewritten by this component.
        file.write_all(data)
            .and_then(|_| file.sync_all())
            .and_then(|_| self.directory.sync_all())
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)
    }

    pub(crate) fn reserve(
        &mut self,
        grant: &AckOnlyRecoveryGrantV1,
    ) -> Result<Digest32, AckOnlyRecoveryError> {
        self.reserve_with_hooks(grant, || {}, || {})
    }

    #[cfg(test)]
    pub(crate) fn reserve_with_test_rebind(
        &mut self,
        grant: &AckOnlyRecoveryGrantV1,
        injected_rebind: impl FnOnce(),
    ) -> Result<Digest32, AckOnlyRecoveryError> {
        self.reserve_with_hooks(grant, injected_rebind, || {})
    }

    #[cfg(test)]
    pub(crate) fn reserve_with_test_target_fsync_exit(
        &mut self,
        grant: &AckOnlyRecoveryGrantV1,
        injected_exit: impl FnOnce(),
    ) -> Result<Digest32, AckOnlyRecoveryError> {
        self.reserve_with_hooks(grant, || {}, injected_exit)
    }

    /// Test-only hooks permit precise fault injection after the owner FD
    /// precheck or target-file fsync. Normal callers get TWO hardcoded
    /// no-op hooks above; nothing in production can choose a callback.
    fn reserve_with_hooks(
        &mut self,
        grant: &AckOnlyRecoveryGrantV1,
        after_precheck: impl FnOnce(),
        after_target_fsync: impl FnOnce(),
    ) -> Result<Digest32, AckOnlyRecoveryError> {
        self.ensure_owner_path_is_original_fd()?;
        after_precheck();

        // FIRST reserve the immutable original Ledger event/ACK pair, so a
        // completely DIFFERENT signed grant nonce cannot recover the SAME
        // original event a second time within this owner-held directory.
        let target = Self::target_digest(grant);
        let target_filename = format!("target-{}", Self::hex(target));
        let target_file = self.create_once(
            &target_filename,
            AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate,
        )?;
        let mut target_bytes = TARGET_DOMAIN.to_vec();
        target_bytes.extend_from_slice(target.as_array());
        target_bytes.extend_from_slice(grant.grant_nonce.as_array());
        target_bytes.extend_from_slice(Digest32::of_bytes(&grant.signing_bytes()).as_array());
        target_bytes.extend_from_slice(&grant.recovery_signature);
        self.persist_one(target_file, &target_bytes)?;

        // A crash RIGHT HERE is deliberately fail-closed: target remains
        // reserved, nonce does not exist, and another grant must not retry.
        after_target_fsync();

        // SECOND enforce global-by-nonce uniqueness within this SAME owner
        // directory. If the nonce already belongs to a different target,
        // the target reservation above stays as an indeterminate HOLD.
        let nonce_filename = format!("nonce-{}", Self::hex(grant.grant_nonce));
        let nonce_file = self.create_once(
            &nonce_filename,
            AckOnlyRecoveryError::NonceAlreadyReservedOrIndeterminate,
        )?;
        let mut nonce_bytes = NONCE_DOMAIN.to_vec();
        nonce_bytes.extend_from_slice(grant.grant_nonce.as_array());
        nonce_bytes.extend_from_slice(target.as_array());
        nonce_bytes.extend_from_slice(Digest32::of_bytes(&grant.signing_bytes()).as_array());
        nonce_bytes.extend_from_slice(&grant.recovery_signature);
        self.persist_one(nonce_file, &nonce_bytes)?;
        self.ensure_owner_path_is_original_fd()?;

        let mut receipt_bytes = target_bytes;
        receipt_bytes.extend_from_slice(&nonce_bytes);
        Ok(Digest32::of_bytes(&receipt_bytes))
    }
}
