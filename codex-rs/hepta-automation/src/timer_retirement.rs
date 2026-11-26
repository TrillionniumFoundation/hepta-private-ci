//! One create-only retirement fence outside the replaceable SQLite snapshot.
//! It revokes timer admission only; it is not another writer or execution log.
//! Database restore must retain this current owner fence. Restoring both the
//! database and every external fence requires independent recovery authority.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use codex_hepta_contracts::AgentId;
use sqlx::Row;
use sqlx::SqlitePool;

use crate::AutomationError;
use crate::AutomationStore;

const FILENAME: &str = "timer-retired.v1";
const DOMAIN: &str = "hepta.automation.timer-retirement.v1\n";
const MAX_FENCE_BYTES: u64 = 256;

pub(super) fn read(database: &Path, owner: &AgentId) -> Result<Option<i64>, AutomationError> {
    let path = database
        .parent()
        .ok_or(AutomationError::Corrupt)?
        .join(FILENAME);
    let metadata = match std::fs::symlink_metadata(&path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(AutomationError::Unavailable),
    };
    if !metadata.is_file() || metadata.len() > MAX_FENCE_BYTES {
        return Err(AutomationError::Corrupt);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.nlink() != 1 {
            return Err(AutomationError::Corrupt);
        }
    }
    let mut bytes = Vec::new();
    File::open(&path)
        .map_err(unavailable)?
        .take(MAX_FENCE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    if bytes.len() as u64 > MAX_FENCE_BYTES {
        return Err(AutomationError::Corrupt);
    }
    let text = std::str::from_utf8(&bytes).map_err(|_| AutomationError::Corrupt)?;
    let value = text
        .strip_prefix(DOMAIN)
        .and_then(|text| text.strip_prefix(owner.as_str()))
        .and_then(|text| text.strip_prefix('\n'))
        .and_then(|text| text.strip_suffix('\n'))
        .ok_or(AutomationError::Corrupt)?;
    let epoch = value.parse::<i64>().map_err(|_| AutomationError::Corrupt)?;
    if epoch <= 0 || epoch.to_string() != value {
        return Err(AutomationError::Corrupt);
    }
    Ok(Some(epoch))
}

/// Publish before the SQLite terminal commit, while its writer reservation is
/// held. A crash or uncertain sync can only disable admission, never resurrect
/// the old timer. Existing files are verified, never truncated or replaced.
pub(super) fn persist(database: &Path, owner: &AgentId, epoch: i64) -> Result<(), AutomationError> {
    if epoch <= 0 {
        return Err(AutomationError::Corrupt);
    }
    let parent = database.parent().ok_or(AutomationError::Corrupt)?;
    let path = parent.join(FILENAME);
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    match options.open(&path) {
        Ok(mut file) => {
            let contents = format!("{DOMAIN}{}\n{epoch}\n", owner.as_str());
            file.write_all(contents.as_bytes()).map_err(unavailable)?;
            file.sync_all().map_err(unavailable)?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            if read(database, owner)? != Some(epoch) {
                return Err(AutomationError::Corrupt);
            }
            File::open(&path)
                .map_err(unavailable)?
                .sync_all()
                .map_err(unavailable)?;
        }
        Err(_) => return Err(AutomationError::Unavailable),
    }
    // Match the existing fleet's directory-sync convention. Unix crash tests
    // qualify the fsync path; non-Unix power-loss durability is not inferred.
    #[cfg(unix)]
    File::open(parent)
        .map_err(unavailable)?
        .sync_all()
        .map_err(unavailable)?;
    Ok(())
}

/// Check before migrations: an old active database or missing lifecycle table
/// cannot be upgraded into a current writer in the presence of retirement.
pub(super) async fn verify_open(pool: &SqlitePool, epoch: i64) -> Result<(), AutomationError> {
    let row =
        sqlx::query("SELECT writer_epoch, phase FROM automation_timer_lifecycle WHERE singleton=1")
            .fetch_optional(pool)
            .await
            .map_err(|_| AutomationError::Corrupt)?
            .ok_or(AutomationError::Corrupt)?;
    let actual: i64 = row
        .try_get("writer_epoch")
        .map_err(|_| AutomationError::Corrupt)?;
    let phase: String = row.try_get("phase").map_err(|_| AutomationError::Corrupt)?;
    if actual != epoch || phase != "retired" {
        return Err(AutomationError::Corrupt);
    }
    Ok(())
}

impl AutomationStore {
    /// Called inside the existing SQLite write reservation. The file also
    /// fences already-open handles after an interrupted retirement publication.
    pub(super) fn ensure_timer_not_retired(&self) -> Result<(), AutomationError> {
        if read(self.path(), self.owner_agent_id())?.is_some() {
            return Err(AutomationError::TimerFenced);
        }
        Ok(())
    }
}

fn unavailable(_: std::io::Error) -> AutomationError {
    AutomationError::Unavailable
}
