//! Local Laya backend inside inference.worker, never a new authority owner.
//! Four Q24 retrieval features produce advisory benefit predictions only.
use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverNeuronFeatureObservation;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelDriver;
use crate::model_worker::ModelManifest;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::WorkerRequest;
use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;
use std::process::Child;
use std::process::ChildStdin;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
const Q24: i64 = 1 << 24;
const MAX_FRAME: u64 = 16_384;

/// Immutable operator-selected backend and stop-only control, not a grant.
pub struct LayaCellConfig {
    pub python: PathBuf,
    pub backend: PathBuf,
    pub model: PathBuf,
    pub candidate: Option<PathBuf>,
    pub base_sha256: String,
    pub backend_sha256: String,
    pub load_timeout: Duration,
    pub stop_timeout: Duration,
    pub cancel: Arc<AtomicBool>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Ready {
    manifest: ModelManifest,
    encoder_digest: String,
    head_digest: String,
    memory_bytes: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Prediction {
    request_id: String,
    prediction_q24: Vec<i64>,
    memory_bytes: u64,
    latency_micros: u64,
}
struct Process {
    child: Child,
    stdin: Option<ChildStdin>,
    responses: mpsc::Receiver<Result<Vec<u8>, String>>,
    handle: DriverModelHandle,
    ready: Option<Ready>,
}
pub struct LayaCellDriver {
    config: LayaCellConfig,
    process: Option<Process>,
}
impl LayaCellDriver {
    pub fn new(config: LayaCellConfig) -> Result<Self, Error> {
        if !config.python.is_absolute()
            || !config.backend.is_absolute()
            || !config.model.is_absolute()
            || config.candidate.as_ref().is_some_and(|p| !p.is_absolute())
            || config.load_timeout.is_zero()
            || config.load_timeout > Duration::from_secs(300)
            || config.stop_timeout.is_zero()
            || config.stop_timeout > Duration::from_secs(5)
            || !valid_digest(&config.base_sha256)
            || !valid_digest(&config.backend_sha256)
        {
            return Err(Error::InvalidManifest);
        }
        Ok(Self {
            config,
            process: None,
        })
    }
    fn receive(&self, deadline: Instant) -> Result<Vec<u8>, Error> {
        let process = self.process.as_ref().ok_or(Error::ModelNotLoaded)?;
        loop {
            if self.config.cancel.load(Ordering::Acquire) {
                return Err(Error::DriverFailure("Laya cancelled".to_string()));
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(Error::DeadlineExpired);
            }
            match process
                .responses
                .recv_timeout(remaining.min(Duration::from_millis(20)))
            {
                Ok(Ok(bytes)) => return Ok(bytes),
                Ok(Err(reason)) => return Err(Error::DriverFailure(reason)),
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(_) => {
                    return Err(Error::DriverFailure(
                        "Laya response stream ended".to_string(),
                    ));
                }
            }
        }
    }
    fn stop(&mut self) -> Result<(), Error> {
        let Some(process) = self.process.as_mut() else {
            return Ok(());
        };
        process.stdin.take();
        let deadline = Instant::now() + self.config.stop_timeout;
        if process.child.try_wait().map_err(driver_io)?.is_none()
            && process.child.kill().is_err()
            && process.child.try_wait().map_err(driver_io)?.is_none()
        {
            return Err(Error::CleanupPending(process.handle.opaque_id.clone()));
        }
        loop {
            if process.child.try_wait().map_err(driver_io)?.is_some() {
                self.process.take();
                return Ok(());
            }
            if Instant::now() >= deadline {
                return Err(Error::CleanupPending(process.handle.opaque_id.clone()));
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
    fn fail<T>(&mut self, error: Error) -> Result<T, Error> {
        self.stop()?;
        Err(error)
    }
    fn send(&mut self, mut bytes: Vec<u8>, deadline: Instant) -> Result<(), Error> {
        if bytes.len() >= MAX_FRAME as usize {
            return Err(Error::FeatureLimit);
        }
        bytes.push(b'\n');
        let process = self.process.as_mut().ok_or(Error::ModelNotLoaded)?;
        let mut stdin = process.stdin.take().ok_or(Error::ModelCleanupPending)?;
        let (tx, rx) = mpsc::sync_channel(1);
        // A blocked pipe writer cannot extend the caller's deadline.
        std::thread::spawn(move || {
            let result = stdin.write_all(&bytes).and_then(|()| stdin.flush());
            let _ = tx.send((stdin, result));
        });
        loop {
            if self.config.cancel.load(Ordering::Acquire) {
                return Err(Error::DriverFailure("Laya cancelled".to_string()));
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(Error::DeadlineExpired);
            }
            match rx.recv_timeout(remaining.min(Duration::from_millis(20))) {
                Ok((stdin, result)) => {
                    process.stdin = Some(stdin);
                    return result.map_err(driver_io);
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(_) => return Err(Error::DriverFailure("Laya writer failed".to_string())),
            }
        }
    }
}
impl ModelDriver for LayaCellDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if self.process.is_some() {
            return Err(Error::ModelAlreadyLoaded);
        }
        if self.config.cancel.load(Ordering::Acquire) {
            return Err(Error::DriverFailure(
                "Laya cancelled before load".to_string(),
            ));
        }
        if manifest.model_id != "laya.retrieval-continuation-v1" || manifest.maximum_tokens != 512 {
            return Err(Error::InvalidManifest);
        }
        let meta = std::fs::symlink_metadata(&self.config.backend).map_err(driver_io)?;
        if !meta.is_file() || meta.len() > 65_536 {
            return Err(Error::InvalidManifest);
        }
        let backend = std::fs::read(&self.config.backend).map_err(driver_io)?;
        if format!("{:x}", Sha256::digest(&backend)) != self.config.backend_sha256 {
            return Err(Error::InvalidManifest);
        }
        let mut command = Command::new(&self.config.python);
        command
            .arg(&self.config.backend)
            .arg("--model")
            .arg(&self.config.model)
            .arg("--base-sha256")
            .arg(&self.config.base_sha256)
            .env_clear()
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONNOUSERSITE", "1")
            .env("HF_HUB_OFFLINE", "1")
            .env("TRANSFORMERS_OFFLINE", "1")
            .env("TOKENIZERS_PARALLELISM", "false")
            .env("OMP_NUM_THREADS", "4")
            .env("MKL_NUM_THREADS", "4")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if let Some(candidate) = &self.config.candidate {
            command.arg("--candidate").arg(candidate);
        }
        let mut child = command.spawn().map_err(driver_io)?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| Error::DriverFailure("missing Laya output".to_string()))?;
        let stdin = child.stdin.take();
        let (tx, responses) = mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut frame = Vec::new();
                let result = (&mut reader)
                    .take(MAX_FRAME + 1)
                    .read_until(b'\n', &mut frame);
                match result {
                    Ok(0) => break,
                    Ok(_) if frame.len() <= MAX_FRAME as usize && frame.ends_with(b"\n") => {
                        if tx.send(Ok(frame)).is_err() {
                            break;
                        }
                    }
                    _ => {
                        let _ = tx.send(Err("invalid or oversized Laya frame".to_string()));
                        break;
                    }
                }
            }
        });
        let handle = DriverModelHandle {
            opaque_id: format!("laya-{}-{}", child.id(), manifest.model_digest),
            observed_memory_bytes: 0,
        };
        self.process = Some(Process {
            child,
            stdin,
            responses,
            handle,
            ready: None,
        });
        let bytes = match self.receive(Instant::now() + self.config.load_timeout) {
            Ok(value) => value,
            Err(error) => return self.fail(error),
        };
        let ready: Ready = match serde_json::from_slice(&bytes) {
            Ok(value) => value,
            Err(_) => return self.fail(Error::FeatureContract),
        };
        if &ready.manifest != manifest
            || ready.memory_bytes == 0
            || !valid_digest(&ready.encoder_digest)
            || !valid_digest(&ready.head_digest)
        {
            return self.fail(Error::ModelMismatch);
        }
        let process = self.process.as_mut().ok_or(Error::ModelNotLoaded)?;
        process.handle.observed_memory_bytes = ready.memory_bytes;
        process.ready = Some(ready);
        Ok(process.handle.clone())
    }
    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Err(Error::DriverFailure(
            "Laya accepts only the Neuron feature port".to_string(),
        ))
    }
    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        if self
            .process
            .as_ref()
            .is_some_and(|p| p.handle.opaque_id != handle.opaque_id)
        {
            return Err(Error::ModelMismatch);
        }
        self.stop()
    }
}

