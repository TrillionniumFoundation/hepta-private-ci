//! Composite checkpoint publication. Interrupted intents require reconciliation.
use codex_hepta_types::Digest32;
use serde::Serialize;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

pub fn encode(value: &impl Serialize) -> Result<Vec<u8>, String> {
    serde_json::to_vec(value).map_err(|error| error.to_string())
}

pub fn read(path: &Path, limit: u64) -> Result<Vec<u8>, String> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|error| error.to_string())?;
    if !file.metadata().map_err(|error| error.to_string())?.is_file() {
        return Err("checkpoint must be a regular file".into());
    }
    let mut bytes = Vec::new();
    file.take(limit + 1).read_to_end(&mut bytes).map_err(|error| error.to_string())?;
    if bytes.len() as u64 > limit {
        return Err("checkpoint size limit".into());
    }
    Ok(bytes)
}

pub fn create(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|error| error.to_string())?;
    file.write_all(bytes).map_err(|error| error.to_string())?;
    file.sync_all().map_err(|error| error.to_string())?;
    File::open(path.parent().ok_or("checkpoint parent")?)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| error.to_string())
}

pub fn publish(root: &Path, bytes: &[u8]) -> Result<String, String> {
    let pending = root.join("task-checkpoint.pending");
    create(&pending, bytes)?;
    std::fs::rename(&pending, root.join("task-checkpoint.json")).map_err(|error| error.to_string())?;
    File::open(root).and_then(|directory| directory.sync_all()).map_err(|error| error.to_string())?;
    Ok(Digest32::of_bytes(bytes).to_string())
}

pub fn finish_intent(root: &Path) -> Result<(), String> {
    std::fs::remove_file(root.join("task-intent.json")).map_err(|error| error.to_string())?;
    File::open(root).and_then(|directory| directory.sync_all()).map_err(|error| error.to_string())
}
