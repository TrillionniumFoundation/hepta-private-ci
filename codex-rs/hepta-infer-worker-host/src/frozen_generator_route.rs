//! Root-published public routing facts. No role key or signing policy is loaded.
use crate::final_use_authorizer::IssuerProcessIdentityConfig;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Route {
    pub schema_version: u32,
    pub socket: PathBuf,
    pub process_attestation: PathBuf,
    pub process_identity: IssuerProcessIdentityConfig,
    pub maximum_request_duration_ms: u64,
}

impl Route {
    pub(super) fn read(path: &Path, expected: Digest32) -> Result<Self> {
        let bytes = read_root_public_file(path)?;
        if expected.is_zero() || Digest32::of_bytes(&bytes) != expected {
            return Err("frozen Generator public route Source pin mismatch".into());
        }
        let route: Self = serde_json::from_slice(&bytes)?;
        if route.schema_version != 1
            || !(1..=30_000).contains(&route.maximum_request_duration_ms)
            || !route.socket.is_absolute()
            || !route.process_attestation.is_absolute()
        {
            return Err("frozen Generator public route schema or bounds".into());
        }
        root_directory(
            route
                .socket
                .parent()
                .ok_or("Generator socket parent absent")?,
        )?;
        Ok(route)
    }
}

fn root_directory(path: &Path) -> Result<()> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::CurDir | Component::ParentDir))
    {
        return Err("frozen Generator routing path must be canonical and absolute".into());
    }
    for ancestor in path.ancestors() {
        let meta = std::fs::symlink_metadata(ancestor)?;
        if !meta.is_dir() || meta.uid() != 0 || meta.mode() & 0o022 != 0 {
            return Err("frozen Generator routing directory must be Root protected".into());
        }
    }
    Ok(())
}

fn read_root_public_file(path: &Path) -> Result<Vec<u8>> {
    root_directory(path.parent().ok_or("Generator route parent absent")?)?;
    if !path.is_absolute() {
        return Err("frozen Generator route must be absolute".into());
    }
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.uid() != 0 || meta.nlink() != 1 || meta.mode() & 0o022 != 0 {
        return Err("frozen Generator route must be a Root-protected regular file".into());
    }
    let mut bytes = Vec::new();
    file.by_ref().take(8193).read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() > 8192 {
        return Err("frozen Generator route file bounds".into());
    }
    Ok(bytes)
}
