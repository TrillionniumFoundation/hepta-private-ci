//! Digest-pinned local model execution through an operator-selected runtime process.
//!
//! This adapter is deliberately runtime-agnostic. It does not download models,
//! discover devices, mint grants, or claim an OS sandbox. It verifies every
//! local artifact and the runtime binary against the selected ModelManifest,
//! passes an already-verified ResourceGrant to the runtime as a hard requested
//! memory ceiling, and requires a completed reservation/load handshake before
//! the model becomes usable.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::ChildStdin;
use std::process::ChildStdout;
use std::process::Command;
use std::process::Stdio;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;

use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelDriver;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;
use crate::model_worker::WorkerRequest;

pub const LOCAL_RUNTIME_PROTOCOL: &str = "hepta.local-model-driver.v1";
const DEFAULT_MAX_PROTOCOL_LINE_BYTES: usize = 2 * 1024 * 1024;
const HARD_MAX_PROTOCOL_LINE_BYTES: usize = 8 * 1024 * 1024;
const MAX_OUTPUT_BYTES: usize = 1024 * 1024;
const DEFAULT_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalModelArtifacts {
    pub weights_path: PathBuf,
    pub tokenizer_path: PathBuf,
    pub preprocessor_path: PathBuf,
    pub quantization_path: PathBuf,
    /// A read-only descriptor selected by the device authority/launcher. Its
    /// digest is the manifest's device_digest. The driver does not treat this
    /// file as proof that the OS actually enforced cgroups/device ACLs.
    pub device_descriptor_path: PathBuf,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalProcessDriverConfig {
    pub runtime_executable: PathBuf,
    pub models: BTreeMap<String, LocalModelArtifacts>,
    pub maximum_protocol_line_bytes: usize,
    pub shutdown_timeout: Duration,
}

impl LocalProcessDriverConfig {
    pub fn new(
        runtime_executable: PathBuf,
        models: BTreeMap<String, LocalModelArtifacts>,
    ) -> Self {
        Self {
            runtime_executable,
            models,
            maximum_protocol_line_bytes: DEFAULT_MAX_PROTOCOL_LINE_BYTES,
            shutdown_timeout: DEFAULT_SHUTDOWN_TIMEOUT,
        }
    }
}

pub struct LocalProcessDriver {
    config: LocalProcessDriverConfig,
    runtime_executable: PathBuf,
    processes: BTreeMap<String, RuntimeProcess>,
}

struct VerifiedArtifacts {
    weights: PathBuf,
    tokenizer: PathBuf,
    preprocessor: PathBuf,
    quantization: PathBuf,
    device_descriptor: PathBuf,
}

struct RuntimeProcess {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    reserved_memory_bytes: u64,
    observed_memory_bytes: u64,
}

impl RuntimeProcess {
    fn terminate(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for RuntimeProcess {
    fn drop(&mut self) {
        self.terminate();
    }
}

impl LocalProcessDriver {
    pub fn new(config: LocalProcessDriverConfig) -> Result<Self, Error> {
        if config.maximum_protocol_line_bytes == 0
            || config.maximum_protocol_line_bytes > HARD_MAX_PROTOCOL_LINE_BYTES
            || config.shutdown_timeout.is_zero()
            || config.shutdown_timeout > Duration::from_secs(30)
        {
            return Err(driver_error("invalid local runtime bounds"));
        }
        let runtime_executable =
            verify_regular_file(&config.runtime_executable, None, "runtime executable")?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if fs::metadata(&runtime_executable)
                .map_err(io_error)?
                .permissions()
                .mode()
                & 0o111
                == 0
            {
                return Err(driver_error("local runtime is not executable"));
            }
        }
        for (model_id, artifacts) in &config.models {
            validate_local_id(model_id, "configured model")?;
            for (path, label) in [
                (&artifacts.weights_path, "weights"),
                (&artifacts.tokenizer_path, "tokenizer"),
                (&artifacts.preprocessor_path, "preprocessor"),
                (&artifacts.quantization_path, "quantization"),
                (&artifacts.device_descriptor_path, "device descriptor"),
            ] {
                if !path.is_absolute() {
                    return Err(driver_error(format!("{label} path must be absolute")));
                }
            }
        }
        Ok(Self {
            config,
            runtime_executable,
            processes: BTreeMap::new(),
        })
    }

    fn verify_manifest_artifacts(
        &self,
        manifest: &ModelManifest,
    ) -> Result<VerifiedArtifacts, Error> {
        if sha256_file(&self.runtime_executable)? != manifest.runtime_digest {
            return Err(driver_error("runtime executable digest mismatch"));
        }
        let configured = self
            .config
            .models
            .get(&manifest.model_id)
            .ok_or_else(|| driver_error("model has no configured local artifact set"))?;
        Ok(VerifiedArtifacts {
            weights: verify_regular_file(
                &configured.weights_path,
                Some(&manifest.weights_digest),
                "weights",
            )?,
            tokenizer: verify_regular_file(
                &configured.tokenizer_path,
                Some(&manifest.tokenizer_digest),
                "tokenizer",
            )?,
            preprocessor: verify_regular_file(
                &configured.preprocessor_path,
                Some(&manifest.preprocessor_digest),
                "preprocessor",
            )?,
            quantization: verify_regular_file(
                &configured.quantization_path,
                Some(&manifest.quantization_digest),
                "quantization",
            )?,
            device_descriptor: verify_regular_file(
                &configured.device_descriptor_path,
                Some(&manifest.device_digest),
                "device descriptor",
            )?,
        })
    }

    fn spawn_runtime(&self) -> Result<RuntimeProcess, Error> {
        let mut child = Command::new(&self.runtime_executable)
            .arg("--hepta-local-model-worker-v1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(io_error)?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| driver_error("local runtime stdin unavailable"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| driver_error("local runtime stdout unavailable"))?;
        Ok(RuntimeProcess {
            child,
            stdin,
            stdout: BufReader::new(stdout),
            reserved_memory_bytes: 0,
            observed_memory_bytes: 0,
        })
    }

    fn verify_artifacts_unchanged(
        &self,
        manifest: &ModelManifest,
        artifacts: &VerifiedArtifacts,
    ) -> Result<(), Error> {
        for (path, digest, label) in [
            (&self.runtime_executable, &manifest.runtime_digest, "runtime"),
            (&artifacts.weights, &manifest.weights_digest, "weights"),
            (
                &artifacts.tokenizer,
                &manifest.tokenizer_digest,
                "tokenizer",
            ),
            (
                &artifacts.preprocessor,
                &manifest.preprocessor_digest,
                "preprocessor",
            ),
            (
                &artifacts.quantization,
                &manifest.quantization_digest,
                "quantization",
            ),
            (
                &artifacts.device_descriptor,
                &manifest.device_digest,
                "device descriptor",
            ),
        ] {
            if sha256_file(path)? != *digest {
                return Err(driver_error(format!(
                    "{label} changed during local model load"
                )));
            }
        }
        Ok(())
    }

    fn shutdown_after_ack(&self, process: &mut RuntimeProcess) -> Result<(), Error> {
        let deadline = Instant::now() + self.config.shutdown_timeout;
        loop {
            match process.child.try_wait().map_err(io_error)? {
                Some(status) if status.success() => return Ok(()),
                Some(status) => {
                    return Err(driver_error(format!(
                        "local runtime exited unsuccessfully after unload: {status}"
                    )));
                }
                None if Instant::now() >= deadline => {
                    process.terminate();
                    return Err(driver_error(
                        "local runtime did not exit within the unload deadline",
                    ));
                }
                None => thread::sleep(Duration::from_millis(10)),
            }
        }
    }
}

impl ModelDriver for LocalProcessDriver {
    fn load(
        &mut self,
        manifest: &ModelManifest,
        grant: &ResourceGrant,
    ) -> Result<DriverModelHandle, Error> {
        let artifacts = self.verify_manifest_artifacts(manifest)?;
        let mut process = self.spawn_runtime()?;
        let request = json!({
            "protocol": LOCAL_RUNTIME_PROTOCOL,
            "op": "load",
            "model": {
                "model_id": manifest.model_id,
                "model_digest": manifest.model_digest,
                "weights_path": utf8_path(&artifacts.weights, "weights")?,
                "weights_digest": manifest.weights_digest,
                "tokenizer_path": utf8_path(&artifacts.tokenizer, "tokenizer")?,
                "tokenizer_digest": manifest.tokenizer_digest,
                "preprocessor_path": utf8_path(&artifacts.preprocessor, "preprocessor")?,
                "preprocessor_digest": manifest.preprocessor_digest,
                "quantization_path": utf8_path(&artifacts.quantization, "quantization")?,
                "quantization_digest": manifest.quantization_digest,
                "device_descriptor_path": utf8_path(
                    &artifacts.device_descriptor,
                    "device descriptor",
                )?,
                "device_digest": manifest.device_digest,
                "runtime_digest": manifest.runtime_digest,
                "maximum_tokens": manifest.maximum_tokens,
            },
            "grant": {
                "grant_id": grant.grant_id,
                "authority_epoch": grant.authority_epoch,
                "generation": grant.generation,
                "maximum_memory_bytes": grant.maximum_memory_bytes,
                "semantic_digest": grant.semantic_digest,
            }
        });
        if let Err(error) = write_message(&mut process.stdin, &request) {
            process.terminate();
            return Err(error);
        }
        let response =
            match read_message(&mut process.stdout, self.config.maximum_protocol_line_bytes) {
                Ok(response) => response,
                Err(error) => {
                    process.terminate();
                    return Err(error);
                }
            };
        require_string(&response, "protocol", LOCAL_RUNTIME_PROTOCOL)?;
        require_string(&response, "op", "loaded")?;
        require_string(&response, "model_id", &manifest.model_id)?;
        require_string(&response, "model_digest", &manifest.model_digest)?;
        require_string(&response, "runtime_digest", &manifest.runtime_digest)?;
        require_string(&response, "device_digest", &manifest.device_digest)?;
        let handle_id = string_field(&response, "handle_id")?.to_string();
        validate_local_id(&handle_id, "model handle")?;
        if self.processes.contains_key(&handle_id) {
            process.terminate();
            return Err(driver_error("local runtime reused a live model handle"));
        }
        let reserved_memory_bytes = u64_field(&response, "reserved_memory_bytes")?;
        let observed_memory_bytes = u64_field(&response, "observed_memory_bytes")?;
        if reserved_memory_bytes == 0
            || reserved_memory_bytes > grant.maximum_memory_bytes
            || observed_memory_bytes > reserved_memory_bytes
        {
            process.terminate();
            return Err(Error::ModelCapacity);
        }
        if process.child.try_wait().map_err(io_error)?.is_some() {
            process.terminate();
            return Err(driver_error(
                "local runtime exited before the model became usable",
            ));
        }
        if let Err(error) = self.verify_artifacts_unchanged(manifest, &artifacts) {
            process.terminate();
            return Err(error);
        }
        process.reserved_memory_bytes = reserved_memory_bytes;
        process.observed_memory_bytes = observed_memory_bytes;
        self.processes.insert(handle_id.clone(), process);
        Ok(DriverModelHandle {
            opaque_id: handle_id,
            reserved_memory_bytes,
            observed_memory_bytes,
        })
    }

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        let process = self
            .processes
            .get_mut(&handle.opaque_id)
            .ok_or(Error::ModelNotLoaded)?;
        if process.child.try_wait().map_err(io_error)?.is_some() {
            return Ok(indeterminate(process.observed_memory_bytes));
        }
        let message = json!({
            "protocol": LOCAL_RUNTIME_PROTOCOL,
            "op": "run",
            "handle_id": handle.opaque_id,
            "request_id": request.request_id,
            "reservation_id": request.reservation_id,
            "model_digest": request.model_digest,
            "payload_digest": request.payload_digest,
            "input": request.input,
            "maximum_tokens": request.maximum_tokens,
            "deadline_ms": request.deadline_ms,
        });
        // Once a request write begins, an I/O failure is conservatively treated
        // as an unknown execution, never as permission to replay.
        if write_message(&mut process.stdin, &message).is_err() {
            process.terminate();
            return Ok(indeterminate(process.observed_memory_bytes));
        }
        let response =
            match read_message(&mut process.stdout, self.config.maximum_protocol_line_bytes) {
                Ok(response) => response,
                Err(_) => {
                    process.terminate();
                    return Ok(indeterminate(process.observed_memory_bytes));
                }
            };
        if require_string(&response, "protocol", LOCAL_RUNTIME_PROTOCOL).is_err()
            || require_string(&response, "op", "run_result").is_err()
            || require_string(&response, "handle_id", &handle.opaque_id).is_err()
            || require_string(&response, "request_id", &request.request_id).is_err()
        {
            process.terminate();
            return Ok(indeterminate(process.observed_memory_bytes));
        }
        let terminal_observed = match bool_field(&response, "terminal_observed") {
            Ok(value) => value,
            Err(_) => {
                process.terminate();
                return Ok(indeterminate(process.observed_memory_bytes));
            }
        };
        let succeeded = match bool_field(&response, "succeeded") {
            Ok(value) => value,
            Err(_) => {
                process.terminate();
                return Ok(indeterminate(process.observed_memory_bytes));
            }
        };
        let observed_memory_bytes = match u64_field(&response, "observed_memory_bytes") {
            Ok(value) => value,
            Err(_) => {
                process.terminate();
                return Ok(indeterminate(process.observed_memory_bytes));
            }
        };
        if observed_memory_bytes > process.reserved_memory_bytes {
            process.terminate();
            return Err(Error::ModelCapacity);
        }
        process.observed_memory_bytes = observed_memory_bytes;
        let consumed_tokens = match optional_u32_field(&response, "consumed_tokens") {
            Ok(value) => value,
            Err(_) => {
                process.terminate();
                return Ok(indeterminate(observed_memory_bytes));
            }
        };
        if !terminal_observed {
            return Ok(DriverRunObservation {
                terminal_observed: false,
                succeeded: false,
                output_digest: None,
                consumed_tokens,
                observed_memory_bytes,
            });
        }
        let output = optional_string_field(&response, "output")?;
        if output.as_ref().is_some_and(|value| value.len() > MAX_OUTPUT_BYTES) {
            process.terminate();
            return Err(driver_error("local runtime output byte limit exceeded"));
        }
        let output_digest = output.map(|value| sha256(value.as_bytes()));
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded,
            output_digest,
            consumed_tokens,
            observed_memory_bytes,
        })
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        let mut process = self
            .processes
            .remove(&handle.opaque_id)
            .ok_or(Error::ModelNotLoaded)?;
        let request = json!({
            "protocol": LOCAL_RUNTIME_PROTOCOL,
            "op": "unload",
            "handle_id": handle.opaque_id,
        });
        if let Err(error) = write_message(&mut process.stdin, &request) {
            process.terminate();
            return Err(error);
        }
        let response =
            match read_message(&mut process.stdout, self.config.maximum_protocol_line_bytes) {
                Ok(response) => response,
                Err(error) => {
                    process.terminate();
                    return Err(error);
                }
            };
        if require_string(&response, "protocol", LOCAL_RUNTIME_PROTOCOL).is_err()
            || require_string(&response, "op", "unloaded").is_err()
            || require_string(&response, "handle_id", &handle.opaque_id).is_err()
        {
            process.terminate();
            return Err(driver_error("local runtime unload acknowledgement mismatch"));
        }
        self.shutdown_after_ack(&mut process)
    }
}

