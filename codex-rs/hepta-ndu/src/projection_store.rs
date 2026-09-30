//! Crash-bounded durable writer candidate for NDU projection state.
//!
//! The V1 durability profile is Unix-only because it requires atomic replacement
//! of an existing path plus parent-directory synchronization before success is
//! acknowledged. Other platforms fail closed until an equivalent reviewed
//! persistence profile exists.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_types::Digest32;

use crate::NduProjectionEntryV1;
use crate::NduProjectionJournalError;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;

const LOCK_FILE: &str = ".ndu-projection.lock";
const JOURNAL_FILE: &str = "projection.journal";
const TEMP_FILE: &str = ".projection.journal.tmp";
const MAX_BACKUP_BYTES: usize = 12 + 4096 * (8 + 1 + 32 + 32 + 32 + 32 + 32 + 32);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionStoreError {
    UnsupportedPlatform,
    Busy,
    NotDirectory,
    NotRegular,
    Symlink,
    UnsafeOwnerPath,
    OwnershipChanged,
    UnsupportedFilesystem,
    BackupTooLarge,
    BackupRegression,
    Journal(NduProjectionJournalError),
    Io(io::ErrorKind),
    /// A rename may have committed but directory durability was not
    /// acknowledged. The open handle is poisoned and must be reopened before
    /// authoritative reads, backup export, restore or further mutation.
    Indeterminate,
}

impl fmt::Display for NduProjectionStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduProjectionStoreError {}

impl From<io::Error> for NduProjectionStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

impl From<NduProjectionJournalError> for NduProjectionStoreError {
    fn from(error: NduProjectionJournalError) -> Self {
        Self::Journal(error)
    }
}

/// Injectable persistence boundary used by the crash matrix. Production uses
/// the filesystem implementation below; tests inject failures at the exact
/// write, file-sync, rename and parent-directory-sync cuts while exercising the
/// same store mutation path.
trait ProjectionPersistenceV1: Send + Sync {
    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()>;
    fn sync_temp(&self, path: &Path) -> io::Result<()>;
    fn rename(&self, from: &Path, to: &Path) -> io::Result<()>;
    fn sync_parent(&self, root: &Path) -> io::Result<()>;

    /// A visible image may be a rename whose directory sync was interrupted.
    /// Reopen must establish durability before authorizing no-write replay.
    /// This separate seam lets recovery faults be injected without conflating
    /// them with a later mutation's file-sync or directory-sync cut.
    fn confirm_recovered(&self, journal: &File, root: &Path) -> io::Result<()> {
        journal.sync_all()?;
        FsProjectionPersistenceV1.sync_parent(root)
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct FsProjectionPersistenceV1;

impl ProjectionPersistenceV1 for FsProjectionPersistenceV1 {
    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        let mut file = open_regular(path, true, true)?;
        file.write_all(bytes)
    }

    fn sync_temp(&self, path: &Path) -> io::Result<()> {
        open_regular(path, false, false)?.sync_all()
    }

    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        fs::rename(from, to)
    }

    fn sync_parent(&self, root: &Path) -> io::Result<()> {
        #[cfg(unix)]
        {
            File::open(root)?.sync_all()
        }
        #[cfg(not(unix))]
        {
            let _ = root;
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "NDU durable writer V1 requires Unix directory durability semantics",
            ))
        }
    }
}

/// Exclusive writer over one host-authorized projection directory.
///
/// Locks are advisory and therefore assume the directory is private to the
/// authenticated owner. A hostile process that races path replacement after
/// admission or ignores the lock is outside this mechanism's threat model.
/// Existing symlinked root/lock/journal paths are rejected before use.
pub struct NduProjectionStoreV1 {
    root: PathBuf,
    lock: File,
    directory: File,
    filesystem_profile: &'static str,
    journal: NduProjectionJournalV1,
    persistence: Arc<dyn ProjectionPersistenceV1>,
    indeterminate: bool,
}

impl NduProjectionStoreV1 {
    /// Opens or initializes the V1 store. The directory must already exist so
    /// repository code cannot silently widen filesystem authority. V1 is
    /// deliberately unavailable on non-Unix targets rather than silently using
    /// weaker replacement or directory-durability semantics.
    pub fn open(root: impl AsRef<Path>) -> Result<Self, NduProjectionStoreError> {
        Self::open_durable(root)
    }

