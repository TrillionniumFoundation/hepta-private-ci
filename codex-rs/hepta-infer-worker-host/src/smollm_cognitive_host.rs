//! Qualified neural composition for the ordinary Agentd cognitive read route.
//! Original artifact, CURRENT, evaluation, selector, inference.control and
//! kernel FinalUse owners remain authoritative. This module creates no grant,
//! signing key, product qualification or alternative selection receipt.

use std::fs::File;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::NeuralCognitiveInferencePortV1;
use codex_hepta_agentd::NeuralCognitiveObservationV1;
use codex_hepta_agentd::NeuralCognitiveRequestV1;
use codex_hepta_agentd::load_neural_cognitive_process_bootstrap_v1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio_util::sync::CancellationToken;

use crate::final_use_authorizer::UnixFinalUseAuthorizer;
use crate::model_worker::ResourceGrant;
use crate::smollm_neural_read::SmolLmNeuralReadConfigV1;
use crate::smollm_neural_read::SmolLmNeuralReadPortV1;

const MAX_PARAMETER_BYTES: u64 = 2 * 1024 * 1024;

/// Complete host-owned inputs. The descriptor digest must be independently
/// authorized. Resource bounds and executable pins are supplied by the existing
/// host; every physical load/read still requires its independent Unix issuer.
pub struct SmolLmCognitiveHostInputsV1 {
    pub descriptor: PathBuf,
    pub descriptor_digest: Digest32,
    pub worker: SmolLmNeuralReadConfigV1,
    pub worker_id: String,
    pub resource_grant: ResourceGrant,
    pub inference_journal: PathBuf,
    pub inference_journal_capacity: usize,
    pub final_use_authorizer_config: PathBuf,
}

/// Ready to pass to the original `codex_hepta_agentd::run`. Preparation has
/// loaded qualified parameters; it does not claim an ordinary task used them.
/// Keep `session` until Agentd has stopped, then require its explicit shutdown.
pub struct PreparedSmolLmAgentdV1 {
    pub config: AgentdConfig,
    pub session: SmolLmCognitiveSessionV1,
}

/// Owns cleanup of the warm original inference port. Drop is only best-effort
/// cleanup; only successful `shutdown` establishes terminal unload observation.
#[must_use = "retain the session until Agentd stops and observe shutdown"]
pub struct SmolLmCognitiveSessionV1 {
    port: Option<Arc<SmolLmNeuralReadPortV1>>,
    runtime: tokio::runtime::Handle,
}

impl SmolLmCognitiveSessionV1 {
    pub async fn shutdown(mut self) -> Result<(), String> {
        let port = self.port.take().ok_or("neural session already consumed")?;
        self.runtime
            .spawn_blocking(move || port.shutdown())
            .await
            .map_err(|error| format!("neural terminal unload worker: {error}"))?
    }
}

impl Drop for SmolLmCognitiveSessionV1 {
    fn drop(&mut self) {
        if let Some(port) = self.port.take() {
            // Never turn asynchronous cleanup into a successful receipt.
            std::mem::drop(self.runtime.spawn_blocking(move || {
                let _ = port.shutdown();
            }));
        }
    }
}

#[derive(Default)]
struct PreparedInferencePort(OnceLock<Arc<SmolLmNeuralReadPortV1>>);

struct CancelPreparation(Option<CancellationToken>);

impl Drop for CancelPreparation {
    fn drop(&mut self) {
        if let Some(token) = self.0.take() {
            token.cancel();
        }
    }
}

impl NeuralCognitiveInferencePortV1 for PreparedInferencePort {
    fn execute(
        &self,
        request: &NeuralCognitiveRequestV1,
        parameters: &[u8],
    ) -> Result<NeuralCognitiveObservationV1, String> {
        self.0
            .get()
            .ok_or("qualified neural port is not warm")?
            .execute(request, parameters)
    }
}

/// Replay the original product qualification and CURRENT owners before loading
/// a model, then attach that actual model to the ordinary cognitive route. A
/// missing/ineligible descriptor is a terminal error, with no model fallback.
pub async fn prepare_smollm_neural_agentd_v1(
    config: AgentdConfig,
    inputs: SmolLmCognitiveHostInputsV1,
) -> Result<PreparedSmolLmAgentdV1, String> {
    let runtime = tokio::runtime::Handle::try_current()
        .map_err(|error| format!("neural host runtime: {error}"))?;
    let worker_runtime = runtime.clone();
    let cancellation = CancellationToken::new();
    let mut pending = CancelPreparation(Some(cancellation.clone()));
    let result = runtime
        .spawn_blocking(move || prepare(config, inputs, worker_runtime, cancellation))
        .await
        .map_err(|error| format!("neural composition worker: {error}"))?;
    pending.0 = None;
    result
}