fn indeterminate(observed_memory_bytes: u64) -> DriverRunObservation {
    DriverRunObservation {
        terminal_observed: false,
        succeeded: false,
        output_digest: None,
        consumed_tokens: None,
        observed_memory_bytes,
    }
}

fn write_message(stdin: &mut ChildStdin, value: &Value) -> Result<(), Error> {
    let mut bytes = serde_json::to_vec(value)
        .map_err(|error| driver_error(format!("local runtime request encode failed: {error}")))?;
    bytes.push(b'\n');
    stdin.write_all(&bytes).map_err(io_error)?;
    stdin.flush().map_err(io_error)
}

fn read_message(stdout: &mut BufReader<ChildStdout>, maximum_bytes: usize) -> Result<Value, Error> {
    let mut line = String::new();
    let read = stdout
        .take(u64::try_from(maximum_bytes).unwrap_or(u64::MAX) + 1)
        .read_line(&mut line)
        .map_err(io_error)?;
    if read == 0 {
        return Err(driver_error("local runtime closed its protocol stream"));
    }
    if read > maximum_bytes || !line.ends_with('\n') {
        return Err(driver_error("local runtime protocol line exceeded its bound"));
    }
    serde_json::from_str(&line)
        .map_err(|error| driver_error(format!("local runtime returned invalid JSON: {error}")))
}

