use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseFrontier;

pub(super) fn protected_directory(path: &Path) -> anyhow::Result<()> {
    anyhow::ensure!(path.is_absolute(), "protected path must be absolute");
    for ancestor in path.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        anyhow::ensure!(
            metadata.is_dir() && metadata.uid() == 0 && metadata.mode() & 0o022 == 0,
            "authority directory is not protected: {}",
            ancestor.display()
        );
    }
    Ok(())
}

pub(super) fn read_protected(
    path: &Path,
    maximum: usize,
    private: bool,
) -> anyhow::Result<Vec<u8>> {
    protected_directory(path.parent().context("protected file has no parent")?)?;
    let mut file = File::options()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let metadata = file.metadata()?;
    anyhow::ensure!(
        metadata.is_file()
            && metadata.uid() == 0
            && metadata.nlink() == 1
            && metadata.mode() & if private { 0o077 } else { 0o022 } == 0,
        "authority file is not protected: {}",
        path.display()
    );
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take(u64::try_from(maximum)? + 1)
        .read_to_end(&mut bytes)?;
    anyhow::ensure!(
        bytes.len() <= maximum,
        "authority file exceeds its size bound"
    );
    Ok(bytes)
}

pub(super) fn write_atomic(path: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    let parent = path.parent().context("authority state has no parent")?;
    protected_directory(parent)?;
    let temporary = parent.join(format!(".issuer-{}", uuid::Uuid::new_v4()));
    let result = (|| -> anyhow::Result<()> {
        let mut file = File::options()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        std::fs::rename(&temporary, path)?;
        File::open(parent)?.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(temporary);
    }
    result
}

pub(super) fn publish_identity(path: &Path, bytes: &[u8], gid: u32) -> anyhow::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    write_atomic(path, bytes)?;
    std::os::unix::fs::chown(path, Some(0), Some(gid))?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o640))?;
    File::open(path)?.sync_all()?;
    Ok(())
}

/// A root-protected wall-clock floor that survives service restart. Backward
/// clock movement fences issuance. This is a host time source, not hardware
/// attestation, and never accepts time from a workload request.
pub(super) struct ProtectedClock {
    path: PathBuf,
    last: Mutex<u64>,
}

impl ProtectedClock {
    pub(super) fn open(path: PathBuf) -> anyhow::Result<Self> {
        let last = if path.try_exists()? {
            u64::from_be_bytes(
                read_protected(&path, 8, true)?
                    .try_into()
                    .map_err(|_| anyhow::anyhow!("invalid protected clock floor"))?,
            )
        } else {
            0
        };
        let clock = Self {
            path,
            last: Mutex::new(last),
        };
        clock.now_unix_ms()?;
        Ok(clock)
    }
}

impl AuthorityClock for ProtectedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .ok()
            .and_then(|v| u64::try_from(v.as_millis()).ok())
            .ok_or(AuthorityTrustError::Unavailable)?;
        let mut last = self
            .last
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if now < *last {
            return Err(AuthorityTrustError::Unavailable);
        }
        write_atomic(&self.path, &now.to_be_bytes())
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        *last = now;
        Ok(now)
    }
}

/// The trusted frontier lives outside the replaceable issuer authority state.
/// The root service owns an exclusive lock for this directory throughout its
/// lifetime, and checks the persisted frontier on every CAS.
pub(super) struct ProtectedFrontier {
    path: PathBuf,
    current: Mutex<FinalUseFrontier>,
    _lock: File,
}

impl ProtectedFrontier {
    pub(super) fn open(
        directory: &Path,
        initial: FinalUseFrontier,
        state_is_empty: bool,
    ) -> anyhow::Result<Self> {
        protected_directory(directory)?;
        let lock = File::options()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(directory.join("issuer.lock"))?;
        let metadata = lock.metadata()?;
        anyhow::ensure!(
            metadata.uid() == 0 && metadata.nlink() == 1 && metadata.mode() & 0o077 == 0,
            "unsafe issuer lock"
        );
        lock.try_lock()?;
        let path = directory.join("frontier.json");
        let current = if path.try_exists()? {
            serde_json::from_slice(&read_protected(&path, 1024, true)?)?
        } else {
            anyhow::ensure!(
                state_is_empty,
                "missing external frontier for existing issuer state"
            );
            write_atomic(&path, &serde_json::to_vec(&initial)?)?;
            initial
        };
        Ok(Self {
            path,
            current: Mutex::new(current),
            _lock: lock,
        })
    }
}

impl AuthorityFrontierStore<FinalUseFrontier> for ProtectedFrontier {
    fn load(&self, _owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        serde_json::from_slice(
            &read_protected(&self.path, 1024, true)
                .map_err(|_| AuthorityTrustError::Unavailable)?,
        )
        .map_err(|_| AuthorityTrustError::Invalid)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        let mut current = self
            .current
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if *current != *expected || self.load(owner_id)? != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        let bytes = serde_json::to_vec(next).map_err(|_| AuthorityTrustError::Invalid)?;
        write_atomic(&self.path, &bytes).map_err(|_| AuthorityTrustError::Unavailable)?;
        *current = *next;
        Ok(())
    }
}
