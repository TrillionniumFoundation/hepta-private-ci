//! Acknowledged task/cell/content frontier. Mid-action crash recovery is refused.
use crate::cell::Family;
use crate::cell::Snapshot;
use crate::content;
use crate::policy::Controller;
use crate::task::State;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Identity {
    pub source_digest: String,
    pub public_sha256: String,
    pub policy_sha256: String,
    pub content_model_sha256: String,
    pub family: Family,
    pub controller: Controller,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Pair {
    pub schema: String,
    pub identity: Identity,
    pub sequence: u64,
    pub native_checkpoint: String,
    pub task: State,
    pub cell: Snapshot,
    pub content: content::State,
}

pub fn read(path: &Path, limit: u64) -> Result<Vec<u8>, String> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|e| e.to_string())?;
    if !file.metadata().map_err(|e| e.to_string())?.is_file() {
        return Err("regular file required".into());
    }
    let mut bytes = Vec::new();
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() as u64 > limit {
        return Err("input byte limit".into());
    }
    Ok(bytes)
}

pub fn digest(bytes: &[u8]) -> String {
    Digest32::of_bytes(bytes).to_string()
}
pub fn encoded(pair: &Pair) -> Result<Vec<u8>, String> {
    serde_json::to_vec(pair).map_err(|e| e.to_string())
}

pub fn sibling(path: &Path, suffix: &str) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(suffix);
    PathBuf::from(name)
}

pub fn private_file(path: &Path) -> Result<File, String> {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|e| e.to_string())?;
    if !file.metadata().map_err(|e| e.to_string())?.is_file() {
        return Err("regular store required".into());
    }
    Ok(file)
}

pub fn save(path: &Path, pair: &Pair) -> Result<(String, u64), String> {
    let bytes = encoded(pair)?;
    let pending = sibling(path, ".pending");
    let mut f = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(&pending)
        .map_err(|e| e.to_string())?;
    f.write_all(&bytes)
        .and_then(|()| f.sync_all())
        .map_err(|e| e.to_string())?;
    std::fs::rename(&pending, path).map_err(|e| e.to_string())?;
    File::open(path.parent().ok_or("snapshot parent")?)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())?;
    Ok((digest(&bytes), bytes.len() as u64))
}
