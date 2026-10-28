use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use serde::Serialize;
use serde::de::DeserializeOwned;

use super::super::MAX_HEADER_BYTES;
use super::super::MAX_IMAGE_BYTES;
use super::super::failure;

pub(super) fn private_directory(path: &Path) -> Result<(), String> {
    if path.exists() {
        let metadata = path.symlink_metadata().map_err(failure)?;
        if !metadata.is_dir() || metadata.permissions().mode() & 0o077 != 0 {
            return Err("migration requires private nonredirected directories".into());
        }
    } else {
        let parent = path.parent().ok_or("migration root requires parent")?;
        if !parent.exists() { private_directory(parent)?; }
        std::fs::create_dir(path).map_err(failure)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).map_err(failure)?;
        File::open(parent).and_then(|file| file.sync_all()).map_err(failure)?;
    }
    if std::fs::canonicalize(path).map_err(failure)? != path { return Err("migration requires canonical nonredirected paths".into()); }
    Ok(())
}

pub(super) fn regular_or_absent(path: &Path) -> Result<(), String> {
    match path.symlink_metadata() {
        Ok(metadata) if metadata.is_file() => Ok(()),
        Ok(_) => Err("migration file redirection or nonregular file".into()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(failure(error)),
    }
}

pub(super) fn read_bounded(path: &Path, maximum: usize) -> Result<Vec<u8>, String> {
    regular_or_absent(path)?;
    let mut raw = Vec::new();
    File::open(path).map_err(failure)?.take((maximum + 1) as u64).read_to_end(&mut raw).map_err(failure)?;
    if raw.len() > maximum { return Err("migration file bound exceeded".into()); }
    Ok(raw)
}

pub(super) fn read_json<T: DeserializeOwned>(path: &Path) -> Result<T, String> {
    serde_json::from_slice(&read_bounded(path, MAX_HEADER_BYTES * 2)?).map_err(failure)
}

pub(super) fn save_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    atomic_file(path, &serde_json::to_vec(value).map_err(failure)?, /*mode*/ 0o600)
}

pub(super) fn immutable_file(path: &Path, raw: &[u8], mode: u32) -> Result<(), String> {
    if path.exists() {
        if read_bounded(path, MAX_IMAGE_BYTES)? != raw || std::fs::metadata(path).map_err(failure)?.permissions().mode() & 0o777 != mode {
            return Err("migration immutable destination conflict".into());
        }
        return Ok(());
    }
    atomic_file(path, raw, mode)
}

fn atomic_file(path: &Path, raw: &[u8], mode: u32) -> Result<(), String> {
    regular_or_absent(path)?;
    let temporary = path.with_file_name(format!("{}.hepta-v9-tmp", path.file_name().ok_or("migration filename")?.to_string_lossy()));
    regular_or_absent(&temporary)?;
    if temporary.exists() { std::fs::remove_file(&temporary).map_err(failure)?; }
    let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(&temporary).map_err(failure)?;
    file.write_all(raw).map_err(failure)?;
    file.set_permissions(std::fs::Permissions::from_mode(mode)).map_err(failure)?;
    file.sync_all().map_err(failure)?;
    std::fs::rename(&temporary, path).map_err(failure)?;
    File::open(path.parent().ok_or("migration parent")?).and_then(|file| file.sync_all()).map_err(failure)
}
