//! Actual JointGenerator process adapter. Assets are host-bound immutable bytes;
//! the model process never receives a session directory or output destination.

use std::collections::BTreeMap;
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
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
use crate::CellLearningBindingV2;
use crate::CellTaskCostIdentityV2;
use crate::CellTaskCostV2;
use crate::cell_generation_control::CellGenerationWorkerV2;
use crate::cell_joint_process;
use crate::cell_joint_process::ProcessRequest;
use crate::cell_joint_process::ProcessStatus;
use crate::cell_joint_protocol;
use crate::cell_joint_protocol::JointGenerationInputV1;
use crate::cell_joint_protocol::MAX_PUBLIC_BYTES;
use crate::cell_joint_protocol::MAX_WEIGHTS_BYTES;

/// These paths are supplied by the admitted host, never by a generation input.
/// The source digest is the host's artifact/source binding; executable, weights,
/// public bytes and observed device profile are also checked independently here.
pub struct JointGenerationProcessConfigV1 {
    pub executable: PathBuf,
    pub executable_digest: [u8; 32],
    pub source_digest: [u8; 32],
    pub weights: PathBuf,
    pub weights_digest: [u8; 32],
    pub public: PathBuf,
    pub public_digest: [u8; 32],
    pub device_digest: [u8; 32],
}

pub struct JointGenerationProcessWorkerV1 {
    executable: File,
    executable_digest: [u8; 32],
    source_digest: [u8; 32],
    weights: Vec<u8>,
    weights_digest: [u8; 32],
    public: Vec<u8>,
    public_digest: [u8; 32],
    device_digest: [u8; 32],
    clock: Arc<dyn Fn() -> u64 + Send + Sync>,
}

impl JointGenerationProcessWorkerV1 {
    pub const PROFILE: &'static str = "joint-generator-proposal-linux-v1";

    pub fn input_schema_digest() -> [u8; 32] {
        Digest32::of_bytes(b"hepta.joint.host-bound-public-command.v1").into_array()
    }

    pub fn state_schema_digest() -> [u8; 32] {
        Digest32::of_bytes(b"hepta.joint.complete-proposal-state.v1").into_array()
    }

    pub fn output_schema_digest() -> [u8; 32] {
        Digest32::of_bytes(b"hepta.joint.HGC1-multimodal-prefix.v1").into_array()
    }

    pub fn encoder_digest(&self) -> [u8; 32] {
        self.component_digest(b"encoder")
    }

    pub fn head_digest(&self) -> [u8; 32] {
        self.component_digest(b"head")
    }

    pub fn memory_digest(&self) -> [u8; 32] {
        self.component_digest(b"recurrent-state")
    }

    pub fn decoder_digest(&self) -> [u8; 32] {
        self.component_digest(b"decoder")
    }

    fn component_digest(&self, component: &[u8]) -> [u8; 32] {
        Digest32::of_parts(&[
            b"hepta.joint.component.v1\0",
            component,
            &self.source_digest,
            &self.executable_digest,
            &self.weights_digest,
        ])
        .into_array()
    }

    /// A capability profile observed on this Linux host, not a unique hardware
    /// serial number or proof of artifact adoption. Kernel and CPU feature drift
    /// require a new explicit binding; CPU frequency is deliberately excluded.
    pub fn observed_device_digest() -> Result<[u8; 32], CellGenerationErrorV2> {
        let cpu = read_bounded(Path::new("/proc/cpuinfo"), 1024 * 1024)?;
        let cpu = std::str::from_utf8(&cpu).map_err(|_| CellGenerationErrorV2::Unavailable)?;
        let mut fields = BTreeMap::new();
        for line in cpu
            .split("\n\n")
            .next()
            .ok_or(CellGenerationErrorV2::Unavailable)?
            .lines()
        {
            if let Some((key, value)) = line.split_once(':') {
                let key = key.trim();
                if [
                    "vendor_id",
                    "cpu family",
                    "model",
                    "model name",
                    "stepping",
                    "microcode",
                    "flags",
                    "CPU implementer",
                    "CPU part",
                    "CPU revision",
                    "Features",
                ]
                .contains(&key)
                {
                    fields.insert(key, value.trim());
                }
            }
        }
        if fields.is_empty() {
            return Err(CellGenerationErrorV2::Unavailable);
        }
        let kernel = read_bounded(Path::new("/proc/sys/kernel/osrelease"), 4096)?;
        let descriptor =
            serde_json::to_vec(&(std::env::consts::OS, std::env::consts::ARCH, fields, kernel))
                .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        Ok(
            Digest32::of_parts(&[b"hepta.joint.linux-device-profile.v1\0", &descriptor])
                .into_array(),
        )
    }