fn verify_regular_file(
    path: &Path,
    expected_digest: Option<&str>,
    label: &str,
) -> Result<PathBuf, Error> {
    if !path.is_absolute() {
        return Err(driver_error(format!("{label} path must be absolute")));
    }
    let metadata = fs::symlink_metadata(path).map_err(io_error)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(driver_error(format!("{label} must be a regular non-symlink file")));
    }
    let canonical = fs::canonicalize(path).map_err(io_error)?;
    if let Some(expected) = expected_digest
        && sha256_file(&canonical)? != expected
    {
        return Err(driver_error(format!("{label} digest mismatch")));
    }
    Ok(canonical)
}

fn sha256_file(path: &Path) -> Result<String, Error> {
    let mut file = File::open(path).map_err(io_error)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer).map_err(io_error)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn require_string(value: &Value, field: &str, expected: &str) -> Result<(), Error> {
    if string_field(value, field)? != expected {
        return Err(driver_error(format!(
            "local runtime field {field} did not match the request"
        )));
    }
    Ok(())
}

fn string_field<'a>(value: &'a Value, field: &str) -> Result<&'a str, Error> {
    value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| driver_error(format!("local runtime field {field} is missing")))
}

fn optional_string_field(value: &Value, field: &str) -> Result<Option<String>, Error> {
    match value.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(_) => Err(driver_error(format!(
            "local runtime field {field} is not a string"
        ))),
    }
}

