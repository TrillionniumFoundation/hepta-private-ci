use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use crate::AcceptanceError;
use crate::durable::MAX_SMALL_FILE_BYTES;
use crate::durable::canonical_json;
use crate::durable::secure_hash;
use crate::durable::secure_read;
use crate::durable::secure_root;
use crate::durable::sha256;
use crate::durable::verify_secure_directory;

#[derive(Clone, Debug)]
pub(crate) struct ManifestEntry {
    pub sha256: String,
    pub size_bytes: u64,
}

pub(crate) struct VerifiedManifest {
    entries: BTreeMap<String, ManifestEntry>,
    pub root: PathBuf,
}

impl VerifiedManifest {
    pub(crate) fn load(
        root: &Path,
        expected_sha256: &str,
        expected_entries: usize,
    ) -> Result<Self, AcceptanceError> {
        let root = secure_root(root, "evidence root")?;
        let sums_path = root.join("SHA256SUMS");
        let sums = secure_read(&sums_path, MAX_SMALL_FILE_BYTES)?;
        if sha256(&sums) != expected_sha256 {
            return Err(invalid("SHA256SUMS differs from its frozen digest"));
        }
        let parsed = parse_manifest(&sums)?;
        if parsed.len() != expected_entries {
            return Err(invalid("SHA256SUMS entry count differs from its pin"));
        }
        let actual = inventory(&root)?;
        let expected = parsed.keys().cloned().collect::<BTreeSet<_>>();
        let mut actual_paths = actual.files.keys().cloned().collect::<BTreeSet<_>>();
        actual_paths.remove("SHA256SUMS");
        if actual_paths != expected {
            return Err(invalid(
                "evidence inventory differs from the exact SHA256SUMS paths",
            ));
        }
        let mut entries = BTreeMap::new();
        for (relative, expected_sha256) in parsed {
            let (actual_sha256, size_bytes) = secure_hash(&root.join(&relative))?;
            if actual_sha256 != expected_sha256 {
                return Err(invalid(format!(
                    "evidence artifact hash differs for {relative}"
                )));
            }
            entries.insert(
                relative,
                ManifestEntry {
                    sha256: actual_sha256,
                    size_bytes,
                },
            );
        }
        let actual_after = inventory(&root)?;
        if actual_after != actual {
            return Err(invalid(
                "evidence paths or metadata changed during full artifact verification",
            ));
        }
        if sha256(&secure_read(&sums_path, MAX_SMALL_FILE_BYTES)?) != expected_sha256 {
            return Err(invalid("SHA256SUMS changed during evidence verification"));
        }
        Ok(Self { entries, root })
    }

    pub(crate) fn bytes(&self, relative: &str) -> Result<Vec<u8>, AcceptanceError> {
        let entry = self
            .entries
            .get(relative)
            .ok_or_else(|| invalid(format!("required manifest entry is absent: {relative}")))?;
        let bytes = secure_read(&self.root.join(relative), MAX_SMALL_FILE_BYTES)?;
        if sha256(&bytes) != entry.sha256 {
            return Err(invalid(format!(
                "required artifact changed after manifest verification: {relative}"
            )));
        }
        Ok(bytes)
    }

    pub(crate) fn json_pinned<T: for<'de> Deserialize<'de>>(
        &self,
        relative: &str,
    ) -> Result<T, AcceptanceError> {
        let bytes = self.bytes(relative)?;
        serde_json::from_slice(&bytes)
            .map_err(|error| invalid(format!("invalid {relative}: {error}")))
    }

    pub(crate) fn json_canonical<T: for<'de> Deserialize<'de> + Serialize>(
        &self,
        relative: &str,
    ) -> Result<T, AcceptanceError> {
        let bytes = self.bytes(relative)?;
        let value = self.json_pinned(relative)?;
        if canonical_json(&value)? != bytes {
            return Err(invalid(format!("{relative} is not canonical JSON")));
        }
        Ok(value)
    }

    pub(crate) fn entry(&self, relative: &str) -> Option<&ManifestEntry> {
        self.entries.get(relative)
    }

    pub(crate) fn require_hash(
        &self,
        relative: &str,
        expected: &str,
    ) -> Result<(), AcceptanceError> {
        if self.entry(relative).map(|entry| entry.sha256.as_str()) != Some(expected) {
            return Err(invalid(format!(
                "manifest binding differs for required artifact: {relative}"
            )));
        }
        Ok(())
    }
}