    /// Explicit durable constructor. Errors never select an ephemeral journal.
    /// Linux admission excludes network/unknown filesystems. tmpfs and overlay
    /// are local test profiles, not proof of power-loss durability.
    pub fn open_durable(root: impl AsRef<Path>) -> Result<Self, NduProjectionStoreError> {
        Self::open_with_persistence(root, Arc::new(FsProjectionPersistenceV1))
    }

    fn open_with_persistence(
        root: impl AsRef<Path>,
        persistence: Arc<dyn ProjectionPersistenceV1>,
    ) -> Result<Self, NduProjectionStoreError> {
        let result = Self::open_unobserved(root, persistence);
        let metrics = crate::operational_metrics::process_metrics();
        match &result {
            Ok(store) => {
                metrics.set_journal_bytes(store.journal.encoded_len() as u64);
                metrics.record_store_open(!store.journal.entries().is_empty());
            }
            Err(NduProjectionStoreError::Journal(_)) => {
                metrics.record_corruption();
                metrics.record_reopen_failure();
            }
            Err(NduProjectionStoreError::Busy) => metrics.record_store_busy(),
            Err(_) => metrics.record_reopen_failure(),
        }
        result
    }

    fn open_unobserved(
        root: impl AsRef<Path>,
        persistence: Arc<dyn ProjectionPersistenceV1>,
    ) -> Result<Self, NduProjectionStoreError> {
        if !cfg!(unix) {
            return Err(NduProjectionStoreError::UnsupportedPlatform);
        }
        let root = root.as_ref().to_path_buf();
        let metadata = fs::symlink_metadata(&root)?;
        if metadata.file_type().is_symlink() {
            return Err(NduProjectionStoreError::Symlink);
        }
        if !metadata.is_dir() {
            return Err(NduProjectionStoreError::NotDirectory);
        }

        let directory = open_directory(&root)?;
        let filesystem_profile = local_filesystem_profile(&directory)?;
        let lock_path = root.join(LOCK_FILE);
        reject_existing_symlink(&lock_path)?;
        // Linux flock does not need write access. Keeping a writable lock FD
        // would pin the mount writable and prevent a real EROFS transition.
        let lock = open_lock(&lock_path)?;
        match File::try_lock(&lock) {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(NduProjectionStoreError::Busy),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }

        let temp_path = root.join(TEMP_FILE);
        match fs::remove_file(&temp_path) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }

        let journal_path = root.join(JOURNAL_FILE);
        reject_existing_symlink(&journal_path)?;
        let journal = match open_regular(&journal_path, false, false) {
            Ok(file) => {
                let metadata = file.metadata()?;
                if !metadata.is_file() {
                    return Err(NduProjectionStoreError::NotRegular);
                }
                let max_bytes = u64::try_from(MAX_BACKUP_BYTES)
                    .map_err(|_| NduProjectionStoreError::BackupTooLarge)?;
                if metadata.len() > max_bytes {
                    return Err(NduProjectionStoreError::BackupTooLarge);
                }
                let capacity = usize::try_from(metadata.len())
                    .map_err(|_| NduProjectionStoreError::BackupTooLarge)?;
                let mut bytes = Vec::with_capacity(capacity);
                let mut bounded = (&file).take(max_bytes.saturating_add(1));
                bounded.read_to_end(&mut bytes)?;
                if bytes.len() > MAX_BACKUP_BYTES {
                    return Err(NduProjectionStoreError::BackupTooLarge);
                }
                let journal = NduProjectionJournalV1::reopen(&bytes)?;
                // Reading a correctly hashed image proves visibility, not
                // durability. In particular, an exact replay performs no I/O.
                // Do not let a lost rename acknowledgement become a durable
                // acknowledgement merely by closing and reopening the store.
                if persistence.confirm_recovered(&file, &root).is_err() {
                    crate::operational_metrics::process_metrics().record_store_indeterminate();
                    return Err(NduProjectionStoreError::Indeterminate);
                }
                journal
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                let journal = NduProjectionJournalV1::new();
                persist_image(&root, &journal, persistence.as_ref())?;
                journal
            }
            Err(error) => return Err(error.into()),
        };

