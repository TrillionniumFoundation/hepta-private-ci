use std::collections::BTreeSet;
use std::fs;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::thread::JoinHandle;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use serde::Deserialize;

const REVOCATION_FEED_SCHEMA: &str = "hepta.browser.revocation-feed.v1";
const REVOCATION_FEED_VERSION: u64 = 1;
const MAX_REVOCATION_FEED_BYTES: u64 = 1_048_576;
const MAX_REVOKED_GRANTS: usize = 65_536;
const POLL_INTERVAL: Duration = Duration::from_millis(20);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct BrowserRevocationHead {
    schema: String,
    version: u64,
    authority_epoch: u64,
    revision: u64,
    revoked_grant_ids: BTreeSet<String>,
}

impl BrowserRevocationHead {
    fn into_final_use(self) -> Result<FinalUseRevocations, String> {
        if self.schema != REVOCATION_FEED_SCHEMA || self.version != REVOCATION_FEED_VERSION {
            return Err("Browser revocation feed schema/version is unsupported".into());
        }
        if self.authority_epoch == 0 || self.revision == 0 {
            return Err("Browser revocation feed epoch/revision must be non-zero".into());
        }
        if self.revoked_grant_ids.len() > MAX_REVOKED_GRANTS {
            return Err("Browser revocation feed exceeds revoked-grant capacity".into());
        }
        Ok(FinalUseRevocations {
            authority_epoch: self.authority_epoch,
            revision: self.revision,
            revoked_grant_ids: self.revoked_grant_ids,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct AppliedHead {
    authority_epoch: u64,
    revision: u64,
    revoked_grant_ids: BTreeSet<String>,
}

impl From<&FinalUseRevocations> for AppliedHead {
    fn from(value: &FinalUseRevocations) -> Self {
        Self {
            authority_epoch: value.authority_epoch,
            revision: value.revision,
            revoked_grant_ids: value.revoked_grant_ids.clone(),
        }
    }
}

#[derive(Debug)]
struct SharedState {
    applied: Mutex<AppliedHead>,
    last_error: Mutex<Option<String>>,
    refresh_lock: Mutex<()>,
}

pub(crate) struct BrowserRevocationFeed {
    authority: FinalUseAuthority,
    path: PathBuf,
    shared: Arc<SharedState>,
    stop: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
}

impl BrowserRevocationFeed {
    pub(crate) fn start(
        authority: FinalUseAuthority,
        path: PathBuf,
        bootstrap: FinalUseRevocations,
    ) -> Result<Self, String> {
        if !path.is_absolute() {
            return Err("Browser revocation feed path must be absolute".into());
        }
        let shared = Arc::new(SharedState {
            applied: Mutex::new(AppliedHead::from(&bootstrap)),
            last_error: Mutex::new(None),
            refresh_lock: Mutex::new(()),
        });
        let stop = Arc::new(AtomicBool::new(false));
        refresh_once(&authority, &path, &shared)?;

        let worker_authority = authority.clone();
        let worker_path = path.clone();
        let worker_shared = Arc::clone(&shared);
        let worker_stop = Arc::clone(&stop);
        let worker = thread::Builder::new()
            .name("hepta-browser-revocation-feed".to_string())
            .spawn(move || {
                while !worker_stop.load(Ordering::Acquire) {
                    if let Err(error) =
                        refresh_once(&worker_authority, &worker_path, &worker_shared)
                    {
                        if let Ok(mut slot) = worker_shared.last_error.lock() {
                            *slot = Some(error);
                        }
                    }
                    thread::sleep(POLL_INTERVAL);
                }
            })
            .map_err(|error| format!("cannot start Browser revocation feed: {error}"))?;

        Ok(Self {
            authority,
            path,
            shared,
            stop,
            worker: Some(worker),
        })
    }

    pub(crate) fn refresh_now(&self) -> Result<(), String> {
        refresh_once(&self.authority, &self.path, &self.shared)
    }

    #[cfg(test)]
    pub(crate) fn applied_revision(&self) -> Result<u64, String> {
        self.shared
            .applied
            .lock()
            .map(|head| head.revision)
            .map_err(|_| "Browser revocation feed state is poisoned".to_string())
    }
}

impl Drop for BrowserRevocationFeed {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

fn refresh_once(
    authority: &FinalUseAuthority,
    path: &Path,
    shared: &SharedState,
) -> Result<(), String> {
    let _serial = shared
        .refresh_lock
        .lock()
        .map_err(|_| "Browser revocation feed refresh lock is poisoned".to_string())?;
    let next = read_feed(path)?.into_final_use()?;
    {
        let applied = shared
            .applied
            .lock()
            .map_err(|_| "Browser revocation feed state is poisoned".to_string())?;
        if next.authority_epoch == applied.authority_epoch
            && next.revision == applied.revision
            && next.revoked_grant_ids == applied.revoked_grant_ids
        {
            if let Ok(mut slot) = shared.last_error.lock() {
                *slot = None;
            }
            return Ok(());
        }
    }

    authority
        .update_revocations(next.clone())
        .map_err(|error| format!("Browser revocation feed rejected head: {error}"))?;
    *shared
        .applied
        .lock()
        .map_err(|_| "Browser revocation feed state is poisoned".to_string())? =
        AppliedHead::from(&next);
    if let Ok(mut slot) = shared.last_error.lock() {
        *slot = None;
    }
    Ok(())
}

fn read_feed(path: &Path) -> Result<BrowserRevocationHead, String> {
    let parent = path
        .parent()
        .ok_or_else(|| "Browser revocation feed has no parent directory".to_string())?;
    let parent_metadata = fs::symlink_metadata(parent)
        .map_err(|error| format!("cannot inspect Browser revocation feed parent: {error}"))?;
    if !parent_metadata.is_dir() || parent_metadata.file_type().is_symlink() {
        return Err("Browser revocation feed parent must be a non-symlink directory".into());
    }
    #[cfg(unix)]
    let expected_uid = {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};
        if parent_metadata.permissions().mode() & 0o077 != 0 {
            return Err("Browser revocation feed parent permissions are too broad".into());
        }
        parent_metadata.uid()
    };
    let canonical_parent = fs::canonicalize(parent)
        .map_err(|error| format!("cannot canonicalize Browser revocation feed parent: {error}"))?;
    if canonical_parent != parent {
        return Err("Browser revocation feed parent path is not canonical".into());
    }

    let before = fs::symlink_metadata(path)
        .map_err(|error| format!("cannot inspect Browser revocation feed: {error}"))?;
    if !before.is_file()
        || before.file_type().is_symlink()
        || before.len() == 0
        || before.len() > MAX_REVOCATION_FEED_BYTES
    {
        return Err("Browser revocation feed must be a bounded regular non-symlink file".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};
        if before.permissions().mode() & 0o077 != 0 {
            return Err("Browser revocation feed permissions are too broad".into());
        }
        if before.uid() != expected_uid || before.nlink() != 1 {
            return Err(
                "Browser revocation feed must share its private parent owner and have one hard link"
                    .into(),
            );
        }
    }

    let mut file = File::open(path)
        .map_err(|error| format!("cannot open Browser revocation feed: {error}"))?;
    let opened = file
        .metadata()
        .map_err(|error| format!("cannot stat Browser revocation feed: {error}"))?;
    let after = fs::symlink_metadata(path)
        .map_err(|error| format!("cannot re-inspect Browser revocation feed: {error}"))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if opened.dev() != after.dev() || opened.ino() != after.ino() {
            return Err("Browser revocation feed changed during secure open".into());
        }
        if opened.uid() != expected_uid
            || after.uid() != expected_uid
            || opened.nlink() != 1
            || after.nlink() != 1
        {
            return Err("Browser revocation feed ownership/link count changed during open".into());
        }
    }
    if !after.is_file() || after.file_type().is_symlink() {
        return Err("Browser revocation feed changed to an unsafe file".into());
    }

    let mut bytes = Vec::with_capacity(usize::try_from(opened.len()).unwrap_or(0));
    file.read_to_end(&mut bytes)
        .map_err(|error| format!("cannot read Browser revocation feed: {error}"))?;
    if bytes.is_empty() || bytes.len() as u64 > MAX_REVOCATION_FEED_BYTES {
        return Err("Browser revocation feed byte size is outside the hard bound".into());
    }
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("Browser revocation feed is invalid JSON: {error}"))
}
