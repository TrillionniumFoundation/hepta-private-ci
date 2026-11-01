//! Bounded files and acknowledged atomic snapshots. An incomplete write is retained.
use codex_hepta_types::Digest32;
use serde::Serialize;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

pub fn digest(bytes: &[u8]) -> String {
    Digest32::of_bytes(bytes).to_string()
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

pub fn save<T: Serialize>(path: &Path, value: &T) -> Result<(String, u64), String> {
    let bytes = serde_json::to_vec(value).map_err(|e| e.to_string())?;
    if bytes.len() > 2_000_000 {
        return Err("snapshot byte envelope".into());
    }
    let pending = sibling(path, ".pending");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(&pending)
        .map_err(|e| e.to_string())?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|e| e.to_string())?;
    std::fs::rename(&pending, path).map_err(|e| e.to_string())?;
    File::open(path.parent().ok_or("snapshot parent required")?)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())?;
    Ok((digest(&bytes), bytes.len() as u64))
}

pub fn relative_packet(folder: &Path, name: &str) -> Result<PathBuf, String> {
    use std::path::Component;
    let relative = Path::new(name);
    if name.is_empty()
        || name.len() > 4096
        || relative.components().count() != 1
        || relative
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
    {
        return Err("packet path must be a single normal basename".into());
    }
    // Resolve no packet here: existence and contents are deliberately checked only at due time.
    Ok(folder.join(relative))
}
