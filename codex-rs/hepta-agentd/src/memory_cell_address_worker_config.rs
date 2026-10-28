//! Fixed host configuration and complete first-party import pins.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use tokio::io::AsyncReadExt;

use super::wire::canonical;
use super::wire::hash;

/// Every path, code pin, alias and timeout is selected by the embedding host.
/// Request JSON cannot alter executable arguments, model files or this registry.
pub struct MemoryCellAddressWorkerConfigV1 {
    pub python: PathBuf,
    pub worker_script: PathBuf,
    pub worker_script_digest: ContractDigestV1,
    /// Exact first-party file hashes, including the script, all `addressing/*.py`,
    /// and the fixed `v6/__init__.py` plus `v6/encoder.py` import closure.
    pub code_pins: BTreeMap<PathBuf, ContractDigestV1>,
    pub model_directory: PathBuf,
    pub model_digest: ContractDigestV1,
    pub encoder_directory: PathBuf,
    pub aliases: BTreeMap<ContractIdV1, Vec<String>>,
    /// At most 1.5 seconds, leaving the control transport time for owner checks.
    pub request_timeout: Duration,
    /// An explicit prewarm bound; startup must finish before attaching Agentd.
    pub startup_timeout: Duration,
}

impl MemoryCellAddressWorkerConfigV1 {
    pub(super) async fn verify(&self) -> Result<ContractDigestV1, String> {
        if self.request_timeout.is_zero()
            || self.request_timeout > Duration::from_millis(1_500)
            || self.startup_timeout.is_zero()
            || self.startup_timeout > Duration::from_secs(30)
            || !self.python.is_absolute()
            || !self.python.is_file()
            || self.code_pins.is_empty()
            || self.code_pins.len() > 128
            || self.aliases.len() > 4_096
        {
            return Err("invalid fixed address worker configuration".to_string());
        }
        for aliases in self.aliases.values() {
            if aliases.len() > 32
                || aliases.iter().any(|alias| {
                    alias.is_empty() || alias.len() > 128 || alias.chars().any(|ch| ch < ' ')
                })
            {
                return Err("invalid host-configured address alias".to_string());
            }
        }
        require_plain_path(&self.worker_script)?;
        require_plain_path(&self.model_directory)?;
        require_plain_path(&self.encoder_directory)?;
        if !self.model_directory.is_dir()
            || !self.encoder_directory.is_dir()
            || self.code_pins.get(&self.worker_script) != Some(&self.worker_script_digest)
        {
            return Err("address script, model or encoder path lacks its host binding".to_string());
        }
        let addressing = self
            .worker_script
            .parent()
            .ok_or("address worker parent is missing")?;
        let qualification = addressing
            .parent()
            .and_then(Path::parent)
            .ok_or("address worker import root is missing")?;
        let mut required: BTreeSet<_> = [
            "__init__.py",
            "contracts.py",
            "planner.py",
            "model.py",
            "capabilities.py",
        ]
        .into_iter()
        .map(|name| addressing.join(name))
        .collect();
        required.insert(self.worker_script.clone());
        required.insert(qualification.join("memory-cell-v6/v6/__init__.py"));
        required.insert(qualification.join("memory-cell-v6/v6/encoder.py"));
        // New first-party modules cannot silently appear outside the configured
        // manifest. Existing imports are exactly the fixed closure above.
        let mut entries = tokio::fs::read_dir(addressing)
            .await
            .map_err(|_| "cannot inventory address code pins")?;
        let mut count = 0;
        while let Some(entry) = entries
            .next_entry()
            .await
            .map_err(|_| "cannot inventory address code pins")?
        {
            count += 1;
            if count > 256 {
                return Err("address code directory exceeds its bound".to_string());
            }
            if entry
                .path()
                .extension()
                .is_some_and(|extension| extension == "py")
            {
                required.insert(entry.path());
            }
        }
        if required
            .iter()
            .any(|path| !self.code_pins.contains_key(path))
        {
            return Err("address worker is missing a required first-party import pin".to_string());
        }
        for (path, digest) in &self.code_pins {
            read_pinned(path, *digest, /*limit*/ 1_048_576).await?;
        }
        let policy_files: BTreeMap<_, _> =
            ["model.py", "capabilities.py", "contracts.py", "planner.py"]
                .into_iter()
                .map(|name| (name, self.code_pins[&addressing.join(name)].to_string()))
                .collect();
        let policy = hash(&canonical(
            &serde_json::to_value(policy_files).map_err(|_| "policy pin encoding failed")?,
        )?);
        let manifest = read_pinned(
            &self.model_directory.join("manifest.json"),
            self.model_digest,
            /*limit*/ 8_000_000,
        )
        .await?;
        let manifest: serde_json::Value = serde_json::from_slice(&manifest)
            .map_err(|_| "address model manifest JSON is invalid")?;
        if manifest["schema"] != "hepta.memory.v7.intent-model.v1"
            || manifest["policy_digest"] != policy.to_string()
        {
            return Err("address model policy differs from the pinned import closure".to_string());
        }
        Ok(policy)
    }
}

async fn read_pinned(path: &Path, digest: ContractDigestV1, limit: u64) -> Result<Vec<u8>, String> {
    require_plain_path(path)?;
    let file = tokio::fs::File::open(path)
        .await
        .map_err(|_| "cannot open pinned address artifact")?;
    if !file
        .metadata()
        .await
        .map_err(|_| "cannot inspect pinned address artifact")?
        .is_file()
    {
        return Err("pinned address artifact is not a regular file".to_string());
    }
    let mut bytes = Vec::new();
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .await
        .map_err(|_| "cannot read pinned address artifact")?;
    if bytes.len() as u64 > limit || hash(&bytes) != digest {
        return Err("pinned address artifact bytes changed".to_string());
    }
    Ok(bytes)
}

fn require_plain_path(path: &Path) -> Result<(), String> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, std::path::Component::ParentDir))
    {
        return Err("address artifact paths must be absolute without traversal".to_string());
    }
    for ancestor in path.ancestors() {
        if std::fs::symlink_metadata(ancestor)
            .map_err(|_| "address artifact path is unavailable")?
            .file_type()
            .is_symlink()
        {
            return Err("symlinked address artifacts are not allowed".to_string());
        }
    }
    Ok(())
}