impl NeuronFeatureDriver for LayaCellDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        let process = self.process.as_ref().ok_or(Error::ModelNotLoaded)?;
        let ready = process.ready.as_ref().ok_or(Error::ModelNotLoaded)?;
        if process.handle.opaque_id != handle.opaque_id
            || request.encoder_digest != ready.encoder_digest
            || request.head_digest != ready.head_digest
            || request.weights_digest != ready.manifest.weights_digest
        {
            return Err(Error::ModelMismatch);
        }
        if request.feature_vector_q24.len() != 4
            || request.expected_output_width != 2
            || request
                .feature_vector_q24
                .iter()
                .any(|v| !(0..=Q24).contains(v))
        {
            return Err(Error::FeatureLimit);
        }
        let memory_before = ready.memory_bytes;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| Error::DeadlineExpired)?
            .as_millis();
        let remaining = u128::from(request.authorization.deadline_ms)
            .checked_sub(now)
            .ok_or(Error::DeadlineExpired)?;
        let remaining =
            u64::try_from(remaining.min(3_600_000)).map_err(|_| Error::ArithmeticOverflow)?;
        let deadline = Instant::now() + Duration::from_millis(remaining);
        let started = Instant::now();
        let input = serde_json::to_vec(&serde_json::json!({
            "request_id": request.authorization.request_id,
            "features_q24": request.feature_vector_q24,
        }))
        .map_err(|_| Error::FeatureContract)?;
        if let Err(error) = self.send(input, deadline) {
            return self.fail(error);
        }
        let bytes = match self.receive(deadline) {
            Ok(value) => value,
            Err(error) => return self.fail(error),
        };
        let prediction: Prediction = match serde_json::from_slice(&bytes) {
            Ok(value) => value,
            Err(_) => return self.fail(Error::FeatureContract),
        };
        if prediction.request_id != request.authorization.request_id
            || prediction.prediction_q24.len() != 2
            || prediction
                .prediction_q24
                .iter()
                .any(|v| !(0..=Q24).contains(v))
            || prediction.prediction_q24.iter().sum::<i64>() != Q24
            || prediction.memory_bytes == 0
            || prediction.latency_micros == 0
        {
            return self.fail(Error::FeatureContract);
        }
        if self.config.cancel.load(Ordering::Acquire) || Instant::now() >= deadline {
            return self.fail(Error::DeadlineExpired);
        }
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: true,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: request.head_digest.clone(),
            drive_q24: prediction.prediction_q24.clone(),
            prediction_q24: prediction.prediction_q24,
            observed_memory_bytes: prediction.memory_bytes,
            transient_allocation_bytes: prediction.memory_bytes.saturating_sub(memory_before),
            queue_age_micros: 0,
            latency_micros: u64::try_from(started.elapsed().as_micros())
                .map_err(|_| Error::ArithmeticOverflow)?,
        })
    }
}
impl Drop for LayaCellDriver {
    fn drop(&mut self) {
        let _ = self.stop();
    }
}
fn driver_io(error: std::io::Error) -> Error {
    Error::DriverFailure(error.to_string())
}
fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value.bytes().any(|b| b != b'0')
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[cfg(test)]
#[path = "laya_cell_tests.rs"]
mod tests;
