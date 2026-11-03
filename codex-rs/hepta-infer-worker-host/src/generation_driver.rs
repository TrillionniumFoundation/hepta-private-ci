//! Registered, cold-start CPU generation backend for the existing worker.
//! The trusted host fixes paths and hashes once. Requests cannot select an
//! executable, script, checkpoint or output path. No grant is created here.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_infer_core::GENERATION_MAX_BYTES;
use codex_hepta_infer_core::GenerationExecutionV1;
use codex_hepta_infer_core::GenerationModelPinsV1;
use codex_hepta_infer_core::GenerationRequestV1;
use codex_hepta_infer_core::generation_json_digest;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelDriver;
use crate::model_worker::ModelManifest;
use crate::model_worker::WorkerRequest;

#[path = "generation_neuron.rs"]
pub mod neuron;

const SOURCE_DIR: &str = "experiments/multimodal_output_portfolio/v6";
const SOURCES: [&str; 6] = [
    "conditioned.py",
    "data.py",
    "neural.py",
    "observer.py",
    "owner_worker.py",
    "plan_training.py",
];

/// Immutable owner registration, supplied before constructing the worker.
pub struct GenerationRegistrationV1 {
    pub repository: PathBuf,
    pub python: PathBuf,
    pub artifact_root: PathBuf,
    pub checkpoint_name: String,
    pub model_id: String,
    pub pins: GenerationModelPinsV1,
    pub timeout: Duration,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationProcessEvidenceV1 {
    pub schema: String,
    pub request_sha256: String,
    pub model: GenerationModelPinsV1,
    pub execution: Option<GenerationExecutionV1>,
    pub exit_code: Option<i32>,
    pub timed_out: bool,
    pub stderr: String,
    pub stderr_truncated: bool,
    pub stdout: Vec<u8>,
    pub stdout_truncated: bool,
    /// Includes process creation, imports, cold model load and execution.
    pub host_wall_ns: u64,
    pub diagnostic: Option<String>,
    pub authority: String,
}

/// Read-only evidence view; callers cannot inject a successful worker result.
#[derive(Clone, Default)]
pub struct GenerationEvidenceV1(Arc<Mutex<BTreeMap<String, GenerationProcessEvidenceV1>>>);

impl GenerationEvidenceV1 {
    pub fn get(&self, payload: &str) -> Option<GenerationProcessEvidenceV1> {
        self.0.lock().ok()?.get(payload).cloned()
    }
}

pub struct GenerationDriver {
    registration: GenerationRegistrationV1,
    requests: BTreeMap<String, GenerationRequestV1>,
    evidence: GenerationEvidenceV1,
    neuron: neuron::GenerationNeuronRegistry,
}

fn failure(message: impl std::fmt::Display) -> Error {
    Error::DriverFailure(message.to_string())
}

pub fn generation_source_digest(repository: &Path) -> Result<String, Error> {
    let mut bytes = Vec::new();
    for name in SOURCES {
        let path = repository.join(SOURCE_DIR).join(name);
        if path.is_symlink() {
            return Err(failure("source symlink"));
        }
        let content = std::fs::read(path).map_err(failure)?;
        bytes.extend_from_slice(format!("{name}\0{}\n", Digest32::of_bytes(&content)).as_bytes());
    }
    Ok(Digest32::of_bytes(&bytes).to_string())
}

impl GenerationDriver {
    pub fn new(
        registration: GenerationRegistrationV1,
        requests: Vec<GenerationRequestV1>,
    ) -> Result<Self, Error> {
        if registration.timeout.is_zero()
            || registration.timeout > Duration::from_secs(60)
            || requests.is_empty()
            || requests.len() > 128
            || Path::new(&registration.checkpoint_name)
                .components()
                .count()
                != 1
            || matches!(registration.checkpoint_name.as_str(), "" | "." | "..")
            || !registration.python.is_absolute()
            || !registration.repository.is_absolute()
            || !registration.artifact_root.is_absolute()
        {
            return Err(failure("registration bounds"));
        }
        let mut prepared = BTreeMap::new();
        let mut identities = BTreeSet::new();
        for request in requests {
            request.validate(&registration.pins).map_err(failure)?;
            if !identities.insert(request.request_id.clone()) {
                return Err(failure("duplicate request identity"));
            }
            prepared.insert(generation_json_digest(&request).map_err(failure)?, request);
        }
        let driver = Self {
            registration,
            requests: prepared,
            evidence: GenerationEvidenceV1::default(),
            neuron: neuron::GenerationNeuronRegistry::default(),
        };
        driver.verify_registration()?;
        Ok(driver)
    }

