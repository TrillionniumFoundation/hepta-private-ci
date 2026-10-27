use std::collections::BTreeMap;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use serde::Deserialize;
use serde_json::Value;

use crate::validate_file_sha256;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct BoundFile {
    pub path: PathBuf,
    pub bytes: u64,
    pub sha256: String,
}

impl BoundFile {
    pub fn verify(&self, label: &str) -> Result<()> {
        ensure!(self.path.is_absolute(), "{label} must be absolute");
        ensure!(
            self.path.canonicalize()? == self.path,
            "{label} contains a symlink"
        );
        ensure!(self.path.is_file(), "{label} must be a regular file");
        ensure!(
            std::fs::metadata(&self.path)?.len() == self.bytes,
            "{label} byte count changed"
        );
        validate_file_sha256(&self.path, &self.sha256, label)
    }

    pub fn json(&self, label: &str) -> Result<Value> {
        self.verify(label)?;
        serde_json::from_slice(&std::fs::read(&self.path)?).with_context(|| label.to_owned())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Manifest {
    pub schema_version: u32,
    pub qualification_kind: String,
    pub scope: String,
    pub source_root: PathBuf,
    pub candidate_sha: String,
    pub candidate_tree_sha: String,
    pub source_seal: BoundFile,
    pub builder_seal: BoundFile,
    pub build_result: BoundFile,
    pub build_inputs: BoundFile,
    pub controller_snapshot: BoundFile,
    pub proxy_source: BoundFile,
    pub proxy_ready: BoundFile,
    pub binaries: BTreeMap<String, BoundFile>,
    pub fixture_root: PathBuf,
    pub credentials_directory: PathBuf,
    pub runtime_tmp_root: PathBuf,
    pub process_identity_ledger: PathBuf,
    pub homeserver: String,
}
