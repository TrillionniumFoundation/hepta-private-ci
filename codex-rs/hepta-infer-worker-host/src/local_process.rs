//! Real local-model adapter for an isolated runtime process.
//!
//! The worker owns verification, authority and accounting. The runtime owns
//! physical weight/device operations behind a private Unix socket. Every load
//! verifies the exact artifact bytes locally and requires the runtime to report
//! the same digests after it opens them. This keeps model/device truth out of a
//! provider string or opaque handle.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::symlink_metadata;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::path::PathBuf;
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
use crate::model_worker::sha256_hex;

const PROTOCOL: &str = "hepta.local-model-runtime.v1";
const MAX_REQUEST_BYTES: usize = 2 * 1024 * 1024;
const DEFAULT_MAX_RESPONSE_BYTES: usize = 2 * 1024 * 1024;
const FILE_HASH_BUFFER_BYTES: usize = 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalModelArtifacts {
    pub weights_path: PathBuf,
    pub tokenizer_path: PathBuf,
    pub preprocessor_path: PathBuf,
    pub quantization_path: PathBuf,
    pub runtime_path: PathBuf,
    pub device_descriptor_path: PathBuf,
    pub isolation_receipt_path: PathBuf,
}

#[derive(Clone, Debug)]
pub struct LocalProcessConfig {
    pub runtime_socket: PathBuf,
    pub artifacts: BTreeMap<String, LocalModelArtifacts>,
    pub timeout: Duration,
    pub maximum_response_bytes: usize,
}

#[derive(Debug)]
pub struct LocalProcessDriver {
    config: LocalProcessConfig,
}

#[derive(Serialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum RuntimeRequest<'a> {
    Load {
        protocol: &'static str,
        manifest: &'a ModelManifest,
        grant: &'a ResourceGrant,
        artifacts: RuntimeArtifactPaths<'a>,
    },
    Infer {
        protocol: &'static str,
        handle_id: &'a str,
        request: &'a WorkerRequest,
        grant: &'a ResourceGrant,
    },
    Unload {
        protocol: &'static str,
        handle_id: &'a str,
    },
}

#[derive(Serialize)]
struct RuntimeArtifactPaths<'a> {
    weights_path: &'a Path,
    tokenizer_path: &'a Path,
    preprocessor_path: &'a Path,
    quantization_path: &'a Path,
    runtime_path: &'a Path,
    device_descriptor_path: &'a Path,
    isolation_receipt_path: &'a Path,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LoadResponse {
    protocol: String,
    ok: bool,
    error: Option<String>,
    handle_id: Option<String>,
    observed_memory_bytes: Option<u64>,
    model_digest: Option<String>,
    weights_digest: Option<String>,
    tokenizer_digest: Option<String>,
    preprocessor_digest: Option<String>,
    quantization_digest: Option<String>,
    runtime_digest: Option<String>,
    device_digest: Option<String>,
    isolation_digest: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct InferResponse {
    protocol: String,
    ok: bool,
    error: Option<String>,
    terminal_observed: Option<bool>,
    succeeded: Option<bool>,
    output: Option<String>,
    consumed_tokens: Option<u32>,
    observed_memory_bytes: Option<u64>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct UnloadResponse {
    protocol: String,
    ok: bool,
    error: Option<String>,
}

impl LocalProcessDriver {
    pub fn new(config: LocalProcessConfig) -> Result<Self, Error> {
        if !config.runtime_socket.is_absolute()
            || config.timeout.is_zero()
            || config.timeout > Duration::from_secs(3600)
            || config.maximum_response_bytes == 0
            || config.maximum_response_bytes > 16 * 1024 * 1024
            || config.artifacts.is_empty()
            || config.artifacts.len() > 8
        {
            return Err(failure("invalid local runtime configuration"));
        }
        for (model_id, artifacts) in &config.artifacts {
            validate_model_id(model_id)?;
            for path in artifact_paths(artifacts) {
                if !path.is_absolute() {
                    return Err(failure("local model artifact path must be absolute"));
                }
            }
        }
        Ok(Self { config })
    }

    pub fn single_model(
        runtime_socket: PathBuf,
        model_id: String,
        artifacts: LocalModelArtifacts,
        timeout: Duration,
    ) -> Result<Self, Error> {
        Self::new(LocalProcessConfig {
            runtime_socket,
            artifacts: BTreeMap::from([(model_id, artifacts)]),
            timeout,
            maximum_response_bytes: DEFAULT_MAX_RESPONSE_BYTES,
        })
    }

    fn artifacts(&self, model_id: &str) -> Result<&LocalModelArtifacts, Error> {
        self.config
            .artifacts
            .get(model_id)
            .ok_or_else(|| failure("no local artifact mapping for model"))
    }

    fn verify_artifacts(
        &self,
        manifest: &ModelManifest,
        artifacts: &LocalModelArtifacts,
    ) -> Result<(), Error> {
        for (path, expected, label) in [
            (&artifacts.weights_path, &manifest.weights_digest, "weights"),
            (
                &artifacts.tokenizer_path,
                &manifest.tokenizer_digest,
                "tokenizer",
            ),
            (
                &artifacts.preprocessor_path,
                &manifest.preprocessor_digest,
                "preprocessor",
            ),
            (
                &artifacts.quantization_path,
                &manifest.quantization_digest,
                "quantization",
            ),
            (&artifacts.runtime_path, &manifest.runtime_digest, "runtime"),
            (
                &artifacts.device_descriptor_path,
                &manifest.device_digest,
                "device descriptor",
            ),
            (
                &artifacts.isolation_receipt_path,
                &manifest.isolation_digest,
                "isolation receipt",
            ),
        ] {
            let actual = hash_regular_file(path)?;
            if &actual != expected {
                return Err(failure(format!("{label} digest mismatch")));
            }
        }
        Ok(())
    }

    fn exchange<T: Serialize, R: DeserializeOwned>(&self, value: &T) -> Result<R, Error> {
        let metadata = symlink_metadata(&self.config.runtime_socket)
            .map_err(|error| failure(format!("local runtime socket unavailable: {error}")))?;
        if metadata.file_type().is_symlink() || !metadata.file_type().is_socket() {
            return Err(failure(
                "local runtime endpoint is not a direct Unix socket",
            ));
        }
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(failure(
                "local runtime socket must not be accessible by group or world",
            ));
        }
        let encoded = serde_json::to_vec(value)
            .map_err(|error| failure(format!("encode local runtime request: {error}")))?;
        if encoded.len() > MAX_REQUEST_BYTES {
            return Err(failure("local runtime request exceeds byte limit"));
        }
        let mut stream = UnixStream::connect(&self.config.runtime_socket)
            .map_err(|error| failure(format!("connect local runtime: {error}")))?;
        stream
            .set_read_timeout(Some(self.config.timeout))
            .map_err(|error| failure(format!("set runtime read timeout: {error}")))?;
        stream
            .set_write_timeout(Some(self.config.timeout))
            .map_err(|error| failure(format!("set runtime write timeout: {error}")))?;
        stream
            .write_all(&encoded)
            .and_then(|()| stream.write_all(b"\n"))
            .and_then(|()| stream.flush())
            .map_err(|error| failure(format!("write local runtime request: {error}")))?;
        let mut reader = BufReader::new(stream);
        let line = read_bounded_line(&mut reader, self.config.maximum_response_bytes)?;
        serde_json::from_slice(&line)
            .map_err(|error| failure(format!("decode local runtime response: {error}")))
    }
}