    pub fn evidence(&self) -> GenerationEvidenceV1 {
        self.evidence.clone()
    }

    pub fn manifest(&self) -> Result<ModelManifest, Error> {
        let pins = &self.registration.pins;
        Ok(ModelManifest {
            model_id: self.registration.model_id.clone(),
            model_digest: generation_json_digest(pins).map_err(failure)?,
            weights_digest: pins.parameters_sha256.clone(),
            tokenizer_digest: pins.source_sha256.clone(),
            preprocessor_digest: pins.source_sha256.clone(),
            quantization_digest: Digest32::of_bytes(b"float32.cpu.no-quantization.v1").to_string(),
            runtime_digest: generation_json_digest(&pins.runtime_versions).map_err(failure)?,
            device_digest: pins.device_sha256.clone(),
            maximum_tokens: 8,
        })
    }

    fn checkpoint(&self) -> PathBuf {
        self.registration
            .artifact_root
            .join(&self.registration.checkpoint_name)
    }

    fn verify_registration(&self) -> Result<(), Error> {
        let pins = &self.registration.pins;
        pins.validate().map_err(failure)?;
        if self.checkpoint().is_symlink()
            || std::fs::metadata(self.checkpoint()).map_err(failure)?.len() > 64 * 1024 * 1024
            || Digest32::of_bytes(&std::fs::read(self.checkpoint()).map_err(failure)?).to_string()
                != pins.checkpoint_sha256
            || Digest32::of_bytes(&std::fs::read(&self.registration.python).map_err(failure)?)
                .to_string()
                != pins.python_sha256
            || generation_source_digest(&self.registration.repository)? != pins.source_sha256
        {
            return Err(failure("registered artifact/source/runtime changed"));
        }
        Ok(())
    }

    fn invoke(&self, request: &GenerationRequestV1) -> Result<GenerationProcessEvidenceV1, Error> {
        let payload = serde_json::to_vec(&serde_json::json!({
            "checkpoint": self.checkpoint(), "request_json": serde_json::to_string(request).map_err(failure)?,
        })).map_err(failure)?;
        if payload.len() > GENERATION_MAX_BYTES {
            return Err(failure("envelope bound"));
        }
        let started = Instant::now();
        let mut evidence = GenerationProcessEvidenceV1 {
            schema: "hepta.inference.generation-process.v1".into(),
            request_sha256: generation_json_digest(request).map_err(failure)?,
            model: request.model.clone(),
            execution: None,
            exit_code: None,
            timed_out: false,
            stderr: String::new(),
            stderr_truncated: false,
            stdout: Vec::new(),
            stdout_truncated: false,
            host_wall_ns: 0,
            diagnostic: None,
            authority: "deny_all".into(),
        };
        let spawned = Command::new(&self.registration.python)
            // POSIX CPU backend: do not execute an ignored, stale source-tree
            // bytecode cache. /dev/null cannot contain cached module children.
            .arg("-I")
            .arg("-B")
            .arg("-X")
            .arg("pycache_prefix=/dev/null")
            .arg(
                self.registration
                    .repository
                    .join(SOURCE_DIR)
                    .join("owner_worker.py"),
            )
            .current_dir(&self.registration.repository)
            .env("OMP_NUM_THREADS", "1")
            .env("MKL_NUM_THREADS", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn();
        let mut child = match spawned {
            Ok(child) => child,
            Err(error) => {
                evidence.host_wall_ns =
                    u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX);
                evidence.diagnostic = Some(format!("process start failed: {error}"));
                return Ok(evidence);
            }
        };
        let mut stdin = child.stdin.take().ok_or_else(|| failure("stdin"))?;
        let stdout = child.stdout.take().ok_or_else(|| failure("stdout"))?;
        let stderr = child.stderr.take().ok_or_else(|| failure("stderr"))?;
        let writer = thread::spawn(move || stdin.write_all(&payload));
        let reader = thread::spawn(move || {
            let mut bytes = Vec::new();
            stdout
                .take(GENERATION_MAX_BYTES as u64 + 1)
                .read_to_end(&mut bytes)
                .map(|_| bytes)
        });
        let errors = thread::spawn(move || {
            let mut bytes = Vec::new();
            stderr.take(16_385).read_to_end(&mut bytes).map(|_| bytes)
        });
        let (status, timed_out) = loop {
            match child.try_wait().map_err(failure)? {
                Some(status) => break (status, false),
                None if started.elapsed() >= self.registration.timeout => {
                    child.kill().map_err(failure)?;
                    break (child.wait().map_err(failure)?, true);
                }
                None => thread::sleep(Duration::from_millis(5)),
            }
        };
        let _write_result = writer.join().map_err(|_| failure("writer thread"))?;
        let bytes = reader
            .join()
            .map_err(|_| failure("stdout thread"))?
            .map_err(failure)?;
        let stderr = errors
            .join()
            .map_err(|_| failure("stderr thread"))?
            .map_err(failure)?;
        evidence.exit_code = status.code();
        evidence.timed_out = timed_out;
        evidence.stderr = String::from_utf8_lossy(&stderr[..stderr.len().min(16_384)]).into_owned();
        evidence.stderr_truncated = stderr.len() > 16_384;
        evidence.stdout = bytes[..bytes.len().min(GENERATION_MAX_BYTES)].to_vec();
        evidence.stdout_truncated = bytes.len() > GENERATION_MAX_BYTES;
        evidence.host_wall_ns = u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX);
        if status.success() && !timed_out {
            let verified = (|| {
                if bytes.len() > GENERATION_MAX_BYTES {
                    return Err(failure("output bound"));
                }
                let output: GenerationExecutionV1 =
                    serde_json::from_slice(&bytes).map_err(failure)?;
                output.verify(request).map_err(failure)?;
                self.verify_registration()?;
                Ok(output)
            })();
            match verified {
                Ok(output) => evidence.execution = Some(output),
                Err(error) => evidence.diagnostic = Some(error.to_string()),
            }
        }
        Ok(evidence)
    }
}