fn prepare(
    config: AgentdConfig,
    inputs: SmolLmCognitiveHostInputsV1,
    runtime: tokio::runtime::Handle,
    cancellation: CancellationToken,
) -> Result<PreparedSmolLmAgentdV1, String> {
    if cancellation.is_cancelled() {
        return Err("neural host preparation cancelled before qualification".to_owned());
    }
    StableId::new(inputs.worker_id.clone()).map_err(|error| error.to_string())?;
    if !inputs.inference_journal.is_absolute()
        || !inputs.final_use_authorizer_config.is_absolute()
        || !(1..=16_384).contains(&inputs.inference_journal_capacity)
    {
        return Err("neural inference owner paths or capacity are invalid".to_owned());
    }
    let identity = config.identity();
    for path in [
        &inputs.inference_journal,
        &inputs.final_use_authorizer_config,
    ] {
        validate_inference_owner_path(
            path,
            &[&identity.home_root, &identity.run_root, &identity.workspace],
        )?;
    }
    let owner = identity.agent_id.clone();
    let generation = identity.spawn_generation;
    let slot = Arc::new(PreparedInferencePort::default());
    // Loader replay and the canonical selector below never invoke this port.
    // A descriptor cannot activate it or supply another implementation.
    let bootstrap = load_neural_cognitive_process_bootstrap_v1(
        &inputs.descriptor,
        inputs.descriptor_digest,
        identity,
        slot.clone(),
    )
    .map_err(|error| format!("neural product qualification: {error}"))?;
    let pin = bootstrap.model_pin.pin.clone();
    let parameters = read_parameter_fd(&bootstrap.payload, pin.payload_digest)?;
    let config = config
        .with_evaluated_neural_cognitive_bootstrap(bootstrap)
        .map_err(|error| format!("neural qualified selection/CURRENT: {error}"))?;

    // No inference journal is opened, resource entered, issuer called or model
    // started until the original qualification and selection factories succeed.
    if cancellation.is_cancelled() {
        return Err("neural host preparation cancelled before inference owners".to_owned());
    }
    let authorizer = Arc::new(
        UnixFinalUseAuthorizer::open(&inputs.final_use_authorizer_config)
            .map_err(|error| format!("neural original FinalUse owner: {error}"))?,
    );
    let control = Arc::new(Mutex::new(
        DurableInferenceControl::open(inputs.inference_journal, inputs.inference_journal_capacity)
            .map_err(|error| format!("neural original inference.control: {error}"))?,
    ));
    let port = Arc::new(
        SmolLmNeuralReadPortV1::start_cancellable(
            inputs.worker,
            pin,
            parameters,
            owner,
            generation,
            inputs.worker_id,
            inputs.resource_grant,
            control,
            authorizer,
            runtime.clone(),
            cancellation.clone(),
        )
        .map_err(|error| format!("neural original model load: {error}"))?,
    );
    if cancellation.is_cancelled() {
        let cleanup = port.shutdown();
        return Err(format!(
            "neural host preparation cancelled after load; terminal unload: {cleanup:?}"
        ));
    }
    if slot.0.set(port.clone()).is_err() {
        let cleanup = port.shutdown();
        return Err(format!(
            "neural port already bound; terminal unload: {cleanup:?}"
        ));
    }
    Ok(PreparedSmolLmAgentdV1 {
        config,
        session: SmolLmCognitiveSessionV1 {
            port: Some(port),
            runtime,
        },
    })
}

fn read_parameter_fd(file: &File, expected: Digest32) -> Result<Vec<u8>, String> {
    let metadata = file.metadata().map_err(|error| error.to_string())?;
    if !metadata.is_file() || !(1..=MAX_PARAMETER_BYTES).contains(&metadata.len()) {
        return Err("neural parameter FD exceeds the registered SmolLM bounds".to_owned());
    }
    let length = usize::try_from(metadata.len()).map_err(|error| error.to_string())?;
    let mut bytes = vec![0; length];
    // read_at neither reopens a mutable pathname nor moves the artifact owner's
    // shared cursor. The original ranker independently validates this same FD.
    file.read_exact_at(&mut bytes, 0)
        .map_err(|error| error.to_string())?;
    if expected.is_zero() || Digest32::of_bytes(&bytes) != expected {
        return Err("neural parameter FD differs from the qualified payload".to_owned());
    }
    Ok(bytes)
}

fn validate_inference_owner_path(path: &Path, body_roots: &[&Path]) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or("neural inference owner path has no parent")?;
    if !path.is_absolute()
        || path.file_name().is_none()
        || parent.canonicalize().map_err(|error| error.to_string())? != parent
        || body_roots.iter().any(|root| path.starts_with(root))
        || std::fs::symlink_metadata(parent)
            .map_err(|error| error.to_string())?
            .mode()
            & 0o022
            != 0
    {
        return Err(
            "neural inference owner path must be canonical, protected and outside the body"
                .to_owned(),
        );
    }
    match std::fs::symlink_metadata(path) {
        Ok(metadata)
            if !metadata.is_file() || metadata.nlink() != 1 || metadata.mode() & 0o022 != 0 =>
        {
            Err("neural inference owner file must be protected, regular and unaliased".to_owned())
        }
        Ok(_) => Ok(()),
        // The original journal owner may create a new regular file; the
        // original authorizer separately requires its config to exist.
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.to_string()),
    }
}

#[cfg(test)]
#[path = "smollm_cognitive_host_tests.rs"]
mod tests;
