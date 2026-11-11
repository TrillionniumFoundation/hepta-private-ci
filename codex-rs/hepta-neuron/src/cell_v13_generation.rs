//! Frozen V13 new-task proposals. Full learning closure is verified in one
//! process; another receives no source bodies, training dataset or example rows.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::CellBackendManifestV2;
use crate::CellCostAccountingV2;
use crate::CellCostEntryV2;
use crate::CellCostMetricsV2;
use crate::CellCostOutcomeV2;
use crate::CellCostStageV2;
use crate::CellGenerationDispositionV2;
use crate::CellGenerationErrorV2;
use crate::CellGenerationProposalV2;
use crate::CellGenerationRequestV2;
use crate::CellGenerationWorkerV2;
use crate::CellLearningBindingV2;
use crate::CellTaskCostIdentityV2;
use crate::CellTaskCostV2;
use crate::JointGenerationProcessWorkerV1;
use crate::cell_joint_process::elapsed_micros;
use crate::cell_v13_assets;
use crate::cell_v13_assets::PreparedFiles;
pub use crate::cell_v13_assets::V13GenerationAssetFileV1;
pub use crate::cell_v13_assets::V13GenerationProcessFilesV1;
use crate::cell_v13_process;
use crate::cell_v13_process::ProcessObservation;
use crate::cell_v13_process::ProcessRequest;
use crate::cell_v13_protocol;
use crate::cell_v13_protocol::Phase;
use crate::cell_v13_protocol::PhasePayload;
use crate::cell_v13_protocol::PhaseResponse;
use crate::cell_v13_protocol::V13LearningClosureV1;
use crate::cell_v13_protocol::V13TaskInputV1;
use crate::cell_v13_protocol::terminal_status;

pub struct V13GenerationProcessConfigV1 {
    /// Only argv0, to select the host's explicit Python environment. Execution
    /// uses the separately opened interpreter inode, never this pathname.
    pub interpreter_argv0: PathBuf,
    pub interpreter_digest: [u8; 32],
    pub worker_digest: [u8; 32],
    pub source_digest: [u8; 32],
    pub device_digest: [u8; 32],
    pub closure: V13LearningClosureV1,
    /// Per phase, at most two sequential phases. Never exceeds 60 CPU seconds
    /// across their integer-second limits; measured overruns remain measured.
    pub phase_cpu_seconds: u64,
    pub address_space_bytes: u64,
    pub wall_limit: Duration,
}

pub struct V13GenerationProcessWorkerV1 {
    config: V13GenerationProcessConfigV1,
    files: PreparedFiles,
    bundle_digest: [u8; 32],
    runtime_digest: [u8; 32],
    preparation_wall_micros: u64,
    preparation_event: [u8; 32],
    clock: Arc<dyn Fn() -> u64 + Send + Sync>,
}

impl V13GenerationProcessWorkerV1 {
    pub const PROFILE: &'static str = "v13-minilm-task-proposal-linux-v1";

    pub fn open_files(
        config: V13GenerationProcessConfigV1,
        files: V13GenerationProcessFilesV1,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>,
    ) -> Result<Self, CellGenerationErrorV2> {
        let started = Instant::now();
        let observed = clock();
        if observed == 0
            || !config.interpreter_argv0.is_absolute()
            || config.source_digest == [0; 32]
            || config.device_digest == [0; 32]
            || !(1..=30).contains(&config.phase_cpu_seconds)
            || !(1..=4 * 1024_u64.pow(3)).contains(&config.address_space_bytes)
            || config.wall_limit.is_zero()
            || config.wall_limit > Duration::from_secs(120)
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        config.closure.binding()?;
        let files =
            cell_v13_assets::prepare(files, config.interpreter_digest, config.worker_digest)?;
        if files.assets.get("model.npz").map(|asset| asset.digest)
            != Some(config.closure.checkpoint_digest)
            || Self::observed_device_digest()? != config.device_digest
            || clock() < observed
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let catalog: Vec<_> = files
            .assets
            .iter()
            .map(|(name, asset)| (name, asset.digest))
            .collect();
        let catalog = serde_json::to_vec(&(catalog, config.closure.binding()?))
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let bundle_digest =
            Digest32::of_parts(&[b"hepta.v13.complete-assets.v1\0", &catalog]).into_array();
        let runtime_digest = Digest32::of_parts(&[
            b"hepta.v13.pinned-python-proposal.v1\0",
            &config.interpreter_digest,
            &config.worker_digest,
            config.interpreter_argv0.as_os_str().as_encoded_bytes(),
            &config.phase_cpu_seconds.to_le_bytes(),
            &config.address_space_bytes.to_le_bytes(),
            &u64::try_from(config.wall_limit.as_micros())
                .map_err(|_| CellGenerationErrorV2::Capacity)?
                .to_le_bytes(),
        ])
        .into_array();
        let preparation_wall_micros = elapsed_micros(started)?;
        let preparation_event = Digest32::of_parts(&[
            b"hepta.v13.preparation-cost.v1\0",
            &bundle_digest,
            &runtime_digest,
            &observed.to_le_bytes(),
            &preparation_wall_micros.to_le_bytes(),
        ])
        .into_array();
        Ok(Self {
            config,
            files,
            bundle_digest,
            runtime_digest,
            preparation_wall_micros,
            preparation_event,
            clock,
        })
    }

