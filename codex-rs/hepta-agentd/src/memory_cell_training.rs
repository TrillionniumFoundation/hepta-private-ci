//! Real bounded parameter training, separated from artifact activation.
//!
//! The configured process receives an owner-acquired export. Its candidate is
//! accepted only after native decoding and a fresh SQLite cut check. Clean jobs
//! have no parent input; replay jobs retain the selected artifact lineage.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;

use crate::LoadedMemoryCellBundleV1;
use crate::MemoryCellBundleCandidateV1;
use crate::MemoryCellReleaseHostV1;

const MAX_JOB_BYTES: usize = 16 * 1024 * 1024;
const REQUIRED_CODE: &[&str] = &[
    "memory-cell-v7/training.py", "memory-cell-v7/training_worker.py", "memory-cell-v7/native_export.py",
    "memory-cell-v6/v6/__init__.py", "memory-cell-v6/v6/cells.py",
    "memory-cell-v6/v6/values.py", "memory-cell-v6/v6/contracts.py",
];

/// Trusted startup configuration. No path or command comes from a read request.
pub struct MemoryCellTrainerConfigV1 {
    pub python: PathBuf,
    pub qualification_root: PathBuf,
    pub code_pins: BTreeMap<String, Digest32>,
    pub deadline: Duration,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellFitBudgetV1 {
    pub seed: u32,
    pub steps: u16,
    pub dimension: u16,
    pub hidden: u16,
    pub threshold: f64,
}

/// Original training artifacts are checked by re-export against these selected
/// native digests. A corrected or withdrawn parent requires a clean rebuild.
pub struct MemoryCellReplayParentV1 {
    pub release: Arc<MemoryCellReleaseHostV1>,
    pub selected: Arc<LoadedMemoryCellBundleV1>,
    pub semantic_original: String,
    pub procedure_original: String,
}

pub enum MemoryCellTrainingModeV1 {
    Clean,
    Replay(MemoryCellReplayParentV1),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrainedPayload {
    original: String,
    native: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrainedTypes {
    semantic: TrainedPayload,
    procedure: TrainedPayload,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrainingResponse {
    schema: String,
    scope: ContractIdV1,
    owner_cut_digest: ContractDigestV1,
    request_digest: ContractDigestV1,
    configuration: Value,
    artifacts: TrainedTypes,
    receipt: Value,
}

/// Immutable candidate and measured training receipt. Neither grants selection
/// authority; publication still takes this snapshot to the artifact owner.
pub struct MemoryCellTrainingCandidateV1 {
    snapshot: MemoryCellOwnerSnapshotV1,
    candidate: MemoryCellBundleCandidateV1,
    receipt: Value,
    code_digest: Digest32,
    semantic_original: String,
    procedure_original: String,
    semantic_native: String,
    procedure_native: String,
}

impl MemoryCellTrainingCandidateV1 {
    pub fn snapshot(&self) -> &MemoryCellOwnerSnapshotV1 { &self.snapshot }
    pub fn bundle(&self) -> &MemoryCellBundleCandidateV1 { &self.candidate }
    pub fn receipt(&self) -> &Value { &self.receipt }
    pub fn training_code_digest(&self) -> Digest32 { self.code_digest }
    pub fn original_payloads(&self) -> (&str, &str) { (&self.semantic_original, &self.procedure_original) }
    pub fn native_payloads(&self) -> (&str, &str) { (&self.semantic_native, &self.procedure_native) }
}

impl MemoryCellTrainerConfigV1 {
    fn validate_code(&self) -> Result<Digest32, String> {
        if !self.python.is_absolute() || !self.qualification_root.is_absolute()
            || self.deadline.is_zero() || self.deadline > Duration::from_secs(60)
            || self.code_pins.len() != REQUIRED_CODE.len() {
            return Err("memory trainer configuration bounds".to_string());
        }
        let mut identity = b"hepta.memory.training-code.v1".to_vec();
        for name in REQUIRED_CODE {
            let expected = self.code_pins.get(*name).ok_or_else(|| "memory trainer import pin missing".to_string())?;
            let path = self.qualification_root.join(name);
            let metadata = std::fs::symlink_metadata(&path).map_err(|error| error.to_string())?;
            if !metadata.is_file() || metadata.len() > 1_048_576 {
                return Err("memory trainer code file bound".to_string());
            }
            let bytes = std::fs::read(path).map_err(|error| error.to_string())?;
            if Digest32::of_bytes(&bytes) != *expected {
                return Err("memory trainer code changed".to_string());
            }
            identity.extend_from_slice(&(name.len() as u64).to_be_bytes());
            identity.extend_from_slice(name.as_bytes());
            identity.extend_from_slice(expected.as_array());
        }
        Ok(Digest32::of_bytes(&identity))
    }

    /// Fit both typed parameter cells against the actual current owner. The
    /// future may be cancelled: kill-on-drop prevents a detached training job.
    pub async fn train(
        &self, store: &DurableCognitiveStore, access: &CognitiveAccess,
        scope: &CognitiveScope, generation: ContractGenerationV1,
        budget: MemoryCellFitBudgetV1, mode: MemoryCellTrainingModeV1,
    ) -> Result<MemoryCellTrainingCandidateV1, String> {
        let code_digest = self.validate_code()?;
        if !(1..=1_000).contains(&budget.steps) || !(8..=256).contains(&budget.dimension)
            || !(1..=128).contains(&budget.hidden) || !budget.threshold.is_finite()
            || !(0.0..=1.0).contains(&budget.threshold) {
            return Err("memory training budget exceeded".to_string());
        }
        let now = crate::memory_cell_runtime::now_unix_seconds().map_err(|error| error.to_string())?;
        let snapshot = store.memory_cell_snapshot(access, scope, now).await.map_err(|error| error.to_string())?;
        let (name, parents) = match &mode {
            MemoryCellTrainingModeV1::Clean => ("clean", json!({})),
            MemoryCellTrainingModeV1::Replay(parent) => {
                parent.release.revalidate(&parent.selected)?;
                if generation.get() != parent.selected.generation().get().saturating_add(1)
                    || snapshot.scope() != parent.selected.scope() {
                    return Err("memory replay generation or scope differs".to_string());
                }
                ("replay", json!({
                    "semantic": {"payload": parent.semantic_original, "native_digest": parent.selected.semantic().digest().to_string()},
                    "procedure": {"payload": parent.procedure_original, "native_digest": parent.selected.procedure().digest().to_string()}
                }))
            }
        };
        let mut configuration = serde_json::to_value(&budget).map_err(|error| error.to_string())?;
        configuration["mode"] = Value::String(name.to_string());
        let request = serde_json::to_vec(&json!({
            "schema": "hepta.memory.training-request.v1", "export": snapshot,
            "configuration": configuration, "parents": parents,
        })).map_err(|error| error.to_string())?;
        if request.len() > MAX_JOB_BYTES { return Err("memory training input exceeds bound".to_string()); }
        let request_digest = Digest32::of_bytes(&request);
        let mut child = Command::new(&self.python)
            .args(["-I", "-u", "-B"])
            .arg(self.qualification_root.join("memory-cell-v7/training_worker.py"))
            .env("OPENBLAS_NUM_THREADS", "1").env("OMP_NUM_THREADS", "1")
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())
            .kill_on_drop(true).spawn().map_err(|error| error.to_string())?;
        let mut input = child.stdin.take().ok_or("training input unavailable")?;
        let output = child.stdout.take().ok_or("training output unavailable")?;
        let errors = child.stderr.take().ok_or("training error channel unavailable")?;
        let execution = async {
            let send = async {
                input.write_all(&request).await?;
                input.shutdown().await?;
                drop(input);
                Ok::<_, std::io::Error>(())
            };
            let receive = async {
                let mut bytes = Vec::new();
                output.take((MAX_JOB_BYTES + 1) as u64).read_to_end(&mut bytes).await?;
                Ok::<_, std::io::Error>(bytes)
            };
            let stderr = async {
                let mut bytes = Vec::new();
                errors.take(8_193).read_to_end(&mut bytes).await?;
                Ok::<_, std::io::Error>(bytes)
            };
            let (_, bytes, diagnostics) = tokio::try_join!(send, receive, stderr).map_err(|error| error.to_string())?;
            let status = child.wait().await.map_err(|error| error.to_string())?;
            if !status.success() || bytes.len() > MAX_JOB_BYTES || diagnostics.len() > 8_192 {
                return Err("memory training process failed or exceeded output bounds".to_string());
            }
            Ok(bytes)
        };
        let bytes = tokio::time::timeout(self.deadline, execution).await
            .map_err(|_| "memory training deadline exceeded".to_string())??;
        let response: TrainingResponse = serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
        if response.schema != "hepta.memory.training-result.v1" || response.scope != *snapshot.scope()
            || response.owner_cut_digest != snapshot.owner_cut_digest() || response.request_digest.digest() != request_digest
            || response.configuration != configuration || response.receipt["authority"] != false
            || response.receipt["schema"] != "hepta.memory.training-receipt.v1"
            || serde_json::to_vec(&response.receipt).map_err(|error| error.to_string())?.len() > 32_768 {
            return Err("memory training response binding differs".to_string());
        }
        let candidate = MemoryCellBundleCandidateV1::from_owner_snapshot(&snapshot, generation,
            response.artifacts.semantic.native.as_bytes(), response.artifacts.procedure.native.as_bytes())?;
        if self.validate_code()? != code_digest { return Err("memory training code changed during execution".to_string()); }
        if let MemoryCellTrainingModeV1::Replay(parent) = &mode { parent.release.revalidate(&parent.selected)?; }
        let current = store.memory_cell_snapshot(access, scope,
            crate::memory_cell_runtime::now_unix_seconds().map_err(|error| error.to_string())?).await.map_err(|error| error.to_string())?;
        if current.owner_cut_digest() != snapshot.owner_cut_digest() { return Err("memory source changed during training".to_string()); }
        Ok(MemoryCellTrainingCandidateV1 { snapshot, candidate, receipt: response.receipt, code_digest,
            semantic_original: response.artifacts.semantic.original, procedure_original: response.artifacts.procedure.original,
            semantic_native: response.artifacts.semantic.native, procedure_native: response.artifacts.procedure.native })
    }
}
