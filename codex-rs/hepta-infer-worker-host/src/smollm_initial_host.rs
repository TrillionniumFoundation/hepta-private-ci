//! Initial-only physical load under the original selection/CURRENT/effect owners.
//! This owner exposes neither a config/session/port conversion nor a task route.

use super::*;
use crate::smollm_neural_read::SmolLmMeasuredLoadV1;
use crate::smollm_neural_read::runtime_identity::SmolLmRuntimeIdentityV1;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_learning_artifacts::ArtifactOwnerCurrentReaderV1;
use codex_hepta_learning_artifacts::SelectedInitialSmolLmMaterialV1;

/// Original host-owned paths, bounded resources and executable expectations.
/// No selector, issuer key, evaluation evidence or observed root is supplied.
pub struct SmolLmInitialHostInputsV1 {
    pub worker: SmolLmNeuralReadConfigV1,
    pub worker_id: String,
    pub resource_grant: ResourceGrant,
    pub inference_journal: PathBuf,
    pub inference_journal_capacity: usize,
    pub final_use_authorizer_config: PathBuf,
}

/// One original owner, including rejected post-load preparations until cleanup.
/// There is no Clone, serialization, external constructor or extraction API.
#[must_use = "retain the original owner and explicitly observe shutdown"]
pub struct PreparedSelectedInitialSmolLmV1 {
    config: AgentdConfig,
    material: Option<SelectedInitialSmolLmMaterialV1>,
    current: ArtifactOwnerCurrentReaderV1,
    session: SmolLmCognitiveSessionV1,
    association: Option<(Digest32, String, String)>,
}

/// Borrowed actual load evidence for one still-current selected initial parent.
/// The bounded callback may not dispatch effects or reenter the owner.
pub struct InitialSelectedLoadObservationV1<'a> {
    load: &'a SmolLmMeasuredLoadV1,
    selection_digest: Digest32,
}

impl InitialSelectedLoadObservationV1<'_> {
    pub fn measured(&self) -> &SmolLmMeasuredLoadV1 {
        self.load
    }
    pub fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }
}

/// A rejection retains any successfully loaded original session privately.
pub struct InitialSmolLmPreparationErrorV1 {
    reason: String,
    retained: Option<Box<PreparedSelectedInitialSmolLmV1>>,
}

impl std::fmt::Debug for InitialSmolLmPreparationErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("InitialSmolLmPreparationErrorV1")
            .field("reason", &self.reason)
            .field("cleanup_retained", &self.retained.is_some())
            .finish()
    }
}

impl std::fmt::Display for InitialSmolLmPreparationErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.reason)
    }
}

impl std::error::Error for InitialSmolLmPreparationErrorV1 {}

impl From<String> for InitialSmolLmPreparationErrorV1 {
    fn from(reason: String) -> Self {
        Self {
            reason,
            retained: None,
        }
    }
}

impl InitialSmolLmPreparationErrorV1 {
    pub fn reason(&self) -> &str {
        &self.reason
    }

    /// No retained session means no pending cleanup, never a terminal receipt.
    pub async fn shutdown_retained(&mut self) -> Result<(), String> {
        if let Some(owner) = self.retained.as_mut() {
            owner.shutdown().await?;
        }
        self.retained = None;
        Ok(())
    }
}

impl PreparedSelectedInitialSmolLmV1 {
    /// Historical identity only; the original Agentd config remains owned here.
    pub fn identity(&self) -> &AgentdIdentity {
        self.config.identity()
    }

    pub fn with_current_initial_load<T>(
        &mut self,
        observe: impl for<'a> FnOnce(InitialSelectedLoadObservationV1<'a>) -> Result<T, String>,
    ) -> Result<T, String> {
        self.observe(initial_now_seconds, observe)
    }

    fn observe<T>(
        &mut self,
        mut clock: impl FnMut() -> Result<u64, String>,
        observe: impl for<'a> FnOnce(InitialSelectedLoadObservationV1<'a>) -> Result<T, String>,
    ) -> Result<T, String> {
        // Taking the capsule first also closes CURRENT/clock/callback failures.
        let mut material = self.material.take().ok_or("initial owner is unavailable")?;
        let manifest = material.manifest();
        let parameter = manifest.content_digest;
        let generation = manifest.generation;
        let selection = material.selection_digest();
        let before = clock()?;
        let view = self
            .current
            .current_registry_view(before)
            .map_err(|e| e.to_string())?;
        if material
            .with_current(view, before, Digest32::of_bytes)
            .map_err(|e| e.to_string())?
            != parameter
        {
            return Err("selected initial parameter bytes changed".to_owned());
        }
        let port = self
            .session
            .port
            .as_ref()
            .ok_or("initial session is closed")?;
        let (result, association) = port.with_measurements(|load, _| {
            let fixed = load.fixed_initial_backbone()?;
            let actual = fixed.measured();
            let (request, reservation) = actual
                .control_load_ids()
                .ok_or("initial load was not settled")?;
            let association = (
                actual.ready_digest(),
                request.to_owned(),
                reservation.to_owned(),
            );
            if actual.parameter_file_digest() != parameter
                || actual.generation() != generation.get()
                || generation.get() != 1
                || self
                    .association
                    .as_ref()
                    .is_some_and(|old| old != &association)
            {
                return Err("actual load differs from its selected initial parent".to_owned());
            }
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                observe(InitialSelectedLoadObservationV1 {
                    load: actual,
                    selection_digest: selection,
                })
            }));
            Ok((result, association))
        })??;
        // Unwind only after the original worker/mailbox guards are released.
        let result = match result {
            Ok(result) => result?,
            Err(panic) => std::panic::resume_unwind(panic),
        };
        let after = clock()?;
        let view = self
            .current
            .current_registry_view(after)
            .map_err(|e| e.to_string())?;
        material
            .with_current(view, after, |_| ())
            .map_err(|e| e.to_string())?;
        self.association = Some(association);
        self.material = Some(material);
        Ok(result)
    }

    /// Failure keeps this exact original session for a later explicit cleanup.
    /// No failed unload or asynchronous Drop is a terminal resource receipt.
    pub async fn shutdown(&mut self) -> Result<(), String> {
        self.material = None;
        let port = self
            .session
            .port
            .as_ref()
            .cloned()
            .ok_or("initial session is closed")?;
        self.session
            .runtime
            .spawn_blocking(move || port.shutdown())
            .await
            .map_err(|e| format!("initial terminal unload worker: {e}"))??;
        self.session.port = None;
        Ok(())
    }
}