    pub fn bundle_digest(&self) -> [u8; 32] {
        self.bundle_digest
    }
    pub fn runtime_digest(&self) -> [u8; 32] {
        self.runtime_digest
    }
    pub fn learning_closure(&self) -> &V13LearningClosureV1 {
        &self.config.closure
    }
    /// All host/control/worker timestamps use this same selected epoch.
    pub fn clock(&self) -> Arc<dyn Fn() -> u64 + Send + Sync> {
        Arc::clone(&self.clock)
    }

    pub fn input_schema_digest() -> [u8; 32] {
        Digest32::of_bytes(b"hepta.v13.text-payload.8192.v1").into_array()
    }
    pub fn state_schema_digest() -> [u8; 32] {
        Digest32::of_bytes(b"hepta.v13.frozen-empty-runtime-state.v1").into_array()
    }
    pub fn output_schema_digest() -> [u8; 32] {
        Digest32::of_bytes(b"hepta.v13.task-output-json-line.v1").into_array()
    }
    pub fn observed_device_digest() -> Result<[u8; 32], CellGenerationErrorV2> {
        Ok(Digest32::of_parts(&[
            b"hepta.v13.linux-device-profile.v1\0",
            &JointGenerationProcessWorkerV1::observed_device_digest()?,
        ])
        .into_array())
    }

    /// Actual held descriptors, for the admitting host's before-write owner
    /// separation check. This is not a pathname check or adoption reference.
    pub fn asset_file_identities(&self) -> Result<Vec<(u64, u64)>, CellGenerationErrorV2> {
        self.files.identities()
    }

    /// Persist once in the existing task journal before exposing the service.
    /// Reopening and repeating actual asset checks creates a new observation.
    pub fn preparation_cost(
        &self,
        identity: CellTaskCostIdentityV2,
    ) -> Result<CellCostEntryV2, CellGenerationErrorV2> {
        if identity.source_digest != self.config.source_digest {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(CellCostEntryV2 {
            event_id: self.preparation_event,
            identity,
            stage: CellCostStageV2::Codec,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(self.preparation_wall_micros),
                ..CellCostMetricsV2::default()
            },
        })
    }

    pub fn validate_manifest(
        &self,
        manifest: &CellBackendManifestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        manifest.digest()?;
        let CellLearningBindingV2::Resumable { weights, .. } = &self.config.closure.learning else {
            return Err(CellGenerationErrorV2::InvalidBinding);
        };
        if manifest.profile != Self::PROFILE
            || manifest.source_digest != self.config.source_digest
            || manifest.bundle_digest != self.bundle_digest
            || manifest.runtime_digest != self.runtime_digest
            || manifest.device_digest != self.config.device_digest
            || manifest.encoder != Some(self.config.closure.encoder_digest)
            || manifest.head != Some(*weights)
            || manifest.memory.is_some()
            || manifest.world_model.is_some()
            || manifest.decoder.is_some()
            || manifest.learning != self.config.closure.learning
            || manifest.input_schema != Self::input_schema_digest()
            || manifest.state_schema != Self::state_schema_digest()
            || manifest.output_schema != Self::output_schema_digest()
            || manifest.max_input_bytes > 8192
            || manifest.max_state_bytes != 1
            || manifest.max_step_cost_entries < 8
            || Self::observed_device_digest()? != self.config.device_digest
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(())
    }
}

