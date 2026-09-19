//! Production adapter for a locally installed model runtime process.
//!
//! The driver verifies every configured artifact before process creation, then
//! speaks one strict JSON-lines protocol with a long-lived child process. The
//! runtime process is responsible for the physical model/device implementation;
//! this adapter binds its acknowledgement to the exact manifest, resource grant
//! and OS process id. Host-level cgroup/namespace/seccomp/device ACL enforcement
//! remains a deployment responsibility and is intentionally not fabricated here.

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
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;
use sha2::Digest;
use sha2::Sha256;

use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelDriver;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;
use crate::model_worker::WorkerRequest;

const PROTOCOL: &str = "hepta.local-model-runtime.v1";
const MAX_RUNTIME_MESSAGE_BYTES: usize = 32 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalModelSpec {
    pub weights_path: PathBuf,
    pub tokenizer_path: PathBuf,
    pub preprocessor_path: PathBuf,
    pub quantization_path: PathBuf,
    pub license_path: PathBuf,
    pub sbom_path: PathBuf,
    pub runtime_path: PathBuf,
    pub device_descriptor_path: PathBuf,
    pub runtime_args: Vec<String>,
    /// Explicit environment for the model runtime. The inherited environment
    /// is cleared so ambient credentials/device selectors are not authority.
    pub runtime_env: BTreeMap<String, String>,
}

#[derive(Debug)]
pub struct LocalProcessModelDriver {
    specs: BTreeMap<String, LocalModelSpec>,
    sessions: BTreeMap<String, RuntimeSession>,
    io_timeout: Duration,
}

