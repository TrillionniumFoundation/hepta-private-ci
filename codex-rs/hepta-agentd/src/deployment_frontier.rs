//! Private, durable host frontiers for a user-owned Linux deployment.
//!
//! Store this directory outside the Agentd/FinalUse state directories and their
//! backup/restore set. This protects against rollback of those local stores;
//! it does not claim protection against the host administrator rolling back
//! every disk. It stores trust frontiers, never a second operation ledger.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Write;
use std::marker::PhantomData;
use std::os::fd::AsRawFd;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;
use sha2::Digest;
use sha2::Sha256;

const MAX_RECORD_BYTES: usize = 64 * 1024;
const LOCK_DEADLINE: Duration = Duration::from_secs(2);
static TEMP_ID: AtomicU64 = AtomicU64::new(1);

/// An explicitly provisioned external frontier directory. Opening never resets
/// a missing/corrupt record. A separate OS account/service can own this store;
/// same-UID code is not an isolation boundary.
pub struct DeploymentFrontierStore<F> {
    directory: PathBuf,
    value: PhantomData<fn() -> F>,
    protected: Option<ProtectedBackend<F>>,
}

struct ProtectedBackend<F> {
    directory: Arc<RootAuthorityDirectory>,
    registered: Mutex<Option<Arc<HostAuthorityFrontierStore<F>>>>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Record<F> {
    schema_version: u32,
    owner_id: String,
    frontier: F,
}

impl<F> DeploymentFrontierStore<F>
where
    F: Clone + Eq + Serialize + DeserializeOwned,
{
    /// Create a new private trust directory. Existing paths are refused so
    /// deployment cannot silently turn a lost frontier into an empty one.
    pub fn create(directory: &Path) -> io::Result<Self> {
        if !directory.is_absolute() {
            return Err(io::Error::other("frontier directory must be absolute"));
        }
        std::fs::DirBuilder::new().mode(0o700).create(directory)?;
        File::open(
            directory
                .parent()
                .ok_or_else(|| io::Error::other("no parent"))?,
        )?
        .sync_all()?;
        Self::open(directory)
    }

    /// Open a previously provisioned private directory without mutating it.
    pub fn open(directory: &Path) -> io::Result<Self> {
        let metadata = std::fs::symlink_metadata(directory)?;
        // SAFETY: geteuid has no arguments or borrowed memory.
        let uid = unsafe { libc::geteuid() };
        if !directory.is_absolute()
            || !metadata.is_dir()
            || metadata.file_type().is_symlink()
            || metadata.uid() != uid
            || metadata.mode() & 0o777 != 0o700
        {
            return Err(io::Error::other(
                "frontier directory must be owned private 0700",
            ));
        }
        Ok(Self {
            directory: directory.to_path_buf(),
            value: PhantomData,
            protected: None,
        })
    }

    /// Root service construction only. The parent must already be a protected
    /// private directory; a missing mount/parent is not implicitly provisioned.
    pub(crate) fn create_protected(directory: &Path) -> io::Result<Self> {
        RootAuthorityDirectory::open(
            directory
                .parent()
                .ok_or_else(|| io::Error::other("no protected parent"))?,
        )
        .map_err(io::Error::other)?;
        std::fs::DirBuilder::new().mode(0o700).create(directory)?;
        File::open(
            directory
                .parent()
                .ok_or_else(|| io::Error::other("no parent"))?,
        )?
        .sync_all()?;
        Self::open_protected(directory)
    }

    pub(crate) fn open_protected(directory: &Path) -> io::Result<Self> {
        Ok(Self {
            directory: directory.to_path_buf(),
            value: PhantomData,
            protected: Some(ProtectedBackend {
                directory: RootAuthorityDirectory::open(directory).map_err(io::Error::other)?,
                registered: Mutex::new(None),
            }),
        })
    }

    fn protected_store(
        &self,
        owner: &str,
    ) -> Result<Option<Arc<HostAuthorityFrontierStore<F>>>, AuthorityTrustError> {
        let Some(protected) = &self.protected else {
            return Ok(None);
        };
        let mut registered = protected
            .registered
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if registered.is_none() {
            *registered = Some(Arc::new(HostAuthorityFrontierStore::open(
                protected.directory.clone(),
                owner.into(),
            )?));
        }
        Ok(registered.clone())
    }

    /// Provision a single reviewed original-owner initial frontier. This is an
    /// administrative bootstrap operation and always refuses an existing key.
    pub fn provision(&self, owner_id: &str, frontier: &F) -> io::Result<()> {
        if let Some(protected) = &self.protected {
            let mut registered = protected
                .registered
                .lock()
                .map_err(|_| io::Error::other("protected store lock"))?;
            if registered.is_some() {
                return Err(io::Error::other("protected owner already registered"));
            }
            let store = HostAuthorityFrontierStore::initialize(
                protected.directory.clone(),
                owner_id.into(),
                frontier.clone(),
            )
            .map_err(io::Error::other)?;
            *registered = Some(Arc::new(store));
            return Ok(());
        }
        let _guard = self.lock()?;
        let path = self.record_path(owner_id)?;
        let bytes = Self::encode(owner_id, frontier)?;
        let mut file = Self::private_options()
            .write(true)
            .create_new(true)
            .open(path)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        File::open(&self.directory)?.sync_all()
    }

    /// Explicit original Root bootstrap completion; ordinary provision/open
    /// never invoke this path. A different retained state is not replaced.
    pub(crate) fn resume_protected_initialization(
        &self,
        owner_id: &str,
        initial: &F,
    ) -> io::Result<()> {
        let protected = self.protected.as_ref().ok_or_else(|| {
            io::Error::other("initialization resume requires the protected owner")
        })?;
        let mut registered = protected
            .registered
            .lock()
            .map_err(|_| io::Error::other("protected store lock"))?;
        if registered.is_some() {
            return Err(io::Error::other("protected owner already registered"));
        }
        let store = HostAuthorityFrontierStore::resume_initialization(
            protected.directory.clone(),
            owner_id.into(),
            initial.clone(),
        )
        .map_err(io::Error::other)?;
        *registered = Some(Arc::new(store));
        Ok(())
    }

    fn record_path(&self, owner_id: &str) -> io::Result<PathBuf> {
        if owner_id.is_empty() || owner_id.len() > 128 || owner_id.as_bytes().contains(&0) {
            return Err(io::Error::other("invalid frontier owner"));
        }
        let hash = Sha256::digest(owner_id.as_bytes());
        Ok(self.directory.join(format!("{hash:x}.json")))
    }

    fn private_options() -> OpenOptions {
        let mut options = OpenOptions::new();
        options
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
        options
    }

    fn check_file(file: &File) -> io::Result<()> {
        let metadata = file.metadata()?;
        // SAFETY: geteuid has no arguments or borrowed memory.
        let uid = unsafe { libc::geteuid() };
        if !metadata.is_file()
            || metadata.uid() != uid
            || metadata.mode() & 0o777 != 0o600
            || metadata.nlink() != 1
        {
            return Err(io::Error::other(
                "frontier file must be owned private regular 0600",
            ));
        }
        Ok(())
    }

    fn lock(&self) -> io::Result<File> {
        // Use a fresh open file description per operation: flock on one shared
        // descriptor would not serialize two threads in this process.
        let file = Self::private_options()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.directory.join("frontier.lock"))?;
        Self::check_file(&file)?;
        let deadline = Instant::now() + LOCK_DEADLINE;
        loop {
            // SAFETY: file owns a live FD; flock retains no pointer.
            if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
                return Ok(file);
            }
            let error = io::Error::last_os_error();
            if error.kind() != io::ErrorKind::WouldBlock || Instant::now() >= deadline {
                return Err(error);
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }

    fn read_record(&self, owner_id: &str) -> io::Result<F> {
        let file = Self::private_options()
            .read(true)
            .open(self.record_path(owner_id)?)?;
        Self::check_file(&file)?;
        let mut bytes = Vec::new();
        file.take((MAX_RECORD_BYTES + 1) as u64)
            .read_to_end(&mut bytes)?;
        if bytes.len() > MAX_RECORD_BYTES {
            return Err(io::Error::other("frontier record is oversized"));
        }
        let record: Record<F> = serde_json::from_slice(&bytes)?;
        if record.schema_version != 1 || record.owner_id != owner_id {
            return Err(io::Error::other("frontier owner or schema mismatch"));
        }
        Ok(record.frontier)
    }

    fn encode(owner_id: &str, frontier: &F) -> io::Result<Vec<u8>> {
        let bytes = serde_json::to_vec(&Record {
            schema_version: 1,
            owner_id: owner_id.to_string(),
            frontier,
        })?;
        if bytes.len() > MAX_RECORD_BYTES {
            return Err(io::Error::other("frontier record is oversized"));
        }
        Ok(bytes)
    }

    fn commit_record(&self, owner_id: &str, next: &F) -> io::Result<()> {
        let bytes = Self::encode(owner_id, next)?;
        let temporary = self.directory.join(format!(
            ".frontier-{}-{}.pending",
            std::process::id(),
            TEMP_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let mut file = Self::private_options()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        let result = (|| {
            file.write_all(&bytes)?;
            file.sync_all()?;
            std::fs::rename(&temporary, self.record_path(owner_id)?)?;
            File::open(&self.directory)?.sync_all()
        })();
        if result.is_err() {
            // Removing an unpublished temporary does not reset the frontier.
            // A failure after rename remains uncertain and the owner fences.
            let _ = std::fs::remove_file(&temporary);
        }
        result
    }
}

impl<F> AuthorityFrontierStore<F> for DeploymentFrontierStore<F>
where
    F: Clone + Eq + Serialize + DeserializeOwned,
{
    fn load(&self, owner_id: &str) -> Result<F, AuthorityTrustError> {
        if let Some(store) = self.protected_store(owner_id)? {
            return store.load(owner_id);
        }
        let _guard = self.lock().map_err(|_| AuthorityTrustError::Unavailable)?;
        self.read_record(owner_id)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &F,
        next: &F,
    ) -> Result<(), AuthorityTrustError> {
        if let Some(store) = self.protected_store(owner_id)? {
            return store.compare_and_set(owner_id, expected, next);
        }
        let _guard = self.lock().map_err(|_| AuthorityTrustError::Unavailable)?;
        let current = self
            .read_record(owner_id)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if &current != expected {
            return Err(AuthorityTrustError::Conflict);
        }
        self.commit_record(owner_id, next)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }
}

#[cfg(test)]
#[path = "deployment_frontier_tests.rs"]
mod tests;
