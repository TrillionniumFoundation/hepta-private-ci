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

    fn replace(
        &self,
        temporary: &str,
        name: &str,
        bytes: &[u8],
    ) -> Result<(), AuthorityTrustError> {
        let mut file = self.open_private(temporary, OFlags::RDWR | OFlags::CREATE)?;
        // Validate type/ownership/link count before truncating even a stale
        // temporary entry left by a killed broker.
        file.set_len(0).map_err(unavailable)?;
        file.write_all(bytes).map_err(unavailable)?;
        file.sync_all().map_err(unavailable)?;
        rustix::fs::renameat(&self.directory, temporary, &self.directory, name)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        self.sync_directory()
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
        let file = self.root.open_private(&self.name, OFlags::RDONLY)?;
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

    fn persist(&self, frontier: &F) -> Result<(), AuthorityTrustError> {
        self.forget_durability()?;
        let bytes = serde_json::to_vec(&Record {
            schema: 1,
            owner_id: self.owner_id.clone(),
            frontier,
        })
        .map_err(|_| AuthorityTrustError::Invalid)?;
        if bytes.len() as u64 > MAX_RECORD_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
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
