//! Private CPU process driver for the registered single-token read profile.
//! The original InferenceWorker owns its model/resource lifecycle.

use std::fs::OpenOptions;
use std::fs::{self};
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_agentd::NeuralCognitivePinV1;
use codex_hepta_agentd::NeuralCognitiveRequestV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelDriver;
use crate::model_worker::ModelManifest;
use crate::model_worker::WorkerRequest;

#[path = "smollm_neural_profile.rs"]
mod profile;
#[path = "smollm_neural_session.rs"]
mod session;
use profile::NoAuthority;
use profile::PROFILE;
use profile::Ready;
use profile::SCHEMA;
pub use profile::SmolLmNeuralReadConfigV1;
use session::Session;
use session::read_bounded;
use session::write_private;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    schema: String,
    request_id: String,
    input_sha256: String,
    file_sha256: String,
    artifact: String,
    contract: String,
    profile: String,
    pub(super) action_ids: Vec<String>,
    pub(super) scores_q32: Vec<i64>,
    input_tokens: usize,
    logits_sha256: String,
    execution_ns: u64,
    observed_rss_bytes: u64,
    authority: NoAuthority,
}

pub(super) struct Exchange {
    pub(super) request: NeuralCognitiveRequestV1,
    pub(super) request_id: String,
    pub(super) payload_digest: String,
    pub(super) response: Option<(Response, Digest32)>,
}
pub(super) type Mailbox = Arc<Mutex<Option<Exchange>>>;

pub(super) struct SmolLmDriver {
    pub(super) config: SmolLmNeuralReadConfigV1,
    pub(super) pin: NeuralCognitivePinV1,
    pub(super) parameters: Vec<u8>,
    pub(super) mailbox: Mailbox,
    runtime: tokio::runtime::Handle,
    session: Option<Session>,
}

impl SmolLmDriver {
    pub(super) fn new(
        config: SmolLmNeuralReadConfigV1,
        pin: NeuralCognitivePinV1,
        parameters: Vec<u8>,
        mailbox: Mailbox,
        runtime: tokio::runtime::Handle,
    ) -> Self {
        Self {
            config,
            pin,
            parameters,
            mailbox,
            runtime,
            session: None,
        }
    }