impl ModelDriver for LocalProcessDriver {
    fn load(
        &mut self,
        manifest: &ModelManifest,
        grant: &ResourceGrant,
    ) -> Result<DriverModelHandle, Error> {
        let artifacts = self.artifacts(&manifest.model_id)?.clone();
        self.verify_artifacts(manifest, &artifacts)?;
        let response: LoadResponse = self.exchange(&RuntimeRequest::Load {
            protocol: PROTOCOL,
            manifest,
            grant,
            artifacts: RuntimeArtifactPaths {
                weights_path: &artifacts.weights_path,
                tokenizer_path: &artifacts.tokenizer_path,
                preprocessor_path: &artifacts.preprocessor_path,
                quantization_path: &artifacts.quantization_path,
                runtime_path: &artifacts.runtime_path,
                device_descriptor_path: &artifacts.device_descriptor_path,
                isolation_receipt_path: &artifacts.isolation_receipt_path,
            },
        })?;
        validate_protocol(&response.protocol)?;
        if !response.ok {
            return Err(runtime_error(response.error));
        }
        for (actual, expected, label) in [
            (
                response.model_digest.as_deref(),
                manifest.model_digest.as_str(),
                "model",
            ),
            (
                response.weights_digest.as_deref(),
                manifest.weights_digest.as_str(),
                "weights",
            ),
            (
                response.tokenizer_digest.as_deref(),
                manifest.tokenizer_digest.as_str(),
                "tokenizer",
            ),
            (
                response.preprocessor_digest.as_deref(),
                manifest.preprocessor_digest.as_str(),
                "preprocessor",
            ),
            (
                response.quantization_digest.as_deref(),
                manifest.quantization_digest.as_str(),
                "quantization",
            ),
            (
                response.runtime_digest.as_deref(),
                manifest.runtime_digest.as_str(),
                "runtime",
            ),
            (
                response.device_digest.as_deref(),
                manifest.device_digest.as_str(),
                "device",
            ),
            (
                response.isolation_digest.as_deref(),
                manifest.isolation_digest.as_str(),
                "isolation",
            ),
        ] {
            if actual != Some(expected) {
                return Err(failure(format!(
                    "local runtime did not prove exact {label} digest"
                )));
            }
        }
        let handle_id = response
            .handle_id
            .filter(|value| !value.is_empty() && value.len() <= 128)
            .ok_or_else(|| failure("local runtime omitted model handle"))?;
        let observed_memory_bytes = response
            .observed_memory_bytes
            .ok_or_else(|| failure("local runtime omitted memory reservation"))?;
        if observed_memory_bytes == 0 || observed_memory_bytes > grant.maximum_memory_bytes {
            return Err(failure("local runtime memory reservation exceeds grant"));
        }
        Ok(DriverModelHandle {
            opaque_id: handle_id,
            observed_memory_bytes,
        })
    }

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
        grant: &ResourceGrant,
    ) -> Result<DriverRunObservation, Error> {
        if sha256_hex(request.prompt.as_bytes()) != request.payload_digest {
            return Err(Error::PayloadMismatch);
        }
        let response: InferResponse = self.exchange(&RuntimeRequest::Infer {
            protocol: PROTOCOL,
            handle_id: &handle.opaque_id,
            request,
            grant,
        })?;
        validate_protocol(&response.protocol)?;
        if !response.ok {
            return Err(runtime_error(response.error));
        }
        let terminal_observed = response
            .terminal_observed
            .ok_or_else(|| failure("local runtime omitted terminal observation"))?;
        let succeeded = response
            .succeeded
            .ok_or_else(|| failure("local runtime omitted success observation"))?;
        let consumed_tokens = response
            .consumed_tokens
            .ok_or_else(|| failure("local runtime omitted token usage"))?;
        let observed_memory_bytes = response
            .observed_memory_bytes
            .ok_or_else(|| failure("local runtime omitted memory observation"))?;
        if observed_memory_bytes == 0 || observed_memory_bytes > grant.maximum_memory_bytes {
            return Err(failure("local runtime memory observation exceeds grant"));
        }
        let output_digest = match response.output {
            Some(output) => {
                if output.len() > self.config.maximum_response_bytes {
                    return Err(failure("local runtime output exceeds byte limit"));
                }
                Some(sha256_hex(output.as_bytes()))
            }
            None => None,
        };
        if terminal_observed && succeeded && output_digest.is_none() {
            return Err(Error::MissingTerminalOutput);
        }
        Ok(DriverRunObservation {
            terminal_observed,
            succeeded,
            output_digest,
            consumed_tokens,
            observed_memory_bytes,
        })
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        let response: UnloadResponse = self.exchange(&RuntimeRequest::Unload {
            protocol: PROTOCOL,
            handle_id: &handle.opaque_id,
        })?;
        validate_protocol(&response.protocol)?;
        if response.ok {
            Ok(())
        } else {
            Err(runtime_error(response.error))
        }
    }
}

