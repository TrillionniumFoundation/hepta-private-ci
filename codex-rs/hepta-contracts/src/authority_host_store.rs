//! OS-protected, separately located authority frontiers for a local host.
//!
//! The root-owned broker uses this backend outside the Agent's writable state.
//! It protects against an unprivileged writer replacing its own authority
//! directory. It does not protect against root or rollback of the whole host.

use crate::AuthorityFrontierStore;
use crate::AuthorityTrustError;
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;
use sha2::Digest;
use sha2::Sha256;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::marker::PhantomData;
use std::os::unix::fs::MetadataExt;
use std::path::Component;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;

use rustix::fs::AtFlags;
use rustix::fs::FlockOperation;
use rustix::fs::Mode;
use rustix::fs::OFlags;

const MAX_RECORD_BYTES: u64 = 16 * 1024;

#[path = "authority_host_issuer.rs"]
mod issuer;
pub use issuer::HostFinalUseIssuer;
pub use issuer::HostIssuerError;

#[path = "authority_host_store_initialization.rs"]
mod initialization;

#[path = "authority_host_observation.rs"]
mod observation;
pub use observation::RootStoredObservation;

enum DirectoryAccess {
    Ancestor,
    Private,
}

/// Retained root-owned directory, opened through non-writable root ancestors.
/// No Agent-writable path, symlink, or caller-provided ownership claim is used.
pub struct RootAuthorityDirectory {
    directory: File,
    owner_uid: u32,
    #[cfg(test)]
    before_directory_sync: std::sync::Mutex<Option<DurabilityHook>>,
}

#[cfg(test)]
type DurabilityHook = Arc<dyn Fn() -> std::io::Result<()> + Send + Sync>;