        Ok(Self {
            root,
            lock,
            directory,
            filesystem_profile,
            journal,
            persistence,
            indeterminate: false,
        })
    }

    #[must_use]
    pub const fn filesystem_profile(&self) -> &'static str {
        self.filesystem_profile
    }

    /// Storage readiness only; not current authorization or release readiness.
    #[must_use]
    pub fn storage_ready(&self) -> bool {
        self.ensure_authoritative().is_ok()
    }

    #[must_use]
    pub const fn is_indeterminate(&self) -> bool {
        self.indeterminate
    }

    pub fn entries(&self) -> Result<&[NduProjectionEntryV1], NduProjectionStoreError> {
        self.ensure_authoritative()?;
        Ok(self.journal.entries())
    }

    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Result<Option<Digest32>, NduProjectionStoreError> {
        self.ensure_authoritative()?;
        Ok(self
            .journal
            .selected_projection_digest(objective_digest, subject_digest))
    }

    /// Returns a complete, self-validating backup image. The caller owns backup
    /// transport, encryption, retention and external acknowledgement.
    pub fn backup_bytes(&self) -> Result<Vec<u8>, NduProjectionStoreError> {
        self.ensure_authoritative()?;
        Ok(self.journal.export_bytes())
    }

    pub fn append_projection(
        &mut self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        self.commit(|journal| {
            journal.append_projection(
                kind,
                identity_digest,
                objective_digest,
                subject_digest,
                payload_digest,
            )
        })
    }

    /// Compatibility entry for first selection. Replacement callers must use
    /// `select_projection_if_current` with the exact current predecessor.
    pub fn select_projection(
        &mut self,
        operation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        self.select_projection_if_current(
            operation_identity_digest,
            objective_digest,
            subject_digest,
            None,
            projection_digest,
        )
    }

    pub fn select_projection_if_current(
        &mut self,
        operation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        expected_predecessor: Option<Digest32>,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        self.commit(|journal| {
            journal.select_projection_if_current(
                operation_identity_digest,
                objective_digest,
                subject_digest,
                expected_predecessor,
                projection_digest,
            )
        })
    }

    pub fn revoke_projection(
        &mut self,
        revocation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        self.commit(|journal| {
            journal.revoke_projection(
                revocation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
        })
    }

    /// Replaces the current state from a complete backup only after validating
    /// the whole hash chain and semantic transition history. Restore is
    /// monotonic: the current committed history must be an exact prefix of the
    /// backup. This prevents an older valid backup from deleting a later
    /// revocation or otherwise resurrecting stale selected state.
    pub fn restore_backup(&mut self, bytes: &[u8]) -> Result<(), NduProjectionStoreError> {
        let result = self.restore_unobserved(bytes);
        if result.is_err() {
            crate::operational_metrics::process_metrics().record_restore_failure();
        }
        result
    }

    fn restore_unobserved(&mut self, bytes: &[u8]) -> Result<(), NduProjectionStoreError> {
        self.ensure_authoritative()?;
        if bytes.len() > MAX_BACKUP_BYTES {
            return Err(NduProjectionStoreError::BackupTooLarge);
        }
        let restored = NduProjectionJournalV1::reopen(bytes)?;
        let current_len = self.journal.entries().len();
        if restored.entries().len() < current_len
            || &restored.entries()[..current_len] != self.journal.entries()
        {
            return Err(NduProjectionStoreError::BackupRegression);
        }
        if restored == self.journal {
            return Ok(());
        }
        self.ensure_authoritative()?;
        match persist_image(&self.root, &restored, self.persistence.as_ref()) {
            Ok(()) => {
                self.journal = restored;
                Ok(())
            }
            Err(NduProjectionStoreError::Indeterminate) => {
                self.indeterminate = true;
                Err(NduProjectionStoreError::Indeterminate)
            }
            Err(error) => Err(error),
        }
    }

    fn ensure_authoritative(&self) -> Result<(), NduProjectionStoreError> {
        if self.indeterminate {
            Err(NduProjectionStoreError::Indeterminate)
        } else {
            verify_owner_identity(&self.root, &self.directory, &self.lock)
        }
    }

    fn commit<F>(&mut self, mutation: F) -> Result<NduProjectionEntryV1, NduProjectionStoreError>
    where
        F: FnOnce(
            &mut NduProjectionJournalV1,
        ) -> Result<NduProjectionEntryV1, NduProjectionJournalError>,
    {
        self.ensure_authoritative()?;
        let mut candidate = self.journal.clone();
        let entry = mutation(&mut candidate)?;
        // Exact replay is already durable. Do not rewrite the complete image or
        // turn a historical acknowledgement into a new ambiguous disk commit.
        if candidate == self.journal {
            return Ok(entry);
        }
        self.ensure_authoritative()?;
        match persist_image(&self.root, &candidate, self.persistence.as_ref()) {
            Ok(()) => {
                self.journal = candidate;
                Ok(entry)
            }
            Err(NduProjectionStoreError::Indeterminate) => {
                self.indeterminate = true;
                Err(NduProjectionStoreError::Indeterminate)
            }
            Err(error) => Err(error),
        }
    }
}