fn artifact_paths(value: &LocalModelArtifacts) -> [&Path; 7] {
    [
        &value.weights_path,
        &value.tokenizer_path,
        &value.preprocessor_path,
        &value.quantization_path,
        &value.runtime_path,
        &value.device_descriptor_path,
        &value.isolation_receipt_path,
    ]
}

fn hash_regular_file(path: &Path) -> Result<String, Error> {
    let metadata = symlink_metadata(path)
        .map_err(|error| failure(format!("inspect {}: {error}", path.display())))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(failure(format!(
            "local artifact is not a direct regular file: {}",
            path.display()
        )));
    }
    let mut file =
        File::open(path).map_err(|error| failure(format!("open {}: {error}", path.display())))?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; FILE_HASH_BUFFER_BYTES];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|error| failure(format!("read {}: {error}", path.display())))?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(format_digest(hasher.finalize().into()))
}

fn read_bounded_line(reader: &mut BufReader<UnixStream>, maximum: usize) -> Result<Vec<u8>, Error> {
    let mut line = Vec::new();
    loop {
        let available = reader
            .fill_buf()
            .map_err(|error| failure(format!("read local runtime response: {error}")))?;
        if available.is_empty() {
            return Err(failure("local runtime closed without newline response"));
        }
        if let Some(index) = available.iter().position(|byte| *byte == b'\n') {
            if line.len().saturating_add(index) > maximum {
                return Err(failure("local runtime response exceeds byte limit"));
            }
            line.extend_from_slice(&available[..index]);
            reader.consume(index + 1);
            return Ok(line);
        }
        if line.len().saturating_add(available.len()) > maximum {
            return Err(failure("local runtime response exceeds byte limit"));
        }
        let count = available.len();
        line.extend_from_slice(available);
        reader.consume(count);
    }
}

fn validate_protocol(value: &str) -> Result<(), Error> {
    if value == PROTOCOL {
        Ok(())
    } else {
        Err(failure("local runtime protocol mismatch"))
    }
}

fn validate_model_id(value: &str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(failure("invalid local model id"));
    }
    Ok(())
}

fn runtime_error(error: Option<String>) -> Error {
    failure(
        error
            .unwrap_or_else(|| "local runtime rejected request".to_string())
            .chars()
            .take(1024)
            .collect::<String>(),
    )
}

fn failure(message: impl Into<String>) -> Error {
    Error::DriverFailure(message.into())
}

fn format_digest(digest: [u8; 32]) -> String {
    let mut encoded = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut encoded, "{byte:02x}");
    }
    encoded
}

#[cfg(test)]
#[path = "local_process_tests.rs"]
mod tests;
