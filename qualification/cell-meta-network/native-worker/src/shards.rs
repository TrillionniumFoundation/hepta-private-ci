//! Read-only source snapshot work, registered by the trusted experiment launcher.
//! Requests select a manifest digest, never an arbitrary filesystem path.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;
use std::io::Read;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

const MANIFEST_CAP: u64 = 2 * 1024 * 1024;
const FILE_CAP: u64 = 4 * 1024 * 1024;
const SHARD_CAP: u64 = 64 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    shards: Vec<Binding>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Binding {
    manifest: PathBuf,
    root: PathBuf,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema: String,
    source_commit: Option<String>,
    #[serde(default)]
    source_tree_sha256: Option<String>,
    files: Vec<FileSpec>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FileSpec {
    path: String,
    bytes: u64,
    sha256: String,
}
struct Shard {
    root: PathBuf,
    manifest: Manifest,
}

#[derive(Default)]
pub(crate) struct ShardStore {
    shards: BTreeMap<String, Shard>,
}

impl ShardStore {
    pub fn load(path: &Path) -> Result<Self, String> {
        let config: Config = serde_json::from_slice(&bounded_read(path, MANIFEST_CAP)?)
            .map_err(|error| error.to_string())?;
        if config.schema != "hepta.source-shard-deployment.v1"
            || config.shards.is_empty()
            || config.shards.len() > 8
        {
            return Err("shard deployment shape".to_string());
        }
        let mut result = Self::default();
        for binding in config.shards {
            let raw = bounded_read(&binding.manifest, MANIFEST_CAP)?;
            let manifest: Manifest =
                serde_json::from_slice(&raw).map_err(|error| error.to_string())?;
            if !matches!(
                manifest.schema.as_str(),
                "hepta.source-shard-manifest.v1" | "hepta.source-shard-manifest.v2"
            ) || manifest.files.is_empty()
                || manifest.files.len() > 4096
            {
                return Err("shard manifest profile".to_string());
            }
            match (&manifest.source_commit, &manifest.source_tree_sha256) {
                (Some(commit), None)
                    if commit.len() == 40
                        && commit.bytes().all(|byte| byte.is_ascii_hexdigit()) => {}
                (None, Some(tree))
                    if manifest.schema == "hepta.source-shard-manifest.v2"
                        && *tree == tree_digest(&manifest.files)?.to_string() => {}
                _ => {
                    return Err(
                        "exactly one valid source commit or source-tree identity required"
                            .to_string(),
                    );
                }
            }
            let mut paths = BTreeSet::new();
            let mut contents = BTreeSet::new();
            let mut total = 0_u64;
            for file in &manifest.files {
                if !relative_file(&file.path)
                    || !paths.insert(file.path.clone())
                    || !contents.insert(file.sha256.clone())
                    || file.bytes > FILE_CAP
                {
                    return Err("shard path, duplicate or file bound".to_string());
                }
                file.sha256
                    .parse::<Digest32>()
                    .map_err(|error| error.to_string())?;
                total = total.checked_add(file.bytes).ok_or("shard byte overflow")?;
            }
            if total > SHARD_CAP {
                return Err("shard total byte bound".to_string());
            }
            let root = fs::canonicalize(&binding.root).map_err(|error| error.to_string())?;
            if !root.is_dir() {
                return Err("shard root must be a directory".to_string());
            }
            let identity = Digest32::of_bytes(&raw).to_string();
            if result
                .shards
                .insert(identity, Shard { root, manifest })
                .is_some()
            {
                return Err("duplicate shard identity".to_string());
            }
        }
        Ok(result)
    }

    pub fn identities(&self) -> Vec<&str> {
        self.shards.keys().map(String::as_str).collect()
    }

    pub fn audit(&self, identity: &str) -> Result<Value, String> {
        let shard = self.shards.get(identity).ok_or("unregistered shard")?;
        let mut bytes = 0_u64;
        let mut lines = 0_u64;
        let mut aggregate = Vec::new();
        for spec in &shard.manifest.files {
            let joined = shard.root.join(&spec.path);
            let path = fs::canonicalize(&joined).map_err(|error| error.to_string())?;
            if !path.starts_with(&shard.root)
                || fs::symlink_metadata(&joined)
                    .map_err(|error| error.to_string())?
                    .file_type()
                    .is_symlink()
            {
                return Err("source path escapes root or is a symlink".to_string());
            }
            let raw = bounded_read(&path, spec.bytes)?;
            let actual = Digest32::of_bytes(&raw);
            if raw.len() as u64 != spec.bytes || actual.to_string() != spec.sha256 {
                return Err("source changed from the registered snapshot".to_string());
            }
            let file_lines = raw.iter().filter(|byte| **byte == b'\n').count() as u64;
            bytes += spec.bytes;
            lines += file_lines;
            aggregate.extend_from_slice(spec.path.as_bytes());
            aggregate.push(0);
            aggregate.extend_from_slice(actual.as_array());
            aggregate.extend_from_slice(&spec.bytes.to_le_bytes());
            aggregate.extend_from_slice(&file_lines.to_le_bytes());
        }
        Ok(
            json!({"manifest_sha256":identity, "source_commit":shard.manifest.source_commit,
                  "source_tree_sha256":shard.manifest.source_tree_sha256,
                  "files":shard.manifest.files.len(), "bytes":bytes, "newline_count":lines,
                  "verified_content_sha256":Digest32::of_bytes(&aggregate).to_string()}),
        )
    }
}

fn tree_digest(files: &[FileSpec]) -> Result<Digest32, String> {
    let mut encoded = b"hepta.source-tree-content.v1\0".to_vec();
    for file in files {
        encoded.extend_from_slice(&(file.path.len() as u64).to_le_bytes());
        encoded.extend_from_slice(file.path.as_bytes());
        encoded.extend_from_slice(&file.bytes.to_le_bytes());
        encoded.extend_from_slice(
            file.sha256
                .parse::<Digest32>()
                .map_err(|error| error.to_string())?
                .as_array(),
        );
    }
    Ok(Digest32::of_bytes(&encoded))
}

fn relative_file(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 1024
        && !value.contains('\\')
        && !value.chars().any(char::is_control)
        && value.split('/').all(|part| !part.is_empty())
        && Path::new(value)
            .components()
            .all(|part| matches!(part, Component::Normal(_)))
}

fn bounded_read(path: &Path, cap: u64) -> Result<Vec<u8>, String> {
    let file = fs::File::open(path).map_err(|error| error.to_string())?;
    let metadata = file.metadata().map_err(|error| error.to_string())?;
    if !metadata.is_file() || metadata.len() > cap {
        return Err("bounded regular file required".to_string());
    }
    let mut raw = Vec::new();
    file.take(cap + 1)
        .read_to_end(&mut raw)
        .map_err(|error| error.to_string())?;
    if raw.len() as u64 > cap {
        return Err("file grew beyond bound".to_string());
    }
    Ok(raw)
}

#[cfg(test)]
#[path = "shard_tests.rs"]
mod tests;