/// Consume real selected initial material, then load it through the existing
/// inference.control/resource/Unix FinalUse owners. No evaluated route is added.
pub async fn prepare_selected_initial_smollm_v1(
    config: AgentdConfig,
    material: SelectedInitialSmolLmMaterialV1,
    current: ArtifactOwnerCurrentReaderV1,
    inputs: SmolLmInitialHostInputsV1,
) -> Result<PreparedSelectedInitialSmolLmV1, InitialSmolLmPreparationErrorV1> {
    let runtime = tokio::runtime::Handle::try_current().map_err(|e| e.to_string())?;
    let worker_runtime = runtime.clone();
    let cancellation = CancellationToken::new();
    let mut pending = CancelPreparation(Some(cancellation.clone()));
    let result = runtime
        .spawn_blocking(move || {
            prepare_initial(
                config,
                material,
                current,
                inputs,
                worker_runtime,
                cancellation,
                initial_now_seconds,
            )
        })
        .await
        .map_err(|e| format!("initial preparation worker: {e}"))?;
    pending.0 = None;
    result
}

fn prepare_initial(
    config: AgentdConfig,
    mut material: SelectedInitialSmolLmMaterialV1,
    current: ArtifactOwnerCurrentReaderV1,
    inputs: SmolLmInitialHostInputsV1,
    runtime: tokio::runtime::Handle,
    cancellation: CancellationToken,
    mut clock: impl FnMut() -> Result<u64, String>,
) -> Result<PreparedSelectedInitialSmolLmV1, InitialSmolLmPreparationErrorV1> {
    if cancellation.is_cancelled() {
        return Err("initial preparation cancelled".to_owned().into());
    }
    StableId::new(inputs.worker_id.clone()).map_err(|e| e.to_string())?;
    if !(1..=16_384).contains(&inputs.inference_journal_capacity) {
        return Err("initial inference journal capacity is invalid"
            .to_owned()
            .into());
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
    let now = clock()?;
    let view = current
        .current_registry_view(now)
        .map_err(|e| e.to_string())?;
    let parameters = material
        .with_current(view, now, <[u8]>::to_vec)
        .map_err(|e| e.to_string())?;
    let manifest = material.manifest();
    let sources = inputs.worker.source_identities()?;
    let physical = SmolLmRuntimeIdentityV1 {
        payload_digest: manifest.content_digest,
        generation: manifest.generation,
        family_digest: sources
            .get("model-family-smollm2-135m-v1.json")
            .ok_or("initial family pin".to_owned())?
            .parse()
            .map_err(|e| format!("initial family digest: {e}"))?,
        execution_profile_digest: inputs.worker.execution_profile_digest()?,
    };
    let scope = Digest32::of_parts(&[
        b"hepta.smollm.selected-initial-runtime.v1\0",
        manifest.compatibility_digest.as_array(),
        manifest.content_digest.as_array(),
        &manifest.generation.get().to_be_bytes(),
        physical.family_digest.as_array(),
        physical.execution_profile_digest.as_array(),
        material.selection_digest().as_array(),
    ]);
    let authorizer = Arc::new(
        UnixFinalUseAuthorizer::open(&inputs.final_use_authorizer_config)
            .map_err(|e| e.to_string())?,
    );
    let control = Arc::new(Mutex::new(
        DurableInferenceControl::open(inputs.inference_journal, inputs.inference_journal_capacity)
            .map_err(|e| e.to_string())?,
    ));
    let port = Arc::new(SmolLmNeuralReadPortV1::start_initial_cancellable(
        inputs.worker,
        physical,
        scope,
        parameters,
        identity.agent_id.clone(),
        identity.spawn_generation,
        inputs.worker_id,
        inputs.resource_grant,
        control,
        authorizer,
        runtime.clone(),
        cancellation.clone(),
    )?);
    let mut prepared = PreparedSelectedInitialSmolLmV1 {
        config,
        material: Some(material),
        current,
        session: SmolLmCognitiveSessionV1 {
            port: Some(port),
            runtime,
        },
        association: None,
    };
    let verified = prepared.observe(clock, |_| {
        if cancellation.is_cancelled() {
            Err("initial preparation cancelled after load".to_owned())
        } else {
            Ok(())
        }
    });
    match verified {
        Ok(()) => Ok(prepared),
        Err(reason) => Err(InitialSmolLmPreparationErrorV1 {
            reason,
            retained: Some(Box::new(prepared)),
        }),
    }
}

fn initial_now_seconds() -> Result<u64, String> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|time| time.as_secs())
        .map_err(|e| e.to_string())
}