impl RootAuthorityDirectory {
    /// Open an existing mode-0700 root-owned authority directory. The caller
    /// must be the root broker; initialization/deployment creates it first.
    pub fn open(path: &Path) -> Result<Arc<Self>, AuthorityTrustError> {
        if rustix::process::geteuid().as_raw() != 0 || !path.is_absolute() {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut directory = open_directory(None, Path::new("/"))?;
        check_directory(&directory, 0, DirectoryAccess::Ancestor)?;
        for component in path.components() {
            match component {
                Component::RootDir => {}
                Component::Normal(name) => {
                    directory = open_directory(Some(&directory), Path::new(name))?;
                    check_directory(&directory, 0, DirectoryAccess::Ancestor)?;
                }
                _ => return Err(AuthorityTrustError::Invalid),
            }
        }
        check_directory(&directory, 0, DirectoryAccess::Private)?;
        Ok(Arc::new(Self {
            directory,
            owner_uid: 0,
            #[cfg(test)]
            before_directory_sync: std::sync::Mutex::new(None),
        }))
    }

    fn open_private(&self, name: &str, access: OFlags) -> Result<File, AuthorityTrustError> {
        let file: File = rustix::fs::openat(
            &self.directory,
            name,
            access | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(|_| AuthorityTrustError::Unavailable)?
        .into();
        let metadata = file.metadata().map_err(unavailable)?;
        if !metadata.is_file()
            || metadata.uid() != self.owner_uid
            || metadata.mode() & 0o777 != 0o600
            || metadata.nlink() != 1
        {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(file)
    }

    fn lock(&self, name: &str) -> Result<File, AuthorityTrustError> {
        let file = self.open_private(name, OFlags::RDWR | OFlags::CREATE)?;
        rustix::fs::flock(&file, FlockOperation::NonBlockingLockExclusive)
            .map_err(|_| AuthorityTrustError::Conflict)?;
        let path = rustix::fs::statat(&self.directory, name, AtFlags::SYMLINK_NOFOLLOW)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let descriptor = rustix::fs::fstat(&file).map_err(|_| AuthorityTrustError::Unavailable)?;
        if path.st_dev != descriptor.st_dev || path.st_ino != descriptor.st_ino {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(file)
    }

    fn exists(&self, name: &str) -> Result<bool, AuthorityTrustError> {
        match rustix::fs::statat(&self.directory, name, AtFlags::SYMLINK_NOFOLLOW) {
            Ok(_) => Ok(true),
            Err(rustix::io::Errno::NOENT) => Ok(false),
            Err(_) => Err(AuthorityTrustError::Unavailable),
        }
    }

    fn prepare_replace(
        &self,
        temporary: &str,
        name: &str,
    ) -> Result<PreparedRootReplacement<'_>, AuthorityTrustError> {
        let file = self.open_private(temporary, OFlags::RDWR | OFlags::CREATE)?;
        // Validate type/ownership/link count before truncating even a stale
        // temporary entry left by a killed broker. This prepares only the
        // unpublished temporary inode, never the canonical frontier.
        file.set_len(0).map_err(unavailable)?;
        Ok(PreparedRootReplacement {
            root: self,
            temporary: temporary.to_owned(),
            name: name.to_owned(),
            file,
        })
    }

    fn replace(
        &self,
        temporary: &str,
        name: &str,
        bytes: &[u8],
    ) -> Result<(), AuthorityTrustError> {
        self.prepare_replace(temporary, name)?.commit(bytes)
    }

    fn sync_directory(&self) -> Result<(), AuthorityTrustError> {
        // Controlled tests pause/fail acknowledgement at the actual boundary
        // after rename, without claiming a simulated power-loss result.
        #[cfg(test)]
        {
            let hook = self
                .before_directory_sync
                .lock()
                .map_err(|_| AuthorityTrustError::Unavailable)?
                .clone();
            if let Some(hook) = hook {
                hook().map_err(unavailable)?;
            }
        }
        self.directory.sync_all().map_err(unavailable)
    }
}

// Private, non-cloneable preparation under the caller's original owner lock.
// Preparing it publishes no record. All callers consume it through the same
// original durability sequence, and no descriptor escapes to another owner.
struct PreparedRootReplacement<'a> {
    root: &'a RootAuthorityDirectory,
    temporary: String,
    name: String,
    file: File,
}

impl PreparedRootReplacement<'_> {
    fn commit(mut self, bytes: &[u8]) -> Result<(), AuthorityTrustError> {
        self.file.write_all(bytes).map_err(unavailable)?;
        self.file.sync_all().map_err(unavailable)?;
        rustix::fs::renameat(
            &self.root.directory,
            &self.temporary,
            &self.root.directory,
            &self.name,
        )
        .map_err(|_| AuthorityTrustError::Unavailable)?;
        self.root.sync_directory()
    }
}

fn open_directory(parent: Option<&File>, path: &Path) -> Result<File, AuthorityTrustError> {
    let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
    let descriptor = match parent {
        Some(parent) => rustix::fs::openat(parent, path, flags, Mode::empty()),
        None => rustix::fs::open(path, flags, Mode::empty()),
    }
    .map_err(|_| AuthorityTrustError::Invalid)?;
    Ok(descriptor.into())
}

fn check_directory(
    file: &File,
    owner: u32,
    access: DirectoryAccess,
) -> Result<(), AuthorityTrustError> {
    let metadata = file.metadata().map_err(unavailable)?;
    let valid_permissions = match access {
        DirectoryAccess::Ancestor => metadata.mode() & 0o022 == 0,
        DirectoryAccess::Private => metadata.mode() & 0o777 == 0o700,
    };
    if !metadata.is_dir() || metadata.uid() != owner || !valid_permissions {
        return Err(AuthorityTrustError::Invalid);
    }
    Ok(())
}

fn unavailable(_: std::io::Error) -> AuthorityTrustError {
    AuthorityTrustError::Unavailable
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Record<F> {
    schema: u32,
    owner_id: String,
    frontier: F,
}

/// Durable CAS backend for the original authority owner's frontier type.
/// The broker alone holds the root directory. Clients use its authenticated
/// private channel; this type does not issue grants or maintain an outbox.
pub struct HostAuthorityFrontierStore<F> {
    root: Arc<RootAuthorityDirectory>,
    owner_id: String,
    name: String,
    _frontier: PhantomData<fn() -> F>,
    durable: Mutex<Option<DurableRecord>>,
}

// Published records are immutable replacements under the owner lock. Retain
// the synced inode so it cannot be recycled, and compare the entire encoding.
struct DurableRecord {
    file: File,
    bytes: Vec<u8>,
}
impl DurableRecord {
    fn matches(&self, observed: &Self) -> Result<bool, AuthorityTrustError> {
        let retained = self.file.metadata().map_err(unavailable)?;
        let current = observed.file.metadata().map_err(unavailable)?;
        Ok(retained.dev() == current.dev()
            && retained.ino() == current.ino()
            && self.bytes == observed.bytes)
    }
}

impl<F: Serialize + DeserializeOwned + Eq> HostAuthorityFrontierStore<F> {
    /// Register a new authority frontier exactly once. An existing entry is a
    /// conflict, including after restart; it is never replaced by genesis.
    pub fn initialize(
        root: Arc<RootAuthorityDirectory>,
        owner_id: String,
        initial: F,
    ) -> Result<Self, AuthorityTrustError> {
        let store = Self::configured(root, owner_id)?;
        let _lock = store.publication_lock()?;
        if store.root.exists(&store.name)? {
            return Err(AuthorityTrustError::Conflict);
        }
        store.persist(&initial)?;
        store.acknowledge_persisted(&initial)?;
        Ok(store)
    }

    /// Prepare a genuinely absent frontier before constructing its value.
    /// The original clock uses this to avoid aging a one-second sample while
    /// opening/validating/truncating an unpublished temporary file. There is
    /// still exactly one construction attempt and one durability attempt.
    pub(crate) fn initialize_prepared(
        root: Arc<RootAuthorityDirectory>,
        owner_id: String,
        construct: impl FnOnce() -> Result<F, AuthorityTrustError>,
    ) -> Result<(Self, F), AuthorityTrustError> {
        let store = Self::configured(root, owner_id)?;
        let _lock = store.publication_lock()?;
        if store.root.exists(&store.name)? {
            return Err(AuthorityTrustError::Conflict);
        }
        let prepared = store.prepare_persist()?;
        let initial = construct()?;
        store.persist_prepared(prepared, &initial)?;
        store.acknowledge_persisted(&initial)?;
        Ok((store, initial))
    }

    /// Same original CAS fence, with value construction after complete
    /// expected-record validation and unpublished temporary-file preparation.
    /// A wrong owner, stale preimage, contested lock or invalid temporary inode
    /// cannot invoke the constructor or publish any replacement.
    pub(crate) fn compare_and_set_prepared(
        &self,
        owner_id: &str,
        expected: &F,
        construct: impl FnOnce() -> Result<F, AuthorityTrustError>,
    ) -> Result<F, AuthorityTrustError> {
        if owner_id != self.owner_id {
            return Err(AuthorityTrustError::Invalid);
        }
        let _lock = self.publication_lock()?;
        if &self.read()? != expected {
            return Err(AuthorityTrustError::Conflict);
        }
        let prepared = self.prepare_persist()?;
        let next = construct()?;
        self.persist_prepared(prepared, &next)?;
        self.acknowledge_persisted(&next)?;
        Ok(next)
    }

    /// Open an existing registration without creating or repairing state.
    pub fn open(
        root: Arc<RootAuthorityDirectory>,
        owner_id: String,
    ) -> Result<Self, AuthorityTrustError> {
        let store = Self::configured(root, owner_id)?;
        let _lock = store.publication_lock()?;
        store.read_durable()?;
        Ok(store)
    }

    /// Inspect one durably read record while retaining its original publication
    /// lock. The callback may act on another original owner, but must not
    /// re-enter this store. A second durable read checks the entire unchanged
    /// record before returning. This never creates a record or advances it.
    ///
    /// A callback error is deliberately returned inside the outer result: the
    /// post-callback durability check still runs after any external mutation.
    pub fn with_locked_durable<R>(
        &self,
        owner_id: &str,
        inspect: impl FnOnce(&F) -> R,
    ) -> Result<R, AuthorityTrustError> {
        if owner_id != self.owner_id {
            return Err(AuthorityTrustError::Invalid);
        }
        let _lock = self.publication_lock()?;
        let before = self.read_durable()?;
        let result = inspect(&before);
        if self.read_durable()? != before {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(result)
    }

    fn configured(
        root: Arc<RootAuthorityDirectory>,
        owner_id: String,
    ) -> Result<Self, AuthorityTrustError> {
        if owner_id.is_empty()
            || owner_id.len() > 128
            || !owner_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let digest = Sha256::digest(owner_id.as_bytes());
        let suffix: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
        Ok(Self {
            root,
            owner_id,
            name: format!("frontier-v1-{suffix}.json"),
            _frontier: PhantomData,
            durable: Mutex::new(None),
        })
    }

    fn forget_durability(&self) -> Result<(), AuthorityTrustError> {
        *self
            .durable
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)? = None;
        Ok(())
    }

    fn publication_lock(&self) -> Result<File, AuthorityTrustError> {
        match self.root.lock(&format!("{}.lock", self.name)) {
            Ok(lock) => Ok(lock),
            Err(error) => {
                self.forget_durability()?;
                Err(error)
            }
        }
    }

    fn read(&self) -> Result<F, AuthorityTrustError> {
        match self.read_record() {
            Ok((frontier, _)) => Ok(frontier),
            Err(error) => {
                self.forget_durability()?;
                Err(error)
            }
        }
    }

    // Caller holds the publication lock. A retained, already synced immutable
    // inode with exactly equal bytes is a durability witness; visibility,
    // size/mtime or a cached hash alone are never sufficient.
    fn read_durable(&self) -> Result<F, AuthorityTrustError> {
        let mut durable = self
            .durable
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let (frontier, observed) = match self.read_record() {
            Ok(record) => record,
            Err(error) => {
                *durable = None;
                return Err(error);
            }
        };
        let same = match durable
            .as_ref()
            .map(|record| record.matches(&observed))
            .transpose()
        {
            Ok(same) => same == Some(true),
            Err(error) => {
                *durable = None;
                return Err(error);
            }
        };
        if !same {
            *durable = None;
            observed.file.sync_all().map_err(unavailable)?;
            self.root.sync_directory()?;
            *durable = Some(observed);
        }
        Ok(frontier)
    }

    // persist has completed file+directory sync under this same owner lock.
    // Retain only the exact readback of that newly acknowledged replacement.
    fn acknowledge_persisted(&self, expected: &F) -> Result<(), AuthorityTrustError> {
        let (observed, record) = self.read_record()?;
        if &observed != expected {
            return Err(AuthorityTrustError::Unavailable);
        }
        *self
            .durable
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)? = Some(record);
        Ok(())
    }

    fn read_record(&self) -> Result<(F, DurableRecord), AuthorityTrustError> {
        self.read_opened_record(self.root.open_private(&self.name, OFlags::RDONLY)?)
    }

    fn read_opened_record(&self, file: File) -> Result<(F, DurableRecord), AuthorityTrustError> {
        if file.metadata().map_err(unavailable)?.len() > MAX_RECORD_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut bytes = Vec::new();
        (&file)
            .take(MAX_RECORD_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(unavailable)?;
        if bytes.len() as u64 > MAX_RECORD_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
        let value: Record<F> =
            serde_json::from_slice(&bytes).map_err(|_| AuthorityTrustError::Invalid)?;
        if value.schema != 1 || value.owner_id != self.owner_id {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok((value.frontier, DurableRecord { file, bytes }))
    }

    fn encode(&self, frontier: &F) -> Result<Vec<u8>, AuthorityTrustError> {
        let bytes = serde_json::to_vec(&Record {
            schema: 1,
            owner_id: self.owner_id.clone(),
            frontier,
        })
        .map_err(|_| AuthorityTrustError::Invalid)?;
        if bytes.len() as u64 > MAX_RECORD_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(bytes)
    }

    fn prepare_persist(&self) -> Result<PreparedRootReplacement<'_>, AuthorityTrustError> {
        match self
            .root
            .prepare_replace(&format!("{}.next", self.name), &self.name)
        {
            Ok(prepared) => Ok(prepared),
            Err(error) => {
                self.forget_durability()?;
                Err(error)
            }
        }
    }

    fn persist_prepared(
        &self,
        prepared: PreparedRootReplacement<'_>,
        frontier: &F,
    ) -> Result<(), AuthorityTrustError> {
        // A constructor failure has not touched the canonical inode. Once
        // actual publication starts, retain the original uncertainty rule:
        // no old durability witness survives a failed encode/write/sync.
        self.forget_durability()?;
        let bytes = self.encode(frontier)?;
        prepared.commit(&bytes)
    }

    fn persist(&self, frontier: &F) -> Result<(), AuthorityTrustError> {
        self.forget_durability()?;
        let bytes = self.encode(frontier)?;
        self.root
            .replace(&format!("{}.next", self.name), &self.name, &bytes)
    }
}

impl<F: Serialize + DeserializeOwned + Eq + Clone> AuthorityFrontierStore<F>
    for HostAuthorityFrontierStore<F>
{
    fn load(&self, owner_id: &str) -> Result<F, AuthorityTrustError> {
        if owner_id != self.owner_id {
            return Err(AuthorityTrustError::Invalid);
        }
        let _lock = self.publication_lock()?;
        self.read_durable()
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &F,
        next: &F,
    ) -> Result<(), AuthorityTrustError> {
        if owner_id != self.owner_id {
            return Err(AuthorityTrustError::Invalid);
        }
        let _lock = self.publication_lock()?;
        if &self.read()? != expected {
            return Err(AuthorityTrustError::Conflict);
        }
        self.persist(next)?;
        self.acknowledge_persisted(next)?;
        Ok(())
    }
}

#[cfg(test)]
#[path = "authority_host_store_tests.rs"]
mod tests;