#[derive(Debug)]
struct RuntimeSession {
    child: Child,
    stdin: Arc<Mutex<ChildStdin>>,
    stdout: Arc<Mutex<BufReader<ChildStdout>>>,
    model_id: String,
    handle_id: String,
    reserved_memory_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ArtifactBinding {
    model_digest: String,
    weights_digest: String,
    tokenizer_digest: String,
    preprocessor_digest: String,
    quantization_digest: String,
    license_digest: String,
    sbom_digest: String,
    runtime_digest: String,
    runtime_config_digest: String,
    device_digest: String,
}

impl ArtifactBinding {
    fn from_manifest(manifest: &ModelManifest) -> Self {
        Self {
            model_digest: manifest.model_digest.clone(),
            weights_digest: manifest.weights_digest.clone(),
            tokenizer_digest: manifest.tokenizer_digest.clone(),
            preprocessor_digest: manifest.preprocessor_digest.clone(),
            quantization_digest: manifest.quantization_digest.clone(),
            license_digest: manifest.license_digest.clone(),
            sbom_digest: manifest.sbom_digest.clone(),
            runtime_digest: manifest.runtime_digest.clone(),
            runtime_config_digest: manifest.runtime_config_digest.clone(),
            device_digest: manifest.device_digest.clone(),
        }
    }
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
struct ArtifactPaths {
    weights: String,
    tokenizer: String,
    preprocessor: String,
    quantization: String,
    license: String,
    sbom: String,
    runtime: String,
    device_descriptor: String,
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
struct LoadRequest {
    protocol: &'static str,
    operation: &'static str,
    model_id: String,
    binding: ArtifactBinding,
    paths: ArtifactPaths,
    maximum_tokens: u32,
    grant_id: String,
    authority_epoch: u64,
    worker_generation: u64,
    grant_semantic_digest: String,
    maximum_memory_bytes: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LoadResponse {
    protocol: String,
    operation: String,
    ok: bool,
    model_id: String,
    handle_id: String,
    process_id: u32,
    binding: ArtifactBinding,
    reserved_memory_bytes: u64,
    error: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
struct InferRequest {
    protocol: &'static str,
    operation: &'static str,
    model_id: String,
    handle_id: String,
    request_id: String,
    payload: String,
    maximum_tokens: u32,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct InferResponse {
    protocol: String,
    operation: String,
    request_id: String,
    handle_id: String,
    terminal_observed: bool,
    succeeded: bool,
    output: Option<String>,
    consumed_tokens: u32,
    observed_memory_bytes: u64,
    error: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
struct UnloadRequest {
    protocol: &'static str,
    operation: &'static str,
    model_id: String,
    handle_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct UnloadResponse {
    protocol: String,
    operation: String,
    ok: bool,
    handle_id: String,
    error: Option<String>,
}

impl LocalProcessModelDriver {
    pub fn new(
        specs: BTreeMap<String, LocalModelSpec>,
        io_timeout: Duration,
    ) -> Result<Self, Error> {
        if specs.is_empty()
            || io_timeout.is_zero()
            || io_timeout > Duration::from_secs(3600)
        {
            return Err(Error::DriverFailure(
                "invalid local process driver configuration".to_string(),
            ));
        }
        for (model_id, spec) in &specs {
            validate_config_identity(model_id, "model")?;
            validate_spec_paths(spec)?;
        }
        Ok(Self {
            specs,
            sessions: BTreeMap::new(),
            io_timeout,
        })
    }

    fn available_memory(&self, grant: &ResourceGrant) -> Result<u64, Error> {
        let used = self.sessions.values().try_fold(0_u64, |sum, session| {
            sum.checked_add(session.reserved_memory_bytes)
                .ok_or(Error::ArithmeticOverflow)
        })?;
        grant
            .maximum_memory_bytes
            .checked_sub(used)
            .ok_or(Error::ModelCapacity)
    }
}

impl ModelDriver for LocalProcessModelDriver {
    fn load(
        &mut self,
        manifest: &ModelManifest,
        grant: &ResourceGrant,
    ) -> Result<DriverModelHandle, Error> {
        if self.sessions.values().any(|session| session.model_id == manifest.model_id) {
            return Err(Error::ModelAlreadyLoaded);
        }
        if manifest.device_digest != grant.device_digest {
            return Err(Error::ResourceMismatch("device"));
        }

        let spec = self
            .specs
            .get(&manifest.model_id)
            .ok_or_else(|| Error::DriverFailure("no registered local model spec".to_string()))?
            .clone();
        verify_spec(&spec, manifest)?;
        let available_memory = self.available_memory(grant)?;
        if available_memory == 0 {
            return Err(Error::ModelCapacity);
        }

        let mut child = Command::new(&spec.runtime_path)
            .args(&spec.runtime_args)
            .env_clear()
            .envs(&spec.runtime_env)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| driver_error("spawn runtime", error))?;
        let process_id = child.id();
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| Error::DriverFailure("runtime stdin unavailable".to_string()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| Error::DriverFailure("runtime stdout unavailable".to_string()))?;
        let mut session = RuntimeSession {
            child,
            stdin: Arc::new(Mutex::new(stdin)),
            stdout: Arc::new(Mutex::new(BufReader::new(stdout))),
            model_id: manifest.model_id.clone(),
            handle_id: String::new(),
            reserved_memory_bytes: 0,
        };

        let request = LoadRequest {
            protocol: PROTOCOL,
            operation: "load",
            model_id: manifest.model_id.clone(),
            binding: ArtifactBinding::from_manifest(manifest),
            paths: artifact_paths(&spec)?,
            maximum_tokens: manifest.maximum_tokens,
            grant_id: grant.grant_id.clone(),
            authority_epoch: grant.authority_epoch,
            worker_generation: grant.generation,
            grant_semantic_digest: grant.semantic_digest.clone(),
            maximum_memory_bytes: available_memory,
        };
        let response: LoadResponse = match exchange(&mut session, &request, self.io_timeout) {
            Ok(response) => response,
            Err(error) => {
                terminate(&mut session);
                return Err(error);
            }
        };

        let expected_binding = ArtifactBinding::from_manifest(manifest);
        if response.protocol != PROTOCOL
            || response.operation != "load_result"
            || !response.ok
            || response.model_id != manifest.model_id
            || response.process_id != process_id
            || response.binding != expected_binding
            || response.handle_id.is_empty()
            || response.handle_id.len() > 128
            || response.reserved_memory_bytes == 0
            || response.reserved_memory_bytes > available_memory
        {
            let detail = response
                .error
                .unwrap_or_else(|| "runtime load acknowledgement mismatch".to_string());
            terminate(&mut session);
            return Err(Error::DriverFailure(detail));
        }
        validate_config_identity(&response.handle_id, "runtime handle")?;
        if self.sessions.contains_key(&response.handle_id) {
            terminate(&mut session);
            return Err(Error::DriverFailure(
                "runtime reused an active handle id".to_string(),
            ));
        }

        session.handle_id = response.handle_id.clone();
        session.reserved_memory_bytes = response.reserved_memory_bytes;
        let handle = DriverModelHandle {
            opaque_id: response.handle_id.clone(),
            observed_memory_bytes: response.reserved_memory_bytes,
        };
        self.sessions.insert(response.handle_id, session);
        Ok(handle)
    }

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        let session = self
            .sessions
            .get_mut(&handle.opaque_id)
            .ok_or(Error::ModelNotLoaded)?;
        if session.handle_id != handle.opaque_id {
            return Err(Error::DriverFailure(
                "local runtime handle binding changed".to_string(),
            ));
        }
        let wire_request = InferRequest {
            protocol: PROTOCOL,
            operation: "infer",
            model_id: session.model_id.clone(),
            handle_id: handle.opaque_id.clone(),
            request_id: request.request_id.clone(),
            payload: request.payload.clone(),
            maximum_tokens: request.maximum_tokens,
        };
        let response: InferResponse = match exchange(session, &wire_request, self.io_timeout) {
            Ok(response) => response,
            Err(error) => {
                terminate(session);
                return Err(error);
            }
        };
        if response.protocol != PROTOCOL
            || response.operation != "infer_result"
            || response.request_id != request.request_id
            || response.handle_id != handle.opaque_id
        {
            terminate(session);
            return Err(Error::DriverFailure(
                "runtime inference acknowledgement mismatch".to_string(),
            ));
        }
        if response.error.is_some() && response.succeeded {
            terminate(session);
            return Err(Error::DriverFailure(
                "runtime reported success with an error".to_string(),
            ));
        }
        Ok(DriverRunObservation {
            terminal_observed: response.terminal_observed,
            succeeded: response.succeeded,
            output: response.output,
            consumed_tokens: response.consumed_tokens,
            observed_memory_bytes: response.observed_memory_bytes,
        })
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        let mut session = self
            .sessions
            .remove(&handle.opaque_id)
            .ok_or(Error::ModelNotLoaded)?;
        let request = UnloadRequest {
            protocol: PROTOCOL,
            operation: "unload",
            model_id: session.model_id.clone(),
            handle_id: handle.opaque_id.clone(),
        };
        let response: UnloadResponse = match exchange(&mut session, &request, self.io_timeout) {
            Ok(response) => response,
            Err(error) => {
                terminate(&mut session);
                return Err(error);
            }
        };
        let valid = response.protocol == PROTOCOL
            && response.operation == "unload_result"
            && response.ok
            && response.handle_id == handle.opaque_id;
        let detail = response.error;
        terminate(&mut session);
        if !valid {
            return Err(Error::DriverFailure(
                detail.unwrap_or_else(|| "runtime unload acknowledgement mismatch".to_string()),
            ));
        }
        Ok(())
    }
}

impl Drop for LocalProcessModelDriver {
    fn drop(&mut self) {
        for session in self.sessions.values_mut() {
            terminate(session);
        }
    }
}

fn verify_spec(spec: &LocalModelSpec, manifest: &ModelManifest) -> Result<(), Error> {
    verify_file_digest(&spec.weights_path, &manifest.weights_digest, false)?;
    verify_file_digest(&spec.tokenizer_path, &manifest.tokenizer_digest, false)?;
    verify_file_digest(
        &spec.preprocessor_path,
        &manifest.preprocessor_digest,
        false,
    )?;
    verify_file_digest(
        &spec.quantization_path,
        &manifest.quantization_digest,
        false,
    )?;
    verify_file_digest(&spec.license_path, &manifest.license_digest, false)?;
    verify_file_digest(&spec.sbom_path, &manifest.sbom_digest, false)?;
    verify_file_digest(&spec.runtime_path, &manifest.runtime_digest, true)?;
    if runtime_config_digest(spec) != manifest.runtime_config_digest {
        return Err(Error::DriverFailure(
            "local runtime launch configuration digest mismatch".to_string(),
        ));
    }
    verify_file_digest(
        &spec.device_descriptor_path,
        &manifest.device_digest,
        false,
    )?;
    Ok(())
}

fn verify_file_digest(path: &Path, expected: &str, executable: bool) -> Result<(), Error> {
    if !path.is_absolute() {
        return Err(Error::DriverFailure(
            "local model artifact path must be absolute".to_string(),
        ));
    }
    let metadata = fs::symlink_metadata(path).map_err(|error| driver_error("artifact metadata", error))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(Error::DriverFailure(
            "local model artifact must be a regular non-symlink file".to_string(),
        ));
    }
    #[cfg(unix)]
    if executable {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o111 == 0 {
            return Err(Error::DriverFailure(
                "local model runtime is not executable".to_string(),
            ));
        }
    }
    #[cfg(not(unix))]
    let _ = executable;

    let mut file = File::open(path).map_err(|error| driver_error("open artifact", error))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| driver_error("read artifact", error))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    let actual = format!("{:x}", hasher.finalize());
    if actual != expected {
        return Err(Error::DriverFailure(format!(
            "artifact digest mismatch for {}",
            path.display()
        )));
    }
    Ok(())
}

fn validate_spec_paths(spec: &LocalModelSpec) -> Result<(), Error> {
    for path in [
        &spec.weights_path,
        &spec.tokenizer_path,
        &spec.preprocessor_path,
        &spec.quantization_path,
        &spec.license_path,
        &spec.sbom_path,
        &spec.runtime_path,
        &spec.device_descriptor_path,
    ] {
        if !path.is_absolute() {
            return Err(Error::DriverFailure(
                "all local model paths must be absolute".to_string(),
            ));
        }
    }
    if spec.runtime_args.len() > 64
        || spec.runtime_args.iter().any(|arg| {
            arg.len() > 4096
                || arg.bytes().any(|byte| matches!(byte, 0 | b'\n' | b'\r'))
                || arg.contains('/')
                || arg.contains('\\')
        })
        || spec.runtime_env.len() > 64
        || spec.runtime_env.iter().any(|(key, value)| {
            !safe_runtime_env_key(key)
                || value.len() > 8192
                || value.bytes().any(|byte| matches!(byte, 0 | b'\n' | b'\r'))
                || value.contains('/')
                || value.contains('\\')
        })
    {
        return Err(Error::DriverFailure(
            "local runtime launch configuration exceeds bounds or references unverified paths"
                .to_string(),
        ));
    }
    Ok(())
}

fn safe_runtime_env_key(key: &str) -> bool {
    matches!(
        key,
        "CUDA_VISIBLE_DEVICES"
            | "CUDA_DEVICE_ORDER"
            | "ROCR_VISIBLE_DEVICES"
            | "HIP_VISIBLE_DEVICES"
            | "OMP_NUM_THREADS"
            | "TOKENIZERS_PARALLELISM"
            | "RAYON_NUM_THREADS"
            | "HEPTA_RUNTIME_MODE"
    )
}

fn runtime_config_digest(spec: &LocalModelSpec) -> String {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.local-runtime-config.v1");
    push_runtime_string(&mut bytes, &spec.runtime_args.len().to_string());
    for arg in &spec.runtime_args {
        push_runtime_string(&mut bytes, arg);
    }
    push_runtime_string(&mut bytes, &spec.runtime_env.len().to_string());
    for (key, value) in &spec.runtime_env {
        push_runtime_string(&mut bytes, key);
        push_runtime_string(&mut bytes, value);
    }
    format!("{:x}", Sha256::digest(&bytes))
}

fn push_runtime_string(bytes: &mut Vec<u8>, value: &str) {
    let len = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn artifact_paths(spec: &LocalModelSpec) -> Result<ArtifactPaths, Error> {
    Ok(ArtifactPaths {
        weights: path_string(&spec.weights_path)?,
        tokenizer: path_string(&spec.tokenizer_path)?,
        preprocessor: path_string(&spec.preprocessor_path)?,
        quantization: path_string(&spec.quantization_path)?,
        license: path_string(&spec.license_path)?,
        sbom: path_string(&spec.sbom_path)?,
        runtime: path_string(&spec.runtime_path)?,
        device_descriptor: path_string(&spec.device_descriptor_path)?,
    })
}

fn path_string(path: &Path) -> Result<String, Error> {
    path.to_str()
        .map(str::to_string)
        .ok_or_else(|| Error::DriverFailure("local model path is not UTF-8".to_string()))
}

fn exchange<T: Serialize, R: DeserializeOwned>(
    session: &mut RuntimeSession,
    request: &T,
    timeout: Duration,
) -> Result<R, Error> {
    let mut encoded = serde_json::to_vec(request)
        .map_err(|error| Error::DriverFailure(format!("encode runtime request: {error}")))?;
    if encoded.len() + 1 > MAX_RUNTIME_MESSAGE_BYTES {
        return Err(Error::DriverFailure(
            "runtime request exceeds protocol bound".to_string(),
        ));
    }
    encoded.push(b'\n');
    write_with_timeout(Arc::clone(&session.stdin), encoded, timeout)?;
    let line = read_with_timeout(Arc::clone(&session.stdout), timeout)?;
    serde_json::from_slice(&line)
        .map_err(|error| Error::DriverFailure(format!("decode runtime response: {error}")))
}

fn write_with_timeout(
    stdin: Arc<Mutex<ChildStdin>>,
    bytes: Vec<u8>,
    timeout: Duration,
) -> Result<(), Error> {
    let (sender, receiver) = mpsc::sync_channel(1);
    thread::spawn(move || {
        let result = stdin
            .lock()
            .map_err(|_| "runtime stdin lock poisoned".to_string())
            .and_then(|mut stdin| {
                stdin
                    .write_all(&bytes)
                    .and_then(|()| stdin.flush())
                    .map_err(|error| error.to_string())
            });
        let _ = sender.send(result);
    });
    match receiver.recv_timeout(timeout) {
        Ok(Ok(())) => Ok(()),
        Ok(Err(error)) => Err(Error::DriverFailure(format!(
            "runtime write failed: {error}"
        ))),
        Err(mpsc::RecvTimeoutError::Timeout) => Err(Error::DriverFailure(
            "runtime write timed out".to_string(),
        )),
        Err(mpsc::RecvTimeoutError::Disconnected) => Err(Error::DriverFailure(
            "runtime write worker disconnected".to_string(),
        )),
    }
}

fn read_with_timeout(
    stdout: Arc<Mutex<BufReader<ChildStdout>>>,
    timeout: Duration,
) -> Result<Vec<u8>, Error> {
    let (sender, receiver) = mpsc::sync_channel(1);
    thread::spawn(move || {
        let result = stdout
            .lock()
            .map_err(|_| "runtime stdout lock poisoned".to_string())
            .and_then(|mut stdout| bounded_read_line(&mut stdout).map_err(|error| error.to_string()));
        let _ = sender.send(result);
    });
    match receiver.recv_timeout(timeout) {
        Ok(Ok(line)) => Ok(line),
        Ok(Err(error)) => Err(Error::DriverFailure(format!(
            "runtime read failed: {error}"
        ))),
        Err(mpsc::RecvTimeoutError::Timeout) => Err(Error::DriverFailure(
            "runtime read timed out".to_string(),
        )),
        Err(mpsc::RecvTimeoutError::Disconnected) => Err(Error::DriverFailure(
            "runtime read worker disconnected".to_string(),
        )),
    }
}

fn bounded_read_line<R: BufRead>(reader: &mut R) -> std::io::Result<Vec<u8>> {
    let mut output = Vec::new();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::UnexpectedEof,
                "runtime closed stdout",
            ));
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let count = newline.map_or(available.len(), |index| index + 1);
        if output.len().saturating_add(count) > MAX_RUNTIME_MESSAGE_BYTES {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "runtime response exceeds protocol bound",
            ));
        }
        let chunk = available[..count].to_vec();
        reader.consume(count);
        output.extend_from_slice(&chunk);
        if newline.is_some() {
            output.pop();
            return Ok(output);
        }
    }
}

