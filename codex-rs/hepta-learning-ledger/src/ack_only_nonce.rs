//! Feature-gated test-only durable recovery-grant nonce reservation.
//! This journal MUST be an independently owner-pinned stable directory,
//! not freshly selected by a submitted grant/caller. An indeterminate
//! reservation is never cleared or retried automatically: HOLD.
//!
//! Reservations are O_EXCL before any Witness ACK. This is NOT a
//! globally replicated nonce owner, independent product authority,
//! trusted clock, actual crash/powercut durability attestation, or
//! an approval to repair the original market PAPER ledger.
use rustix::fs::AtFlags;
use rustix::fs::Dir;
use rustix::fs::FileType;
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

const NONCE_DOMAIN: &[u8] = b"hepta.ackonly-qualification-reserved-once.v2";
const TARGET_DOMAIN: &[u8] = b"hepta.ackonly-qualification-event-target-once.v1";
const EVENT_JOURNAL_VERSION: &str = "event-reservations-v2";

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

    fn version_is_current(&self) -> Result<bool, AckOnlyRecoveryError> {
        match rustix::fs::statat(
            &self.directory,
            EVENT_JOURNAL_VERSION,
            AtFlags::SYMLINK_NOFOLLOW,
        ) {
            Ok(stat)
                if FileType::from_raw_mode(stat.st_mode) == FileType::Directory
                    && stat.st_uid == rustix::process::geteuid().as_raw()
                    && stat.st_mode & 0o077 == 0 =>
            {
                Ok(true)
            }
            Err(Errno::NOENT) => Ok(false),
            _ => Err(AckOnlyRecoveryError::NonceStoreUnavailable),
        }
    }

    fn ensure_event_journal(&self) -> Result<(), AckOnlyRecoveryError> {
        if self.version_is_current()? {
            return Ok(());
        }
        // V1 nonce bodies authenticate a grant but do not carry an event key.
        // Do not reinterpret, discard, or advance across an unmapped old grant.
        // Upgrade only after the owner has stopped V1 writers: they do not
        // understand the event-index format and cannot participate in it.
        let entries = Dir::read_from(&self.directory)
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        for entry in entries {
            let entry = entry.map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
            if entry.file_name().to_bytes().starts_with(b"nonce-") && !self.version_is_current()? {
                return Err(AckOnlyRecoveryError::LegacyNonceReservationRequiresReconciliation);
            }
        }
        match rustix::fs::mkdirat(
            &self.directory,
            EVENT_JOURNAL_VERSION,
            Mode::RUSR | Mode::WUSR | Mode::XUSR,
        ) {
            Ok(()) | Err(Errno::EXIST) => {}
            Err(_) => return Err(AckOnlyRecoveryError::NonceStoreUnavailable),
        }
        if !self.version_is_current()? {
            return Err(AckOnlyRecoveryError::NonceStoreUnavailable);
        }
        self.sync_directory()
    }

    fn sync_directory(&self) -> Result<(), AckOnlyRecoveryError> {
        self.directory
            .sync_all()
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)
    }

    fn event_digest(grant: &AckOnlyRecoveryGrantV1) -> Digest32 {
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

    fn reservation_name(prefix: &str, digest: Digest32) -> String {
        let mut name = String::with_capacity(prefix.len() + 64);
        name.push_str(prefix);
        for part in digest.as_array() {
            // Writing into a String is infallible.
            let _ = write!(name, "{part:02x}");
        }
        name
    }

    fn persist_once(
        &self,
        name: &str,
        bytes: &[u8],
        occupied: AckOnlyRecoveryError,
    ) -> Result<(), AckOnlyRecoveryError> {
        // Resolve relative to the held directory, never the visible path.
        let mut file = match rustix::fs::openat(
            &self.directory,
            name,
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::RUSR | Mode::WUSR,
        ) {
            Ok(fd) => File::from(fd),
            Err(Errno::EXIST) => return Err(occupied),
            Err(_) => return Err(AckOnlyRecoveryError::NonceStoreUnavailable),
        };
        // Retain even partial reservations for the owner to reconcile.
        file.set_permissions(fs::Permissions::from_mode(0o600))
            .and_then(|()| file.write_all(bytes))
            .and_then(|()| file.sync_all())
            .map_err(|_| AckOnlyRecoveryError::NonceStoreUnavailable)?;
        self.sync_directory()
    }

    pub(crate) fn reserve(
        &mut self,
        grant: &AckOnlyRecoveryGrantV1,
    ) -> Result<Digest32, AckOnlyRecoveryError> {
        self.check_directory_identity()?;
        self.ensure_event_journal()?;
        let nonce_name = Self::reservation_name("nonce-", grant.grant_nonce);
        let target = Self::event_digest(grant);
        let target_name = Self::reservation_name("target-", target);
        let body = Digest32::of_bytes(&grant.signing_bytes());

        let mut target_bytes = TARGET_DOMAIN.to_vec();
        target_bytes.extend_from_slice(target.as_array());
        target_bytes.extend_from_slice(grant.grant_nonce.as_array());
        target_bytes.extend_from_slice(body.as_array());
        target_bytes.extend_from_slice(&grant.recovery_signature);
        match self.persist_once(
            &target_name,
            &target_bytes,
            AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate,
        ) {
            Ok(()) => {}
            Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate) => {
                // Preserve the original duplicate-nonce error when that
                // reservation is already present. No bytes are modified.
                return match rustix::fs::statat(
                    &self.directory,
                    nonce_name.as_str(),
                    AtFlags::SYMLINK_NOFOLLOW,
                ) {
                    Ok(_) => Err(AckOnlyRecoveryError::NonceAlreadyReservedOrIndeterminate),
                    Err(Errno::NOENT) => {
                        Err(AckOnlyRecoveryError::EventAlreadyReservedOrIndeterminate)
                    }
                    Err(_) => Err(AckOnlyRecoveryError::NonceStoreUnavailable),
                };
            }
            Err(error) => return Err(error),
        }

        let mut nonce_bytes = NONCE_DOMAIN.to_vec();
        nonce_bytes.extend_from_slice(grant.grant_nonce.as_array());
        nonce_bytes.extend_from_slice(target.as_array());
        nonce_bytes.extend_from_slice(body.as_array());
        nonce_bytes.extend_from_slice(&grant.recovery_signature);
        self.persist_once(
            &nonce_name,
            &nonce_bytes,
            AckOnlyRecoveryError::NonceAlreadyReservedOrIndeterminate,
        )?;
        self.check_directory_identity()?;
        target_bytes.extend_from_slice(&nonce_bytes);
        Ok(Digest32::of_bytes(&target_bytes))
    }
}
