//! Kernel-time projection and a root frontier outside workload state.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use serde::Deserialize;
use serde::Serialize;

use crate::ProcessDriverError;

const OWNER: &str = "local-supervisor-resources";
static SEQUENCE: AtomicU64 = AtomicU64::new(1);

pub(super) fn validate_root_directory(path: &Path) -> Result<(), ProcessDriverError> {
    if !path.is_absolute() || path.canonicalize()? != path {
        return Err(ProcessDriverError::new(
            "root-owned path must be canonical and absolute",
        ));
    }
    for parent in path.ancestors() {
        let metadata = std::fs::symlink_metadata(parent)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(ProcessDriverError::new(
                "root authority ancestors must deny workload writes",
            ));
        }
    }
    Ok(())
}

pub(super) fn read_root_file(path: &Path, maximum: u64) -> Result<Vec<u8>, ProcessDriverError> {
    validate_root_directory(
        path.parent()
            .ok_or_else(|| ProcessDriverError::new("root file has no parent"))?,
    )?;
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.uid() != 0
        || metadata.nlink() != 1
        || metadata.mode() & 0o022 != 0
        || metadata.len() > maximum
    {
        return Err(ProcessDriverError::new(
            "root policy must be a bounded protected regular file",
        ));
    }
    let mut bytes = Vec::new();
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(ProcessDriverError::new(
            "root policy grew beyond its read bound",
        ));
    }
    Ok(bytes)
}

pub(super) struct HostClock {
    base_ms: u64,
    started: Instant,
}
impl HostClock {
    pub(super) fn system_now() -> Result<u64, ProcessDriverError> {
        let elapsed = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(super::host_error)?;
        u64::try_from(elapsed.as_millis()).map_err(super::host_error)
    }
    pub(super) fn new() -> Result<Self, ProcessDriverError> {
        Ok(Self {
            base_ms: Self::system_now()?,
            started: Instant::now(),
        })
    }
}
impl AuthorityClock for HostClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let elapsed = u64::try_from(self.started.elapsed().as_millis())
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let projected = self
            .base_ms
            .checked_add(elapsed)
            .ok_or(AuthorityTrustError::Unavailable)?;
        let wall = Self::system_now().map_err(|_| AuthorityTrustError::Unavailable)?;
        if wall.saturating_add(1000) < projected {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(projected)
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Record {
    owner_id: String,
    frontier: AuthorityLeaseFrontier,
}

pub(super) struct RootResourceFrontier {
    path: PathBuf,
    writer: Mutex<()>,
}
impl RootResourceFrontier {
    pub(super) fn open(path: &Path) -> Result<Self, ProcessDriverError> {
        let parent = path
            .parent()
            .ok_or_else(|| ProcessDriverError::new("external frontier has no parent"))?;
        validate_root_directory(parent)?;
        let record = Record {
            owner_id: OWNER.into(),
            frontier: AuthorityLeaseFrontier::for_empty_epoch(1).map_err(super::host_error)?,
        };
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(path)
        {
            Ok(mut file) => {
                file.write_all(&serde_json::to_vec(&record)?)?;
                file.sync_all()?;
                File::open(parent)?.sync_all()?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error.into()),
        }
        let result = Self {
            path: path.to_path_buf(),
            writer: Mutex::new(()),
        };
        result.load(OWNER).map_err(super::host_error)?;
        Ok(result)
    }
}
impl AuthorityFrontierStore<AuthorityLeaseFrontier> for RootResourceFrontier {
    fn load(&self, owner_id: &str) -> Result<AuthorityLeaseFrontier, AuthorityTrustError> {
        if owner_id != OWNER {
            return Err(AuthorityTrustError::Invalid);
        }
        let record: Record = serde_json::from_slice(
            &read_root_file(&self.path, 4096).map_err(|_| AuthorityTrustError::Unavailable)?,
        )
        .map_err(|_| AuthorityTrustError::Invalid)?;
        if record.owner_id != OWNER {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(record.frontier)
    }
    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &AuthorityLeaseFrontier,
        next: &AuthorityLeaseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        let _writer = self
            .writer
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if self.load(owner_id)? != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        let temporary = self.path.with_extension(format!(
            "{}-{}.tmp",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        let result = (|| -> Result<(), ProcessDriverError> {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .custom_flags(libc::O_NOFOLLOW)
                .open(&temporary)?;
            file.write_all(&serde_json::to_vec(&Record {
                owner_id: OWNER.into(),
                frontier: *next,
            })?)?;
            file.sync_all()?;
            std::fs::rename(&temporary, &self.path)?;
            File::open(self.path.parent().expect("validated frontier parent"))?.sync_all()?;
            Ok(())
        })();
        let _ = std::fs::remove_file(temporary);
        result.map_err(|_| AuthorityTrustError::Unavailable)
    }
}
