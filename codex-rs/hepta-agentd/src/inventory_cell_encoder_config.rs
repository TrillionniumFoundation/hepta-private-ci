//! Locally trusted deployment pins for the shared embedding process.

use std::path::{Path, PathBuf};
use std::time::Duration;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use tokio::io::AsyncReadExt;
use crate::INVENTORY_CELL_SEMANTIC_ENCODER_V1;

#[derive(Clone)]
pub struct InventoryCellEncoderWorkerConfigV1 {
    pub python: PathBuf,
    pub worker_script: PathBuf,
    pub worker_digest: Digest32,
    pub encoder_source: PathBuf,
    pub source_digest: Digest32,
    pub encoder_directory: PathBuf,
    pub encoder_digest: ContractDigestV1,
    pub startup_timeout: Duration,
    pub request_timeout: Duration,
}

impl InventoryCellEncoderWorkerConfigV1 {
    /// Parse a bounded startup file supplied by the local operator, not a control
    /// request.  Decoding this file does not spawn or enable the optional worker.
    pub fn from_deployment_json(bytes: &[u8]) -> Result<Self, String> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            python: PathBuf, worker_script: PathBuf, worker_digest: String,
            encoder_source: PathBuf, source_digest: String, encoder_directory: PathBuf,
            encoder_digest: ContractDigestV1, startup_timeout_ms: u64, request_timeout_ms: u64,
        }
        if bytes.is_empty() || bytes.len() > 16384 { return Err("semantic encoder startup configuration bound".to_string()); }
        let wire: Wire = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        Ok(Self { python: wire.python, worker_script: wire.worker_script,
            worker_digest: wire.worker_digest.parse::<Digest32>().map_err(|error| error.to_string())?,
            encoder_source: wire.encoder_source, source_digest: wire.source_digest.parse::<Digest32>().map_err(|error| error.to_string())?,
            encoder_directory: wire.encoder_directory, encoder_digest: wire.encoder_digest,
            startup_timeout: Duration::from_millis(wire.startup_timeout_ms), request_timeout: Duration::from_millis(wire.request_timeout_ms) })
    }

    pub(super) async fn verify(&self) -> Result<(), String> {
        if [&self.python, &self.worker_script, &self.encoder_source, &self.encoder_directory].iter().any(|path| !path.is_absolute())
            || self.encoder_digest.to_string() != INVENTORY_CELL_SEMANTIC_ENCODER_V1
            || self.startup_timeout.is_zero() || self.startup_timeout > Duration::from_secs(120)
            || self.request_timeout.is_zero() || self.request_timeout > Duration::from_secs(10)
        { return Err("encoder process paths, identity or deadlines differ".to_string()); }
        pinned_file(&self.worker_script, self.worker_digest).await?;
        pinned_file(&self.encoder_source, self.source_digest).await?;
        Ok(())
    }
}

async fn pinned_file(path: &Path, expected: Digest32) -> Result<(), String> {
    let file = tokio::fs::File::open(path).await.map_err(|_| "encoder process source unavailable")?;
    let metadata = file.metadata().await.map_err(|_| "encoder process source metadata unavailable")?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > 32768 { return Err("encoder process source size bound".to_string()); }
    let mut bytes = Vec::new();
    file.take(32769).read_to_end(&mut bytes).await.map_err(|_| "encoder process source read failed")?;
    if bytes.len() > 32768 || Digest32::of_bytes(&bytes) != expected { return Err("encoder process source pin differs".to_string()); }
    Ok(())
}