fn parse_manifest(bytes: &[u8]) -> Result<BTreeMap<String, String>, AcceptanceError> {
    let text = std::str::from_utf8(bytes).map_err(|_| invalid("SHA256SUMS is not UTF-8"))?;
    let mut entries = BTreeMap::new();
    let mut previous: Option<String> = None;
    for line in text.lines() {
        if line.len() < 67 || line.as_bytes().get(64..66) != Some(b"  ") {
            return Err(invalid("SHA256SUMS contains a malformed line"));
        }
        let digest = &line[..64];
        if !digest_shape(digest) {
            return Err(invalid("SHA256SUMS contains an invalid digest"));
        }
        let raw = line[66..].strip_prefix("./").unwrap_or(&line[66..]);
        validate_relative_path(raw)?;
        if previous.as_deref().is_some_and(|value| value >= raw) {
            return Err(invalid(
                "SHA256SUMS paths must be unique and strictly sorted",
            ));
        }
        previous = Some(raw.to_string());
        if entries
            .insert(raw.to_string(), digest.to_string())
            .is_some()
        {
            return Err(invalid("SHA256SUMS contains a duplicate path"));
        }
    }
    if entries.is_empty() || !text.ends_with('\n') {
        return Err(invalid(
            "SHA256SUMS must be nonempty and newline terminated",
        ));
    }
    Ok(entries)
}

#[derive(Debug, Eq, PartialEq)]
struct Inventory {
    directories: BTreeMap<String, String>,
    files: BTreeMap<String, String>,
}

fn inventory(root: &Path) -> Result<Inventory, AcceptanceError> {
    let mut directories = BTreeMap::new();
    let mut files = BTreeMap::new();
    let mut pending = vec![(root.to_path_buf(), 0_u8)];
    while let Some((directory, depth)) = pending.pop() {
        if depth > 32 {
            return Err(invalid("evidence directory depth exceeds 32"));
        }
        verify_secure_directory(&directory, "evidence directory")?;
        let directory_relative = directory
            .strip_prefix(root)
            .map_err(|_| invalid("evidence directory escaped its root"))?
            .to_str()
            .ok_or_else(|| invalid("evidence directory path is not UTF-8"))?;
        directories.insert(
            directory_relative.to_string(),
            metadata_snapshot(&std::fs::symlink_metadata(&directory)?),
        );
        for entry in std::fs::read_dir(&directory)? {
            let entry = entry?;
            let path = entry.path();
            let metadata = std::fs::symlink_metadata(&path)?;
            if metadata.file_type().is_symlink() {
                return Err(invalid("evidence tree contains a symlink"));
            }
            if metadata.is_dir() {
                pending.push((path, depth.saturating_add(1)));
            } else if metadata.is_file() {
                let relative = path
                    .strip_prefix(root)
                    .map_err(|_| invalid("evidence path escaped its root"))?
                    .to_str()
                    .ok_or_else(|| invalid("evidence path is not UTF-8"))?
                    .to_string();
                validate_relative_path(&relative)?;
                files.insert(relative, metadata_snapshot(&metadata));
                if files.len() > 4_097 {
                    return Err(invalid("evidence inventory exceeds 4097 files"));
                }
            } else {
                return Err(invalid("evidence tree contains a special file"));
            }
        }
    }
    Ok(Inventory { directories, files })
}

fn metadata_snapshot(metadata: &std::fs::Metadata) -> String {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        format!(
            "{}:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}",
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
            metadata.mode(),
            metadata.uid(),
            metadata.gid(),
            metadata.nlink(),
        )
    }
    #[cfg(not(unix))]
    {
        format!(
            "{}:{:?}:{}",
            metadata.len(),
            metadata.modified().ok(),
            metadata.permissions().readonly(),
        )
    }
}

fn validate_relative_path(value: &str) -> Result<(), AcceptanceError> {
    if value.is_empty() || value.contains('\\') || value.contains('\0') {
        return Err(invalid("manifest path is empty or uses a forbidden byte"));
    }
    let path = Path::new(value);
    if path.is_absolute()
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(invalid("manifest path is not a safe relative path"));
    }
    Ok(())
}

pub(crate) fn digest_shape(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}

#[cfg(test)]
#[path = "manifest_inventory_tests.rs"]
mod tests;