impl Drop for NduProjectionStoreV1 {
    fn drop(&mut self) {
        // Mutation methods already synchronize before acknowledgement. Unlocking
        // here is only ownership cleanup, never a durability acknowledgement.
        let _ = File::unlock(&self.lock);
    }
}

// O_NONBLOCK avoids hanging on an attacker-supplied FIFO before fstat rejects it.
// Existing images may be owner-readable by others, but never writable by them.
// Product bootstrap separately requires a private 0700 owner directory.
fn open_lock(path: &Path) -> io::Result<File> {
    #[cfg(target_os = "linux")]
    {
        use rustix::fs::Mode;
        use rustix::fs::OFlags;
        let lock: File = rustix::fs::open(
            path,
            OFlags::RDONLY | OFlags::CREATE | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(io::Error::from)?
        .into();
        validate_regular(&lock)?;
        Ok(lock)
    }
    #[cfg(not(target_os = "linux"))]
    {
        open_regular(path, true, false)
    }
}

pub(crate) fn open_regular(path: &Path, create: bool, exclusive: bool) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true).write(create);
    if exclusive {
        options.create_new(true);
    } else if create {
        options.create(true).truncate(false);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600).custom_flags(
            (rustix::fs::OFlags::NOFOLLOW
                | rustix::fs::OFlags::NONBLOCK
                | rustix::fs::OFlags::CLOEXEC)
                .bits() as i32,
        );
    }
    let file = options.open(path)?;
    validate_regular(&file)?;
    Ok(file)
}

fn validate_regular(file: &File) -> io::Result<()> {
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "NDU state is not a regular file",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o022 != 0
            || metadata.nlink() != 1
            || metadata.uid() != rustix::process::geteuid().as_raw()
        {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "unsafe NDU file owner, permissions or hard links",
            ));
        }
    }
    Ok(())
}

pub(crate) fn open_directory(root: &Path) -> Result<File, NduProjectionStoreError> {
    #[cfg(unix)]
    {
        use rustix::fs::Mode;
        use rustix::fs::OFlags;
        use std::os::unix::fs::MetadataExt;
        let directory: File = rustix::fs::open(
            root,
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
        )
        .map_err(io::Error::from)?
        .into();
        let metadata = directory.metadata()?;
        if metadata.mode() & 0o022 != 0 || metadata.uid() != rustix::process::geteuid().as_raw() {
            return Err(NduProjectionStoreError::UnsafeOwnerPath);
        }
        Ok(directory)
    }
    #[cfg(not(unix))]
    {
        let _ = root;
        Err(NduProjectionStoreError::UnsupportedPlatform)
    }
}

fn verify_owner_identity(
    root: &Path,
    directory: &File,
    lock: &File,
) -> Result<(), NduProjectionStoreError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let current = open_directory(root)?;
        let current_lock = open_regular(&root.join(LOCK_FILE), false, false)?;
        let expected = directory.metadata()?;
        let actual = current.metadata()?;
        let expected_lock = lock.metadata()?;
        let actual_lock = current_lock.metadata()?;
        if (expected.dev(), expected.ino()) != (actual.dev(), actual.ino())
            || (expected_lock.dev(), expected_lock.ino()) != (actual_lock.dev(), actual_lock.ino())
        {
            return Err(NduProjectionStoreError::OwnershipChanged);
        }
        Ok(())
    }
    #[cfg(not(unix))]
    {
        let _ = (root, directory, lock);
        Err(NduProjectionStoreError::UnsupportedPlatform)
    }
}