fn bool_field(value: &Value, field: &str) -> Result<bool, Error> {
    value
        .get(field)
        .and_then(Value::as_bool)
        .ok_or_else(|| driver_error(format!("local runtime field {field} is missing")))
}

fn u64_field(value: &Value, field: &str) -> Result<u64, Error> {
    value
        .get(field)
        .and_then(Value::as_u64)
        .ok_or_else(|| driver_error(format!("local runtime field {field} is missing")))
}

fn optional_u32_field(value: &Value, field: &str) -> Result<Option<u32>, Error> {
    match value.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(value) => {
            let value = value
                .as_u64()
                .ok_or_else(|| driver_error(format!("local runtime field {field} is invalid")))?;
            let value = u32::try_from(value)
                .map_err(|_| driver_error(format!("local runtime field {field} overflowed")))?;
            Ok(Some(value))
        }
    }
}

fn utf8_path<'a>(path: &'a Path, label: &str) -> Result<&'a str, Error> {
    path.to_str()
        .ok_or_else(|| driver_error(format!("{label} path is not valid UTF-8")))
}

fn validate_local_id(value: &str, label: &str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(driver_error(format!("{label} identity is invalid")));
    }
    Ok(())
}

fn io_error(error: std::io::Error) -> Error {
    driver_error(format!("local runtime I/O failed: {error}"))
}

fn driver_error(message: impl Into<String>) -> Error {
    Error::DriverFailure(message.into())
}

#[cfg(test)]
#[path = "local_process_driver_tests.rs"]
mod tests;
