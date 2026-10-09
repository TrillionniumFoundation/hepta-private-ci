//! Bounded parameter-only LoRA inference after independent selection and final use.
//! The existing owners retain source, registry, routing and effect authority.
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use codex_hepta_contracts::{FinalUseBinding, VerifiedUseToken};
use codex_hepta_types::{Digest32, StableId};
use serde::{Deserialize, Serialize};
use tokio_util::sync::CancellationToken;

static NEXT_SCRATCH: AtomicU64 = AtomicU64::new(0);

#[derive(Clone)]
pub struct MemoryServingProcessConfigV1 {
    pub python_executable: PathBuf,
    pub interpreter_digest: Digest32,
    pub program: PathBuf,
    pub code_digest: Digest32,
    pub model_directory: PathBuf,
    pub scratch_root: PathBuf,
}

/// Owner-admitted paths, not configuration deserialized from a memory or prompt.
#[derive(Clone)]
pub struct MemoryServingProcessV1 {
    config: MemoryServingProcessConfigV1,
    slots: Arc<tokio::sync::Semaphore>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryServingQueryV1 {
    pub request_id: StableId,
    pub question: String,
    pub question_time: String,
    pub deadline_unix_millis: u64,
}

/// This job has no public constructor or raw-history field. Only the selected
/// Agentd consumer constructs it, after binding qualification and owner state.
#[derive(Clone, Serialize)]
pub(crate) struct MemoryServingJobV1 {
    pub schema: &'static str,
    pub request_id: String,
    pub subject_id: String,
    pub destination_id: String,
    pub route_generation: u64,
    pub base_digest: String,
    pub encoder_digest: String,
    pub payload_digest: String,
    pub scope_digest: String,
    pub selection_digest: String,
    pub qualification_digest: String,
    pub source_support_digest: String,
    pub training_job_digest: String,
    pub trainer_digest: String,
    pub runtime_digest: String,
    pub interpreter_digest: String,
    pub question: String,
    pub question_time: String,
    pub deadline_unix_millis: u64,
}
impl MemoryServingJobV1 {
    pub(crate) fn binding(&self) -> Result<FinalUseBinding, String> {
        if self.question.trim().is_empty() || self.question.len() > 16_384
            || self.question.contains('\0') || self.question_time.trim().is_empty()
            || self.question_time.len() > 256 || self.question_time.contains('\0')
            || self.route_generation == 0 || self.deadline_unix_millis == 0
        {
            return Err("invalid selected-memory query".into());
        }
        let parse = |value: &str| value.parse::<Digest32>().map_err(|e| e.to_string());
        Ok(FinalUseBinding {
            subject_id: self.subject_id.clone(),
            destination_id: self.destination_id.clone(),
            request_sha256: *Digest32::of_bytes(&serde_json::to_vec(self).map_err(|e| e.to_string())?).as_array(),
            scope_sha256: *parse(&self.scope_digest)?.as_array(),
            payload_sha256: *parse(&self.payload_digest)?.as_array(),
        })
    }
}

/// Returned only after child terminality, byte/usage checks and live owner refresh.
/// The answer remains a model prediction; it is not a verified factual citation.
#[derive(Debug)]
pub struct MemoryServingResultV1 {
    pub(crate) answer: String,
    pub(crate) answer_digest: Digest32,
    pub(crate) prompt_digest: Digest32,
    pub(crate) input_tokens: u32,
    pub(crate) output_tokens: u32,
    pub(crate) final_use_witness: [u8; 32],
}
impl MemoryServingResultV1 {
    pub fn answer(&self) -> &str { &self.answer }
    pub fn answer_digest(&self) -> Digest32 { self.answer_digest }
    pub fn prompt_digest(&self) -> Digest32 { self.prompt_digest }
    pub fn usage(&self) -> (u32, u32) { (self.input_tokens, self.output_tokens) }
    pub fn final_use_witness(&self) -> [u8; 32] { self.final_use_witness }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Observation {
    schema: String,
    job_digest: String,
    payload_digest: String,
    selection_digest: String,
    qualification_digest: String,
    scope_digest: String,
    base_digest: String,
    base_unchanged: bool,
    answer: String,
    answer_digest: String,
    input_tokens: u32,
    output_tokens: u32,
    prompt_digest: String,
}
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
    if bytes.is_empty() || bytes.len() as u64 > bound { return Err("serving file byte bound".into()); }
    Ok(bytes)
}
fn now_ms() -> Result<u64, String> {
    u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH).map_err(|e| e.to_string())?.as_millis())
        .map_err(|e| e.to_string())
}
impl MemoryServingProcessV1 {
    pub fn new(config: MemoryServingProcessConfigV1) -> Result<Self, String> {
        if [&config.python_executable, &config.program, &config.model_directory, &config.scratch_root]
            .iter().any(|path| !path.is_absolute())
            || !config.model_directory.is_dir() || !config.scratch_root.is_dir()
            || config.interpreter_digest.is_zero() || config.code_digest.is_zero()
        { return Err("invalid admitted serving installation".into()); }
        let value = Self { config, slots: Arc::new(tokio::sync::Semaphore::new(2)) };
        value.verify_installation()?;
        Ok(value)
    }
    pub fn code_digest(program: &Path) -> Result<Digest32, String> {
        if program.file_name().and_then(|name| name.to_str()) != Some("serving_worker.py") {
            return Err("unregistered serving program".into());
        }
        let directory = program.parent().ok_or("serving program parent")?;
        let mut bytes = b"hepta.memory-serving.python-source.v1\0".to_vec();
        for name in ["native.py", "pretrained.py", "requirements.txt", "serving_worker.py", "sessions.py", "tensor_contract.py"] {
            let content = bounded_read(&directory.join(name), 256 * 1024)?;
            bytes.extend_from_slice(&(name.len() as u64).to_be_bytes());
            bytes.extend_from_slice(name.as_bytes());
            bytes.extend_from_slice(Digest32::of_bytes(&content).as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
    pub(crate) fn runtime_digest(&self) -> Digest32 { self.config.code_digest }
    pub(crate) fn interpreter_digest(&self) -> Digest32 { self.config.interpreter_digest }
    fn verify_installation(&self) -> Result<(), String> {
        if Digest32::of_bytes(&bounded_read(&self.config.python_executable, 64 * 1024 * 1024)?) != self.config.interpreter_digest
            || Self::code_digest(&self.config.program)? != self.config.code_digest
        { return Err("serving interpreter/code changed".into()); }
        Ok(())
    }
    pub(crate) fn execute(&self, job: MemoryServingJobV1, payload: Vec<u8>, token: VerifiedUseToken, cancel: CancellationToken) -> Result<MemoryServingResultV1, String> {
        let _permit = self.slots.try_acquire().map_err(|_| "selected-memory serving capacity")?;
        self.verify_installation()?;
        let binding = job.binding()?;
        let remaining = job.deadline_unix_millis.checked_sub(now_ms()?).ok_or("serving deadline expired")?;
        if remaining == 0 || remaining > 300_000 || payload.is_empty() || payload.len() > 64 * 1024 * 1024
            || Digest32::of_bytes(&payload).as_array() != &binding.payload_sha256
            || job.runtime_digest != self.config.code_digest.to_string()
            || job.interpreter_digest != self.config.interpreter_digest.to_string()
            || cancel.is_cancelled()
        { return Err("serving deadline/payload/profile rejected".into()); }
        let path = self.config.scratch_root.join(format!("memory-serve-{}-{}-{}", std::process::id(), now_ms()?, NEXT_SCRATCH.fetch_add(1, Ordering::Relaxed)));
        let mut builder = fs::DirBuilder::new();
        #[cfg(unix)] {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder.create(&path).map_err(|e| e.to_string())?;
        let scratch = Scratch(path);
        fs::write(scratch.0.join("job.json"), serde_json::to_vec(&job).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        fs::write(scratch.0.join("adapter.safetensors"), payload).map_err(|e| e.to_string())?;
        // Last authority check before starting model computation. Consuming one
        // nonce cannot authorize another node, route generation, query or model.
        self.verify_installation()?;
        if cancel.is_cancelled() { return Err("selected-memory inference cancelled".into()); }
        let entered = token.enter(&binding).map_err(|e| e.to_string())?;
        let witness = entered.witness_sha256();
        let child = Command::new(&self.config.python_executable).arg(&self.config.program)
            .arg(scratch.0.join("job.json")).arg(&scratch.0).arg(&self.config.model_directory)
            .env_clear().env("HF_HUB_OFFLINE", "1").env("TRANSFORMERS_OFFLINE", "1")
            .env("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1").env("TOKENIZERS_PARALLELISM", "false")
            .env("PYTHONDONTWRITEBYTECODE", "1").env("OMP_NUM_THREADS", "2").env("OPENBLAS_NUM_THREADS", "2").env("PYTHONHASHSEED", "0")
            .current_dir(&scratch.0).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())
            .spawn().map_err(|e| e.to_string())?;
        let mut child = RunningChild(child);
        let started = Instant::now();
        loop {
            if cancel.is_cancelled() { return Err("selected-memory inference cancelled".into()); }
            if started.elapsed() >= Duration::from_millis(remaining) || now_ms()? >= job.deadline_unix_millis {
                return Err("selected-memory inference deadline exceeded".into());
            }
            if let Some(status) = child.0.try_wait().map_err(|e| e.to_string())? {
                if !status.success() { return Err(format!("selected-memory worker failed: {status}")); }
                break;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        let output: Observation = serde_json::from_slice(&bounded_read(&scratch.0.join("observation.json"), 256 * 1024)?).map_err(|e| e.to_string())?;
        if output.schema != "hepta.memory-serving.observation.v1"
            || output.job_digest != Digest32::of_bytes(&serde_json::to_vec(&job).map_err(|e| e.to_string())?).to_string()
            || output.payload_digest != job.payload_digest || output.selection_digest != job.selection_digest
            || output.qualification_digest != job.qualification_digest || output.scope_digest != job.scope_digest
            || output.base_digest != job.base_digest || !output.base_unchanged
            || output.answer.trim().is_empty() || output.answer.len() > 65_536
            || output.input_tokens == 0 || output.input_tokens > 1024 || output.output_tokens == 0 || output.output_tokens > 32
            || output.answer_digest != Digest32::of_bytes(output.answer.as_bytes()).to_string()
        { return Err("selected-memory observation mismatch".into()); }
        let prompt_digest: Digest32 = output.prompt_digest.parse().map_err(|_| "serving prompt digest")?;
        if prompt_digest.is_zero() { return Err("zero serving prompt digest".into()); }
        Ok(MemoryServingResultV1 { answer_digest: Digest32::of_bytes(output.answer.as_bytes()), answer: output.answer,
            prompt_digest, input_tokens: output.input_tokens, output_tokens: output.output_tokens, final_use_witness: witness })
    }
}

#[cfg(all(test, unix))]
#[path = "memory_serving_process_tests.rs"]
mod tests;
