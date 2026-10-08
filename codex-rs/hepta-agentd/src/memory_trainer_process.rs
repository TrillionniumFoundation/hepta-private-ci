//! Bounded offline tensor worker for a source-admitted learning.operator job.
//! No shell, provider dispatch, environment credentials, or model installation.
use std::fs;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_bellman_operator::MemoryTrainingObservationV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::SharedMemoryTrainingV1;

/// Paths must be admitted, owner-protected local installations. Code content and
/// interpreter bytes are checked at construction and again before every launch.
#[derive(Clone)]
pub struct MemoryTrainerProcessConfigV1 {
    pub python_executable: PathBuf,
    pub interpreter_digest: Digest32,
    pub program: PathBuf,
    pub code_digest: Digest32,
    pub model_directory: PathBuf,
    pub scratch_root: PathBuf,
}

pub struct MemoryTrainerProcessV1 { config: MemoryTrainerProcessConfigV1 }

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ObservationWire {
    job_digest: String,
    base_digest: String,
    frozen_base_after_digest: String,
    encoder_digest: String,
    trainer_digest: String,
    payload_digest: String,
    payload_bytes: u64,
    completed_steps: u32,
    consumed_tokens: u64,
    trainable_parameters: u64,
    changed_parameters: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WorkerOutput { observation: ObservationWire, metrics: serde_json::Value }

struct RunningChild(Child);
impl Drop for RunningChild {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() { let _ = self.0.kill(); }
        let _ = self.0.wait();
    }
}
struct Scratch(PathBuf);
impl Drop for Scratch {
    fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
}

fn bounded_read(path: &Path, bound: u64) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    fs::File::open(path).map_err(|e| e.to_string())?.take(bound + 1)
        .read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    if bytes.len() as u64 > bound { return Err("worker file exceeds bound".into()); }
    Ok(bytes)
}

impl MemoryTrainerProcessV1 {
    pub fn new(config: MemoryTrainerProcessConfigV1) -> Result<Self, String> {
        for path in [&config.python_executable, &config.program, &config.model_directory, &config.scratch_root] {
            if !path.is_absolute() { return Err("worker paths must be absolute".into()); }
        }
        if !config.model_directory.is_dir() || !config.scratch_root.is_dir() {
            return Err("missing admitted model/scratch directory".into());
        }
        let value = Self { config };
        value.verify_installation()?;
        Ok(value)
    }

    pub fn code_digest(program: &Path) -> Result<Digest32, String> {
        let directory = program.parent().ok_or("worker program parent")?;
        if program.file_name().and_then(|s| s.to_str()) != Some("owner_worker.py") {
            return Err("unregistered worker program".into());
        }
        let mut bytes = b"hepta.memory-training.python-source.v1\0".to_vec();
        for name in ["native.py", "owner_worker.py", "pretrained.py", "requirements.txt"] {
            let content = bounded_read(&directory.join(name), 256 * 1024)?;
            bytes.extend_from_slice(&(name.len() as u64).to_be_bytes());
            bytes.extend_from_slice(name.as_bytes());
            bytes.extend_from_slice(Digest32::of_bytes(&content).as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    fn verify_installation(&self) -> Result<(), String> {
        if self.config.interpreter_digest.is_zero() || self.config.code_digest.is_zero()
            || Digest32::of_bytes(&bounded_read(&self.config.python_executable, 64 * 1024 * 1024)?) != self.config.interpreter_digest
            || Self::code_digest(&self.config.program)? != self.config.code_digest
        { return Err("worker interpreter or code drift".into()); }
        Ok(())
    }

    /// Execute on the caller's bounded training pool, never a foreground runtime
    /// executor thread. The returned bytes are still only a candidate; Agentd's
    /// finish boundary must recheck source grants and the learning dataset.
    pub fn execute(
        &self,
        prepared: &SharedMemoryTrainingV1,
        now: u64,
    ) -> Result<(MemoryTrainingObservationV1, Vec<u8>, serde_json::Value), String> {
        self.verify_installation()?;
        let frozen = prepared.frozen();
        let profile = frozen.profile();
        if profile.trainer_digest != self.config.code_digest || profile.expires_at <= now {
            return Err("training profile expired or wrong worker".into());
        }
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|e| e.to_string())?.as_nanos();
        let path = self.config.scratch_root.join(format!("memory-{}-{}-{nonce}", frozen.job_digest(), std::process::id()));
        let mut builder = fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder.create(&path).map_err(|e| e.to_string())?;
        let scratch = Scratch(path);
        let request = serde_json::json!({
            "schema": "hepta.memory-training.worker.v1", "job_digest": frozen.job_digest().to_string(),
            "base_digest": profile.base_digest.to_string(), "encoder_digest": profile.encoder_digest.to_string(),
            "trainer_digest": profile.trainer_digest.to_string(), "scope_digest": profile.scope_digest.to_string(),
            "source_support_digest": frozen.source_support().to_string(), "source_content_digest": frozen.content_digest().to_string(),
            "source_text": frozen.source_text(), "maximum_steps": profile.maximum_steps,
            "maximum_tokens_per_step": profile.maximum_tokens_per_step, "maximum_payload_bytes": profile.maximum_payload_bytes,
        });
        fs::write(scratch.0.join("job.json"), serde_json::to_vec(&request).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        let child = Command::new(&self.config.python_executable)
            .arg(&self.config.program).arg("train").arg(scratch.0.join("job.json"))
            .arg(&scratch.0).arg(&self.config.model_directory)
            .env_clear().env("HF_HUB_OFFLINE", "1").env("TRANSFORMERS_OFFLINE", "1")
            .env("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1").env("TOKENIZERS_PARALLELISM", "false")
            .env("OMP_NUM_THREADS", "2").env("OPENBLAS_NUM_THREADS", "2").env("PYTHONHASHSEED", "0")
            .current_dir(&scratch.0).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())
            .spawn().map_err(|e| e.to_string())?;
        let mut child = RunningChild(child);
        let started = Instant::now();
        let timeout = Duration::from_secs((profile.expires_at - now).min(300));
        loop {
            if let Some(status) = child.0.try_wait().map_err(|e| e.to_string())? {
                if !status.success() { return Err(format!("tensor worker terminal failure: {status}")); }
                break;
            }
            if started.elapsed() >= timeout {
                child.0.kill().map_err(|e| e.to_string())?;
                child.0.wait().map_err(|e| e.to_string())?;
                return Err("tensor worker deadline exceeded".into());
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        let output: WorkerOutput = serde_json::from_slice(&bounded_read(&scratch.0.join("receipt.json"), 256 * 1024)?)
            .map_err(|e| e.to_string())?;
        let payload = bounded_read(&scratch.0.join("adapter.safetensors"), profile.maximum_payload_bytes)?;
        let observed = output.observation;
        let parse = |s: &str| s.parse::<Digest32>().map_err(|_| "worker digest encoding".to_string());
        let receipt = MemoryTrainingObservationV1 {
            job_digest: parse(&observed.job_digest)?, base_digest: parse(&observed.base_digest)?,
            frozen_base_after_digest: parse(&observed.frozen_base_after_digest)?, encoder_digest: parse(&observed.encoder_digest)?,
            trainer_digest: parse(&observed.trainer_digest)?, payload_digest: parse(&observed.payload_digest)?,
            payload_bytes: observed.payload_bytes, completed_steps: observed.completed_steps, consumed_tokens: observed.consumed_tokens,
            trainable_parameters: observed.trainable_parameters, changed_parameters: observed.changed_parameters,
        };
        Ok((receipt, payload, output.metrics))
    }
}