struct Step<'a> {
    worker: &'a V13GenerationProcessWorkerV1,
    manifest: &'a CellBackendManifestV2,
    request: &'a CellGenerationRequestV2,
    cancellation: &'a AtomicBool,
    deadline: u64,
    started: Instant,
    process_wall: u64,
    cost: CellTaskCostV2,
}

impl Step<'_> {
    fn phase(
        &mut self,
        phase: Phase,
        task: Option<&V13TaskInputV1>,
    ) -> Result<(ProcessObservation, Option<PhaseResponse>), CellGenerationErrorV2> {
        let worker = self.worker;
        let payload = cell_v13_protocol::payload(PhasePayload {
            phase,
            request_digest: self.request.digest()?,
            closure: &worker.config.closure,
            task,
            admitted_at_micros: self.request.admitted_at_micros,
            deadline_micros: self.deadline,
            cpu_seconds: worker.config.phase_cpu_seconds,
            address_space_bytes: worker.config.address_space_bytes,
            assets: &worker.files.assets,
        })?;
        let observed = cell_v13_process::run(ProcessRequest {
            executable: &worker.files.interpreter,
            executable_digest: worker.config.interpreter_digest,
            interpreter_argv0: &worker.config.interpreter_argv0,
            script: &worker.files.script,
            payload,
            cancellation: self.cancellation,
            deadline_micros: self.deadline,
            clock: worker.clock.as_ref(),
            wall_limit: worker
                .config
                .wall_limit
                .saturating_sub(self.started.elapsed()),
        })?;
        self.process_wall = self
            .process_wall
            .checked_add(observed.wall_micros)
            .ok_or(CellGenerationErrorV2::Capacity)?;
        let response = cell_v13_protocol::response(&observed.stdout, phase, self.request.digest()?)
            .ok()
            .filter(|value| {
                value.wall_micros <= observed.wall_micros
                    && value.cpu_micros <= (worker.config.phase_cpu_seconds + 1) * 1_000_000
                    && value.limits_within(
                        worker.config.phase_cpu_seconds,
                        worker.config.address_space_bytes,
                    )
            });
        let mut allocated_wall = 0_u64;
        let mut allocated_cpu = 0_u64;
        if let Some(value) = &response {
            for (index, entry) in value.phases.iter().enumerate() {
                allocated_wall += entry.wall_micros;
                allocated_cpu += entry.cpu_micros;
                self.record(
                    format!("infer-{index}"),
                    match entry.stage.as_str() {
                        "encoder" => CellCostStageV2::Encoder,
                        "codec" => CellCostStageV2::Codec,
                        _ => CellCostStageV2::Inference,
                    },
                    CellCostOutcomeV2::Succeeded,
                    CellCostMetricsV2 {
                        wall_micros: Some(entry.wall_micros),
                        cpu_micros: Some(entry.cpu_micros),
                        communication_bytes: Some(0),
                        ..CellCostMetricsV2::default()
                    },
                )?;
            }
        }
        self.record(
            phase.name().to_owned(),
            if phase == Phase::Verify {
                CellCostStageV2::Codec
            } else {
                CellCostStageV2::Inference
            },
            match terminal_status(&observed.status, response.as_ref(), phase) {
                Some(
                    CellGenerationDispositionV2::Cancelled
                    | CellGenerationDispositionV2::DeadlineExceeded,
                ) => CellCostOutcomeV2::Cancelled,
                Some(CellGenerationDispositionV2::Rejected) => CellCostOutcomeV2::Rejected,
                Some(_) => CellCostOutcomeV2::Failed,
                None => {
                    if response.as_ref().is_some_and(|value| {
                        ["verified", "succeeded"].contains(&value.status.as_str())
                    }) {
                        CellCostOutcomeV2::Succeeded
                    } else {
                        CellCostOutcomeV2::Failed
                    }
                }
            },
            CellCostMetricsV2 {
                wall_micros: Some(observed.wall_micros - allocated_wall),
                cpu_micros: response
                    .as_ref()
                    .map(|value| value.cpu_micros - allocated_cpu),
                communication_bytes: Some(observed.communication_bytes),
                ..CellCostMetricsV2::default()
            },
        )?;
        Ok((observed, response))
    }

    fn record(
        &mut self,
        name: String,
        stage: CellCostStageV2,
        outcome: CellCostOutcomeV2,
        metrics: CellCostMetricsV2,
    ) -> Result<(), CellGenerationErrorV2> {
        self.cost
            .record(CellCostEntryV2 {
                event_id: Digest32::of_parts(&[
                    b"hepta.v13.task-cost.v1\0",
                    &self.request.digest()?,
                    name.as_bytes(),
                ])
                .into_array(),
                identity: self.cost.identity(),
                stage,
                outcome,
                accounting: CellCostAccountingV2::Exclusive,
                metrics,
            })
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        Ok(())
    }

    fn finish(
        mut self,
        disposition: CellGenerationDispositionV2,
        output_delta: Vec<u8>,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        let wall = elapsed_micros(self.started)?
            .checked_sub(self.process_wall)
            .ok_or(CellGenerationErrorV2::InvalidBinding)?;
        self.record(
            "host".into(),
            CellCostStageV2::Codec,
            match disposition {
                CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped => {
                    CellCostOutcomeV2::Succeeded
                }
                CellGenerationDispositionV2::Cancelled
                | CellGenerationDispositionV2::DeadlineExceeded => CellCostOutcomeV2::Cancelled,
                CellGenerationDispositionV2::Rejected => CellCostOutcomeV2::Rejected,
                CellGenerationDispositionV2::Failed => CellCostOutcomeV2::Failed,
            },
            CellCostMetricsV2 {
                wall_micros: Some(wall),
                communication_bytes: Some(0),
                ..CellCostMetricsV2::default()
            },
        )?;
        Ok(CellGenerationProposalV2 {
            request_digest: self.request.digest()?,
            bundle_digest: self.manifest.bundle_digest,
            runtime_digest: self.manifest.runtime_digest,
            device_digest: self.manifest.device_digest,
            successor_state: self.request.predecessor.state.clone(),
            output_delta,
            disposition,
            cost: self.cost,
        })
    }
}