fn local_filesystem_profile(directory: &File) -> Result<&'static str, NduProjectionStoreError> {
    #[cfg(target_os = "linux")]
    {
        let metadata = rustix::fs::fstatfs(directory).map_err(io::Error::from)?;
        // Linux UAPI magic values. Unknown, NFS, CIFS, 9P, Ceph and FUSE are
        // deliberately excluded, rather than assuming local lock/fsync behavior.
        match i128::from(metadata.f_type) {
            0xef53 => Ok("linux-ext"),
            0x5846_5342 => Ok("linux-xfs"),
            0x9123_683e => Ok("linux-btrfs"),
            0x2fc1_2fc1 => Ok("linux-zfs"),
            0xf2f5_2010 => Ok("linux-f2fs"),
            0x0102_1994 => Ok("linux-tmpfs-volatile"),
            0x794c_7630 => Ok("linux-overlay-unqualified-backing"),
            _ => Err(NduProjectionStoreError::UnsupportedFilesystem),
        }
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = directory;
        // Unix directory-sync support is retained. This label explicitly does
        // not establish the stronger Linux local-filesystem admission profile.
        Ok("unix-requires-target-filesystem-qualification")
    }
}

fn reject_existing_symlink(path: &Path) -> Result<(), NduProjectionStoreError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => Err(NduProjectionStoreError::Symlink),
        Ok(_) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn persist_image(
    root: &Path,
    journal: &NduProjectionJournalV1,
    persistence: &dyn ProjectionPersistenceV1,
) -> Result<(), NduProjectionStoreError> {
    let started = std::time::Instant::now();
    let result = persist_image_inner(root, journal, persistence);
    crate::operational_metrics::process_metrics()
        .record_persistence(started.elapsed(), result.is_err());
    result
}

fn persist_image_inner(
    root: &Path,
    journal: &NduProjectionJournalV1,
    persistence: &dyn ProjectionPersistenceV1,
) -> Result<(), NduProjectionStoreError> {
    if !cfg!(unix) {
        return Err(NduProjectionStoreError::UnsupportedPlatform);
    }
    let temp_path = root.join(TEMP_FILE);
    let journal_path = root.join(JOURNAL_FILE);
    let bytes = journal.export_bytes();
    if bytes.len() > MAX_BACKUP_BYTES {
        return Err(NduProjectionStoreError::BackupTooLarge);
    }

    match persistence.write_temp(&temp_path, &bytes) {
        Ok(()) => {}
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            fs::remove_file(&temp_path)?;
            persistence.write_temp(&temp_path, &bytes)?;
        }
        Err(error) => return Err(error.into()),
    }
    if let Err(error) = persistence.sync_temp(&temp_path) {
        let _ = fs::remove_file(&temp_path);
        return Err(error.into());
    }

    // A failed acknowledgement does not prove that replacement did not occur.
    // Preserve the candidate and fence this handle until reopen reconciles disk.
    if persistence.rename(&temp_path, &journal_path).is_err() {
        crate::operational_metrics::process_metrics().record_store_indeterminate();
        return Err(NduProjectionStoreError::Indeterminate);
    }
    if persistence.sync_parent(root).is_err() {
        crate::operational_metrics::process_metrics().record_store_indeterminate();
        return Err(NduProjectionStoreError::Indeterminate);
    }
    crate::operational_metrics::process_metrics().set_journal_bytes(bytes.len() as u64);
    Ok(())
}

#[cfg(test)]
#[path = "projection_store_tests.rs"]
mod tests;

#[cfg(all(test, unix))]
#[path = "projection_store_process_kill_tests.rs"]
mod process_kill_tests;

#[cfg(all(test, unix))]
#[path = "projection_store_recovery_tests.rs"]
mod recovery_tests;