    /// Open and fingerprint the selected artifacts once. The public and weight
    /// packets are then passed by bytes, so later path replacement cannot change
    /// a run's assets. The clock must use the same epoch as its Agentd owner.
    pub fn open(
        config: JointGenerationProcessConfigV1,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>,
    ) -> Result<Self, CellGenerationErrorV2> {
        if [
            config.executable_digest,
            config.source_digest,
            config.weights_digest,
            config.public_digest,
            config.device_digest,
        ]
        .contains(&[0; 32])
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let executable =
            File::open(&config.executable).map_err(|_| CellGenerationErrorV2::Unavailable)?;
        let weights = read_bounded(&config.weights, MAX_WEIGHTS_BYTES)?;
        let public = read_bounded(&config.public, MAX_PUBLIC_BYTES)?;
        if cell_joint_process::executable_digest(&executable)? != config.executable_digest
            || Digest32::of_bytes(&weights).into_array() != config.weights_digest
            || Digest32::of_bytes(&public).into_array() != config.public_digest
            || Self::observed_device_digest()? != config.device_digest
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(Self {
            executable,
            executable_digest: config.executable_digest,
            source_digest: config.source_digest,
            weights,
            weights_digest: config.weights_digest,
            public,
            public_digest: config.public_digest,
            device_digest: config.device_digest,
            clock,
        })
    }

    fn validate_manifest(
        &self,
        manifest: &CellBackendManifestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        manifest.digest()?;
        if manifest.profile != Self::PROFILE
            || manifest.source_digest != self.source_digest
            || manifest.runtime_digest != self.executable_digest
            || manifest.device_digest != self.device_digest
            || manifest.input_schema != Self::input_schema_digest()
            || manifest.state_schema != Self::state_schema_digest()
            || manifest.output_schema != Self::output_schema_digest()
            || manifest.encoder != Some(self.encoder_digest())
            || manifest.head != Some(self.head_digest())
            || manifest.memory != Some(self.memory_digest())
            || manifest.world_model.is_some()
            || manifest.decoder != Some(self.decoder_digest())
            || manifest.learning
                != (CellLearningBindingV2::Frozen {
                    weights: self.weights_digest,
                })
            || manifest.max_state_bytes != 65_536
            || manifest.max_delta_bytes != 65_536
            || manifest.max_prefix_bytes < 65_536
            || manifest.max_step_cost_entries < 7
            || Self::observed_device_digest()? != self.device_digest
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(())
    }
}