impl ModelDriver for GenerationDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.verify_registration()?;
        if manifest != &self.manifest()? {
            return Err(Error::ModelMismatch);
        }
        // This backend deliberately cold-loads per invocation. Zero here means
        // no resident model process; actual peak RSS is returned by execution.
        Ok(DriverModelHandle {
            opaque_id: manifest.model_digest.clone(),
            observed_memory_bytes: 0,
        })
    }

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        // The decoder emits eight token positions (including BOS), even when
        // rendering stops at an earlier EOS. Reserve before execution or
        // returning a cached eight-token observation.
        if request.maximum_tokens < 8 || request.reservation_maximum_tokens < 8 {
            return Err(Error::TokenLimit);
        }
        self.verify_registration()?;
        if handle.opaque_id != request.model_digest
            || request.model_digest != self.manifest()?.model_digest
        {
            return Err(Error::ModelMismatch);
        }
        let prepared = self
            .requests
            .get(&request.payload_digest)
            .ok_or(Error::PayloadMismatch)?;
        if request.request_id != prepared.request_id {
            return Err(Error::PayloadMismatch);
        }
        let evidence = match self.evidence.get(&request.payload_digest) {
            Some(evidence) => evidence,
            None => {
                let evidence = self.invoke(prepared)?;
                self.evidence
                    .0
                    .lock()
                    .map_err(|_| failure("evidence lock"))?
                    .insert(request.payload_digest.clone(), evidence.clone());
                evidence
            }
        };
        let valid = evidence.execution.as_ref();
        Ok(DriverRunObservation {
            terminal_observed: !evidence.timed_out
                && (valid.is_some() || evidence.exit_code.is_some_and(|code| code != 0)),
            succeeded: valid.is_some(),
            output_digest: valid
                .map(generation_json_digest)
                .transpose()
                .map_err(failure)?,
            consumed_tokens: if valid.is_some() { 8 } else { 0 },
            // The legacy field cannot represent missing measurement. On failure,
            // zero is not measured RSS: execution=None retains that distinction.
            observed_memory_bytes: valid.map_or(0, |output| output.peak_rss_bytes),
        })
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        if handle.opaque_id != self.manifest()?.model_digest {
            return Err(Error::ModelMismatch);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "generation_driver_tests.rs"]
mod tests;