    fn start(&mut self) -> Result<DriverModelHandle, String> {
        let config = &self.config;
        config.verify_sources()?;
        if self.parameters.len() > 2 * 1024 * 1024
            || self.parameters.is_empty()
            || Digest32::of_bytes(&self.parameters) != self.pin.payload_digest
            || config.execution_profile_digest()? != self.pin.execution_profile_digest
            || config
                .source_identities()?
                .get("model-family-smollm2-135m-v1.json")
                != Some(&self.pin.family_digest.to_string())
            || !config.python.is_absolute()
            || !config.script.is_absolute()
            || !config.materials.is_absolute()
            || !config.run_directory.is_absolute()
            || config.source_pins.get(&config.script).is_none()
            || config.target_contract.len() > 1024 * 1024
            || config.wrapped_adapter.len() > 1024 * 1024
            || config.action_completions.is_empty()
            || config.action_completions.len() > 128
            || config
                .action_completions
                .values()
                .any(|label| label.is_empty() || label.len() > 64)
        {
            return Err("neural worker immutable profile mismatch".to_owned());
        }
        fs::DirBuilder::new()
            .mode(0o700)
            .create(&config.run_directory)
            .map_err(|error| error.to_string())?;
        let root = &config.run_directory;
        write_private(&root.join("target-contract.json"), &config.target_contract)?;
        write_private(&root.join("wrapped-adapter.json"), &config.wrapped_adapter)?;
        write_private(&root.join("artifact.safetensors"), &self.parameters)?;
        let parent = serde_json::to_vec(&serde_json::json!({
            "schema":"hepta-smollm-parent-material-v1", "generation":self.pin.generation.get(),
            "operation_id":"hepta-owner-neural-load", "directory":root,
            "contract":config.contract_digest.to_string(), "adapter":config.adapter_digest.to_string(),
            "file_sha256":self.pin.payload_digest.to_string(),
        })).map_err(|error| error.to_string())?;
        let actions = serde_json::to_vec(&config.actions()).map_err(|error| error.to_string())?;
        write_private(&root.join("parent.json"), &parent)?;
        write_private(&root.join("actions.json"), &actions)?;
        let log = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(root.join("host-process.log"))
            .map_err(|error| error.to_string())?;
        let directory = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW)
            .open(root)
            .map_err(|error| error.to_string())?;
        let child = Command::new(&config.python)
            .arg(&config.script)
            .arg("serve")
            .arg("--materials")
            .arg(&config.materials)
            .arg("--parent")
            .arg(root.join("parent.json"))
            .arg("--parent-sha256")
            .arg(Digest32::of_bytes(&parent).to_string())
            .arg("--actions")
            .arg(root.join("actions.json"))
            .arg("--actions-sha256")
            .arg(Digest32::of_bytes(&actions).to_string())
            .arg("--output")
            .arg(root.join("session"))
            .arg("--threads")
            .arg("4")
            .env("CUDA_VISIBLE_DEVICES", "")
            .env("HF_HUB_OFFLINE", "1")
            .env("TRANSFORMERS_OFFLINE", "1")
            .stdin(Stdio::null())
            .stdout(log.try_clone().map_err(|error| error.to_string())?)
            .stderr(log)
            .spawn()
            .map_err(|error| error.to_string())?;
        // The session keeps a descriptor even while waiting for the worker
        // directory. Drop always retains the original observer for cleanup.
        self.session = Some(Session::new(directory, child, self.runtime.clone()));
        let ready_path = self
            .session
            .as_ref()
            .ok_or("neural session missing")?
            .path("ready.json");
        let deadline = Instant::now() + Duration::from_secs(120);
        loop {
            let session = self.session.as_mut().ok_or("neural session missing")?;
            if session.has_exited()? {
                return Err("neural worker terminated before ready".to_owned());
            }
            if ready_path.exists() {
                break;
            }
            if Instant::now() >= deadline {
                return Err("neural load deadline exceeded".to_owned());
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let ready: Ready = serde_json::from_slice(&read_bounded(&ready_path, 65536)?)
            .map_err(|error| error.to_string())?;
        let mut sources = config.source_identities()?;
        let worker_source = sources
            .remove("llm_neural_read_worker.py")
            .ok_or("worker source pin")?;
        if ready.schema != SCHEMA
            || ready.actual_loaded_parent != config.adapter_digest.to_string()
            || ready.file_sha256 != self.pin.payload_digest.to_string()
            || ready.contract != config.contract_digest.to_string()
            || ready.generation != self.pin.generation.get()
            || ready.backbone != config.backbone_digest.to_string()
            || ready.tokenizer != config.tokenizer_digest.to_string()
            || ready.source_pins != sources
            || ready.worker_source != worker_source
            || ready.actions != config.actions()
            || !ready.authority.denied()
            || ready.observed_rss_bytes == 0
        {
            return Err("neural ready observation differs from the admitted material".to_owned());
        }
        Ok(DriverModelHandle {
            opaque_id: self.pin.payload_digest.to_string(),
            observed_memory_bytes: ready.observed_rss_bytes,
        })
    }
}

impl ModelDriver for SmolLmDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if self.session.is_some() || manifest.weights_digest != self.pin.payload_digest.to_string()
        {
            return Err(Error::ModelMismatch);
        }
        self.start().map_err(Error::DriverFailure)
    }
    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        let execute = || -> Result<DriverRunObservation, String> {
            self.config.verify_sources()?;
            if handle.opaque_id != self.pin.payload_digest.to_string() {
                return Err("neural handle mismatch".to_owned());
            }
            let mut mailbox = self
                .mailbox
                .lock()
                .map_err(|_| "neural exchange poisoned")?;
            let exchange = mailbox.as_mut().ok_or("neural exchange unavailable")?;
            if exchange.request_id != request.request_id
                || exchange.payload_digest != request.payload_digest
                || exchange.response.is_some()
            {
                return Err("neural exchange request mismatch".to_owned());
            }
            let bytes = serde_json::to_vec(
                &serde_json::json!({"schema":"hepta-smollm-inference-input-v1",
                "request_id":request.request_id, "prompt":exchange.request.query}),
            )
            .map_err(|error| error.to_string())?;
            let remaining_ms = request
                .deadline_ms
                .checked_sub(super::now_ms()?)
                .ok_or("neural operation deadline")?;
            let deadline = Instant::now() + Duration::from_millis(remaining_ms.min(1500));
            let raw = self
                .session
                .as_ref()
                .ok_or("neural session unavailable")?
                .exchange(&bytes, deadline)?;
            let response: Response =
                serde_json::from_slice(&raw).map_err(|error| error.to_string())?;
            if response.schema != SCHEMA
                || response.profile != PROFILE
                || response.request_id != request.request_id
                || response.input_sha256 != Digest32::of_bytes(&bytes).to_string()
                || response.file_sha256 != self.pin.payload_digest.to_string()
                || response.artifact != self.config.adapter_digest.to_string()
                || response.contract != self.config.contract_digest.to_string()
                || response.action_ids
                    != self
                        .config
                        .action_completions
                        .keys()
                        .map(ToString::to_string)
                        .collect::<Vec<_>>()
                || response.scores_q32.len() != response.action_ids.len()
                || !response.authority.denied()
                || response.input_tokens == 0
                || response.input_tokens > 128
                || response.execution_ns == 0
                || response.observed_rss_bytes == 0
                || response.logits_sha256.parse::<Digest32>().is_err()
            {
                return Err("neural response does not match actual requested execution".to_owned());
            }
            let output = Digest32::of_bytes(&raw);
            let observed_memory_bytes = response.observed_rss_bytes;
            exchange.response = Some((response, output));
            Ok(DriverRunObservation {
                terminal_observed: true,
                succeeded: true,
                output_digest: Some(output.to_string()),
                consumed_tokens: 1,
                observed_memory_bytes,
            })
        };
        execute().map_err(Error::DriverFailure)
    }
    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        if handle.opaque_id != self.pin.payload_digest.to_string() {
            return Err(Error::ModelMismatch);
        }
        self.session
            .as_mut()
            .ok_or(Error::ModelNotLoaded)?
            .shutdown()
            .map_err(Error::DriverFailure)?;
        self.session.take();
        Ok(())
    }
}
