//! The local half of the release owner's external-CAS transaction. A retained
//! attempt is an unresolved effect, even when a later frontier read is old.

use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use crate::FleetRegistryError;
use crate::release_authority::invalid;

#[path = "release_authority_store_reconciliation.rs"]
mod reconciliation;
pub(crate) use reconciliation::IntentRecoveryFiles;
pub(crate) use reconciliation::IntentRecoveryWinner;
#[cfg(test)]
pub(crate) use reconciliation::fail_once_after_reconciliation_proposal;

pub(crate) const MAX_AUTHORITY_BYTES: usize = 32 * 1024 * 1024;
pub(crate) const MAX_SET_BYTES: usize = 8 * 1024 * 1024;
const JOURNAL: &str = "journal.v1.json";
const PROPOSAL: &str = "proposal.v1.json";
const ATTEMPT: &str = "attempt.v1.json";

#[derive(Clone, Debug)]
pub(crate) struct AuthorityFiles {
    root: PathBuf,
}

impl AuthorityFiles {
    pub fn create(root: PathBuf) -> Result<Self, FleetRegistryError> {
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;

            if !entry_exists(&root)? {
                std::fs::DirBuilder::new().mode(0o700).create(&root)?;
                sync(
                    root.parent()
                        .ok_or_else(|| invalid("release owner directory has no parent"))?,
                )?;
            }
        }
        Self::open(root)
    }

    pub fn open(root: PathBuf) -> Result<Self, FleetRegistryError> {
        for ancestor in root.ancestors() {
            let metadata = std::fs::symlink_metadata(ancestor)?;
            if !metadata.is_dir() || metadata.file_type().is_symlink() {
                return Err(invalid(
                    "release authority requires physical directory ancestors",
                ));
            }
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;

            if std::fs::metadata(&root)?.permissions().mode() & 0o777 != 0o700 {
                return Err(invalid("release authority directory must be private"));
            }
        }
        Ok(Self { root })
    }

    pub fn lock(&self) -> Result<File, FleetRegistryError> {
        let lock = self.recovery_lock()?;
        if entry_exists(&self.root.join(ATTEMPT))?
            || entry_exists(&self.root.join(PROPOSAL))?
            || self.has_intent_reconciliation()?
        {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        Ok(lock)
    }

    pub fn recovery_lock(&self) -> Result<File, FleetRegistryError> {
        let lock = open_private(&self.root.join("owner.lock"), OpenMode::Lock)?;
        lock.try_lock()
            .map_err(|error| invalid(format!("release authority is busy: {error}")))?;
        Ok(lock)
    }

    pub fn journal(&self) -> Result<Vec<u8>, FleetRegistryError> {
        read_private(&self.root.join(JOURNAL), MAX_AUTHORITY_BYTES)
    }

    pub fn journal_exists(&self) -> Result<bool, FleetRegistryError> {
        entry_exists(&self.root.join(JOURNAL))
    }

    pub fn attempt(&self) -> Result<Vec<u8>, FleetRegistryError> {
        read_private(&self.root.join(ATTEMPT), 16 * 1024)
    }

    pub fn proposed_journal(&self) -> Result<(Vec<u8>, bool), FleetRegistryError> {
        if entry_exists(&self.root.join(PROPOSAL))? {
            Ok((
                read_private(&self.root.join(PROPOSAL), MAX_AUTHORITY_BYTES)?,
                true,
            ))
        } else {
            // A crash may happen after rename and before removing the attempt.
            Ok((self.journal()?, false))
        }
    }

    /// The caller must first prove the fresh external frontier is exactly this
    /// attempt's proposal, including the entire journal and M15 checkpoint.
    pub fn finish_completed(&self, proposal_exists: bool) -> Result<(), FleetRegistryError> {
        if proposal_exists {
            self.publish()
        } else {
            sync(&self.root)?;
            std::fs::remove_file(self.root.join(ATTEMPT))?;
            sync(&self.root)
        }
    }

    /// Called before external CAS. Both records survive any uncertain response;
    /// no caller may infer nonexecution by subsequently observing the old value.
    pub fn prepare(&self, journal: &[u8], attempt: &[u8]) -> Result<(), FleetRegistryError> {
        if journal.len() > MAX_AUTHORITY_BYTES || attempt.len() > 16 * 1024 {
            return Err(invalid(
                "release authority journal or attempt exceeds its bound",
            ));
        }
        write_private(&self.root.join(PROPOSAL), journal)?;
        write_private(&self.root.join(ATTEMPT), attempt)?;
        sync(&self.root)
    }

    /// Only a validated successful exact CAS acknowledgment permits this call.
    /// The attempt remains present throughout journal publication and syncing.
    pub fn publish(&self) -> Result<(), FleetRegistryError> {
        std::fs::rename(self.root.join(PROPOSAL), self.root.join(JOURNAL))?;
        sync(&self.root)?;
        std::fs::remove_file(self.root.join(ATTEMPT))?;
        sync(&self.root)
    }
}

enum OpenMode {
    Read,
    Create,
    Lock,
}

#[cfg(unix)]
fn open_private(path: &Path, mode: OpenMode) -> Result<File, FleetRegistryError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    let mut options = OpenOptions::new();
    options
        .read(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    match mode {
        OpenMode::Read => {}
        OpenMode::Create => {
            options.write(true).create_new(true);
        }
        OpenMode::Lock => {
            options.write(true).create(true);
        }
    }
    let file = options.open(path)?;
    let metadata = file.metadata()?;
    let parent = std::fs::metadata(
        path.parent()
            .ok_or_else(|| invalid("release file has no parent"))?,
    )?;
    if !metadata.is_file()
        || metadata.permissions().mode() & 0o777 != 0o600
        || metadata.uid() != parent.uid()
        || metadata.nlink() != 1
    {
        return Err(invalid(
            "release authority file must be private, regular, and unaliased",
        ));
    }
    Ok(file)
}

#[cfg(not(unix))]
fn open_private(_path: &Path, _mode: OpenMode) -> Result<File, FleetRegistryError> {
    Err(invalid("PQ release authority requires Unix file ownership"))
}

pub(crate) fn read_private(path: &Path, bound: usize) -> Result<Vec<u8>, FleetRegistryError> {
    let file = open_private(path, OpenMode::Read)?;
    let length = file.metadata()?.len();
    if length > bound as u64 {
        return Err(invalid("release authority input exceeds its bound"));
    }
    let mut bytes = Vec::new();
    file.take(bound as u64 + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != length {
        return Err(invalid(
            "release authority input changed or exceeded its bound",
        ));
    }
    Ok(bytes)
}

fn write_private(path: &Path, bytes: &[u8]) -> Result<(), FleetRegistryError> {
    let mut file = open_private(path, OpenMode::Create)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn sync(path: &Path) -> Result<(), FleetRegistryError> {
    #[cfg(unix)]
    let directory = {
        use std::os::unix::fs::OpenOptionsExt;
        OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
            .open(path)?
    };
    #[cfg(not(unix))]
    let directory = File::open(path)?;
    directory.sync_all()?;
    Ok(())
}

fn entry_exists(path: &Path) -> Result<bool, FleetRegistryError> {
    match std::fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}