impl CellGenerationWorkerV2 for V13GenerationProcessWorkerV1 {
    fn execute(
        &self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
        cancellation: &AtomicBool,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        let started = Instant::now();
        self.validate_manifest(manifest)?;
        let now = (self.clock)();
        if now == 0
            || now < request.admitted_at_micros
            || request.predecessor.manifest_digest != manifest.digest()?
            || !request.predecessor.state.is_empty()
            || request.predecessor.stopped
            || request.source_frontier != self.config.closure.source_version
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let deadline = now
            .checked_add(
                u64::try_from(self.config.wall_limit.as_micros())
                    .map_err(|_| CellGenerationErrorV2::Capacity)?,
            )
            .ok_or(CellGenerationErrorV2::Capacity)?
            .min(request.deadline_micros);
        let mut step = Step {
            worker: self,
            manifest,
            request,
            cancellation,
            deadline,
            started,
            process_wall: 0,
            cost: CellTaskCostV2::new(CellTaskCostIdentityV2 {
                task_digest: request.task_digest,
                source_digest: manifest.source_digest,
            })
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
        };
        let task = serde_json::from_slice::<V13TaskInputV1>(&request.input)
            .ok()
            .filter(|task| {
                task.encode().is_ok() && request.input.len() <= manifest.max_input_bytes as usize
            });
        let Some(task) = task else {
            return step.finish(CellGenerationDispositionV2::Rejected, Vec::new());
        };
        let (observed, response) = step.phase(Phase::Verify, None)?;
        if let Some(status) = terminal_status(&observed.status, response.as_ref(), Phase::Verify) {
            return step.finish(status, Vec::new());
        }
        if response
            .as_ref()
            .is_none_or(|value| cell_v13_protocol::verified(value, &self.config.closure).is_err())
        {
            return step.finish(CellGenerationDispositionV2::Rejected, Vec::new());
        }
        let (observed, response) = step.phase(Phase::Infer, Some(&task))?;
        if let Some(status) = terminal_status(&observed.status, response.as_ref(), Phase::Infer) {
            return step.finish(status, Vec::new());
        }
        let output = response
            .as_ref()
            .and_then(|value| {
                cell_v13_protocol::output(value, request.digest().ok()?, &self.config.closure).ok()
            })
            .filter(|bytes| {
                bytes.len() <= manifest.max_delta_bytes as usize
                    && request
                        .predecessor
                        .prefix
                        .len()
                        .checked_add(bytes.len())
                        .is_some_and(|length| length <= manifest.max_prefix_bytes as usize)
            });
        match output {
            Some(bytes) => step.finish(CellGenerationDispositionV2::Advanced, bytes),
            None => step.finish(CellGenerationDispositionV2::Failed, Vec::new()),
        }
    }
}