impl CellGenerationWorkerV2 for JointGenerationProcessWorkerV1 {
    fn execute(
        &self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
        cancellation: &AtomicBool,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        let started = Instant::now();
        self.validate_manifest(manifest)?;
        let request_digest = request.digest()?;
        if request.predecessor.manifest_digest != manifest.digest()?
            || request.input.len() > manifest.max_input_bytes as usize
            || request.predecessor.state.len() > manifest.max_state_bytes as usize
            || request.predecessor.prefix.len() > manifest.max_prefix_bytes as usize
            || request.predecessor.stopped
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let input = match serde_json::from_slice::<JointGenerationInputV1>(&request.input) {
            Ok(value) => value,
            Err(_) => return rejected_input(manifest, request, started),
        };
        if input.public_digest != self.public_digest {
            return rejected_input(manifest, request, started);
        }
        let payload = match cell_joint_protocol::request_bytes(
            request_digest,
            &self.weights,
            &self.public,
            &request.predecessor.state,
            &request.predecessor.prefix,
            &input.command,
        ) {
            Ok(value) => value,
            Err(_) => return rejected_input(manifest, request, started),
        };
        let observation = cell_joint_process::run(ProcessRequest {
            executable: &self.executable,
            executable_digest: self.executable_digest,
            payload,
            cancellation,
            deadline_micros: request.deadline_micros,
            clock: self.clock.as_ref(),
        })?;
        let mut phase_micros = [0; 4];
        let (successor_state, output_delta, disposition) = match observation.status {
            ProcessStatus::Succeeded => {
                let proposal =
                    cell_joint_protocol::read_proposal(&observation.stdout, request_digest)
                        .ok()
                        .filter(|proposal| {
                            proposal.state.len() <= manifest.max_state_bytes as usize
                                && proposal.delta.len() <= manifest.max_delta_bytes as usize
                                && request
                                    .predecessor
                                    .prefix
                                    .len()
                                    .checked_add(proposal.delta.len())
                                    .is_some_and(|length| {
                                        length <= manifest.max_prefix_bytes as usize
                                    })
                                && proposal
                                    .wall_micros
                                    .iter()
                                    .try_fold(0_u64, |sum, value| sum.checked_add(*value))
                                    .is_some_and(|sum| sum <= observation.wall_micros)
                        });
                if let Some(proposal) = proposal {
                    phase_micros = proposal.wall_micros;
                    (
                        proposal.state,
                        proposal.delta,
                        if proposal.stopped {
                            CellGenerationDispositionV2::Stopped
                        } else {
                            CellGenerationDispositionV2::Advanced
                        },
                    )
                } else {
                    // The process and all pipes terminated, but its response was
                    // invalid. Retain measured work as Failed, with no adopted
                    // state/output and no invented child-phase observations.
                    (
                        request.predecessor.state.clone(),
                        Vec::new(),
                        CellGenerationDispositionV2::Failed,
                    )
                }
            }
            ProcessStatus::Failed => (
                request.predecessor.state.clone(),
                Vec::new(),
                CellGenerationDispositionV2::Failed,
            ),
            ProcessStatus::Cancelled => (
                request.predecessor.state.clone(),
                Vec::new(),
                CellGenerationDispositionV2::Cancelled,
            ),
            ProcessStatus::Deadline => (
                request.predecessor.state.clone(),
                Vec::new(),
                CellGenerationDispositionV2::DeadlineExceeded,
            ),
        };
        let phase_sum = phase_micros
            .iter()
            .try_fold(0_u64, |sum, value| sum.checked_add(*value))
            .ok_or(CellGenerationErrorV2::Capacity)?;
        if phase_sum > observation.wall_micros {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let total_micros = cell_joint_process::elapsed_micros(started)?;
        let identity = CellTaskCostIdentityV2 {
            task_digest: request.task_digest,
            source_digest: manifest.source_digest,
        };
        let mut cost =
            CellTaskCostV2::new(identity).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let outcome = match disposition {
            CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped => {
                CellCostOutcomeV2::Succeeded
            }
            CellGenerationDispositionV2::Cancelled
            | CellGenerationDispositionV2::DeadlineExceeded => CellCostOutcomeV2::Cancelled,
            CellGenerationDispositionV2::Failed => CellCostOutcomeV2::Failed,
            CellGenerationDispositionV2::Rejected => CellCostOutcomeV2::Rejected,
        };
        // Successful child phases are disjoint. On failure there is no phase
        // receipt: retain one measured process envelope and unknown subdivisions.
        if matches!(
            disposition,
            CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped
        ) {
            for (index, stage) in [
                CellCostStageV2::Codec,
                CellCostStageV2::Encoder,
                CellCostStageV2::Inference,
                CellCostStageV2::Planning,
            ]
            .into_iter()
            .enumerate()
            {
                cost.record(CellCostEntryV2 {
                    event_id: Digest32::of_parts(&[
                        b"hepta.joint.child-phase.v1\0",
                        &request_digest,
                        &[index as u8],
                    ])
                    .into_array(),
                    identity,
                    stage,
                    outcome,
                    accounting: CellCostAccountingV2::Exclusive,
                    metrics: CellCostMetricsV2 {
                        wall_micros: Some(phase_micros[index]),
                        ..CellCostMetricsV2::default()
                    },
                })
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
            }
        }
        cost.record(CellCostEntryV2 {
            event_id: Digest32::of_parts(&[
                b"hepta.joint.transport-and-control.v1\0",
                &request_digest,
            ])
            .into_array(),
            identity,
            stage: if matches!(
                disposition,
                CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped
            ) {
                CellCostStageV2::Communication
            } else {
                CellCostStageV2::Inference
            },
            outcome,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(
                    total_micros
                        .checked_sub(phase_sum)
                        .ok_or(CellGenerationErrorV2::InvalidBinding)?,
                ),
                communication_bytes: Some(observation.communication_bytes),
                ..CellCostMetricsV2::default()
            },
        })
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        Ok(CellGenerationProposalV2 {
            request_digest,
            bundle_digest: manifest.bundle_digest,
            runtime_digest: self.executable_digest,
            device_digest: self.device_digest,
            successor_state,
            output_delta,
            disposition,
            cost,
        })
    }
}

fn read_bounded(path: &Path, maximum: usize) -> Result<Vec<u8>, CellGenerationErrorV2> {
    let file = File::open(path).map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if !file
        .metadata()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?
        .is_file()
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let mut bytes = Vec::new();
    file.take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if bytes.is_empty() || bytes.len() > maximum {
        return Err(CellGenerationErrorV2::Capacity);
    }
    Ok(bytes)
}

fn rejected_input(
    manifest: &CellBackendManifestV2,
    request: &CellGenerationRequestV2,
    started: Instant,
) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
    let request_digest = request.digest()?;
    let identity = CellTaskCostIdentityV2 {
        task_digest: request.task_digest,
        source_digest: manifest.source_digest,
    };
    let mut cost =
        CellTaskCostV2::new(identity).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    cost.record(CellCostEntryV2 {
        event_id: Digest32::of_parts(&[b"hepta.joint.rejected-input.v1\0", &request_digest])
            .into_array(),
        identity,
        stage: CellCostStageV2::Codec,
        outcome: CellCostOutcomeV2::Rejected,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            wall_micros: Some(cell_joint_process::elapsed_micros(started)?),
            ..CellCostMetricsV2::default()
        },
    })
    .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    Ok(CellGenerationProposalV2 {
        request_digest,
        bundle_digest: manifest.bundle_digest,
        runtime_digest: manifest.runtime_digest,
        device_digest: manifest.device_digest,
        successor_state: request.predecessor.state.clone(),
        output_delta: Vec::new(),
        disposition: CellGenerationDispositionV2::Rejected,
        cost,
    })
}

#[cfg(test)]
#[path = "cell_joint_generation_tests.rs"]
mod tests;