fn terminate(session: &mut RuntimeSession) {
    let _ = session.child.kill();
    let _ = session.child.wait();
}

fn validate_config_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

fn driver_error(context: &str, error: impl std::fmt::Display) -> Error {
    Error::DriverFailure(format!("{context}: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    fn temp_file(label: &str, bytes: &[u8]) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "hepta-local-driver-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::write(&path, bytes).expect("write fixture");
        path
    }

    #[test]
    fn exact_artifact_digest_is_required() {
        let path = temp_file("digest", b"verified weights");
        let digest = format!("{:x}", Sha256::digest(b"verified weights"));
        verify_file_digest(&path, &digest, false).expect("verified");
        assert!(verify_file_digest(&path, &"f".repeat(64), false).is_err());
        fs::remove_file(path).expect("cleanup");
    }

    #[test]
    fn runtime_lines_are_bounded_and_exact() {
        let mut input = BufReader::new(&b"{\"ok\":true}\ntrailing"[..]);
        assert_eq!(
            bounded_read_line(&mut input).expect("line"),
            b"{\"ok\":true}".to_vec()
        );
    }

    #[test]
    fn launch_configuration_is_digest_bound_and_injection_keys_are_denied() {
        let path = temp_file("launch-config", b"artifact");
        let mut spec = LocalModelSpec {
            weights_path: path.clone(),
            tokenizer_path: path.clone(),
            preprocessor_path: path.clone(),
            quantization_path: path.clone(),
            license_path: path.clone(),
            sbom_path: path.clone(),
            runtime_path: path.clone(),
            device_descriptor_path: path.clone(),
            runtime_args: vec!["--device=cuda0".to_string()],
            runtime_env: BTreeMap::from([(
                "CUDA_VISIBLE_DEVICES".to_string(),
                "0".to_string(),
            )]),
        };
        let first = runtime_config_digest(&spec);
        spec.runtime_args.push("--threads=2".to_string());
        assert_ne!(first, runtime_config_digest(&spec));

        spec.runtime_env
            .insert("LD_PRELOAD".to_string(), "evil.so".to_string());
        assert!(validate_spec_paths(&spec).is_err());
        fs::remove_file(path).expect("cleanup");
    }

    #[cfg(unix)]
    #[test]
    fn resident_runtime_process_executes_load_infer_unload_protocol() {
        use std::os::unix::fs::PermissionsExt;

        let weights = temp_file("weights", b"weights");
        let tokenizer = temp_file("tokenizer", b"tokenizer");
        let preprocessor = temp_file("preprocessor", b"preprocessor");
        let quantization = temp_file("quantization", b"quantization");
        let license = temp_file("license", b"license");
        let sbom = temp_file("sbom", b"sbom");
        let device = temp_file("device", b"device");
        let runtime = temp_file(
            "runtime",
            br#"#!/bin/sh
IFS= read -r load || exit 10
binding=${load#*\"binding\":}
binding=${binding%%,\"paths\":*}
[ -n "$binding" ] || exit 11
printf '{"protocol":"hepta.local-model-runtime.v1","operation":"load_result","ok":true,"model_id":"model.1","handle_id":"handle.1","process_id":%s,"binding":%s,"reserved_memory_bytes":1024,"error":null}\n' "$$" "$binding"
IFS= read -r infer || exit 12
case "$infer" in
  *'"request_id":"request.1"'*'"payload":"hello local model"'*) ;;
  *) exit 13 ;;
esac
printf '{"protocol":"hepta.local-model-runtime.v1","operation":"infer_result","request_id":"request.1","handle_id":"handle.1","terminal_observed":true,"succeeded":true,"output":"runtime output","consumed_tokens":7,"observed_memory_bytes":1024,"error":null}\n'
IFS= read -r unload || exit 14
printf '{"protocol":"hepta.local-model-runtime.v1","operation":"unload_result","ok":true,"handle_id":"handle.1","error":null}\n'
"#,
        );
        let mut permissions = fs::metadata(&runtime).expect("runtime metadata").permissions();
        permissions.set_mode(0o700);
        fs::set_permissions(&runtime, permissions).expect("runtime executable");

        let spec = LocalModelSpec {
            weights_path: weights.clone(),
            tokenizer_path: tokenizer.clone(),
            preprocessor_path: preprocessor.clone(),
            quantization_path: quantization.clone(),
            license_path: license.clone(),
            sbom_path: sbom.clone(),
            runtime_path: runtime.clone(),
            device_descriptor_path: device.clone(),
            runtime_args: Vec::new(),
            runtime_env: BTreeMap::new(),
        };
        let digest = |path: &Path| {
            let bytes = fs::read(path).expect("read fixture");
            format!("{:x}", Sha256::digest(bytes))
        };
        let manifest = ModelManifest {
            model_id: "model.1".to_string(),
            model_digest: "2".repeat(64),
            weights_digest: digest(&weights),
            tokenizer_digest: digest(&tokenizer),
            preprocessor_digest: digest(&preprocessor),
            quantization_digest: digest(&quantization),
            license_digest: digest(&license),
            sbom_digest: digest(&sbom),
            runtime_digest: digest(&runtime),
            runtime_config_digest: runtime_config_digest(&spec),
            device_digest: digest(&device),
            maximum_tokens: 128,
        };
        let grant = ResourceGrant {
            grant_id: "grant.1".to_string(),
            authority_epoch: 2,
            generation: 3,
            expires_at_ms: 10_000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 1,
            maximum_memory_bytes: 4096,
            device_digest: manifest.device_digest.clone(),
            semantic_digest: "1".repeat(64),
        };
        let payload = "hello local model".to_string();
        let payload_digest = format!("{:x}", Sha256::digest(payload.as_bytes()));
        let request = WorkerRequest {
            request_id: "request.1".to_string(),
            reservation_id: "reservation.1".to_string(),
            model_digest: manifest.model_digest.clone(),
            payload,
            payload_digest: payload_digest.clone(),
            maximum_tokens: 64,
            deadline_ms: 9_000,
            lease_payload_digest: payload_digest,
            reservation_model_digest: manifest.model_digest.clone(),
            reservation_maximum_tokens: 64,
            cancelled: false,
        };

        let mut driver = LocalProcessModelDriver::new(
            BTreeMap::from([(manifest.model_id.clone(), spec)]),
            Duration::from_secs(2),
        )
        .expect("driver");
        let handle = driver.load(&manifest, &grant).expect("load");
        assert_eq!(handle.observed_memory_bytes, 1024);
        let observed = driver.run(&handle, &request).expect("infer");
        assert!(observed.terminal_observed);
        assert!(observed.succeeded);
        assert_eq!(observed.output.as_deref(), Some("runtime output"));
        assert_eq!(observed.consumed_tokens, 7);
        driver.unload(handle).expect("unload");

        for path in [
            weights,
            tokenizer,
            preprocessor,
            quantization,
            license,
            sbom,
            device,
            runtime,
        ] {
            fs::remove_file(path).expect("cleanup");
        }
    }
}
