//! Actual JointGenerator process adapter. Assets are host-bound immutable bytes;
//! the model process never receives a session directory or output destination.

use std::collections::BTreeMap;
use std::fs::File;
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

#[path = "cell_joint_assets.rs"]
mod assets;
pub use assets::JointGenerationProcessFilesV1;
use assets::read_bounded;

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
    pub const OBSERVED_PROFILE: &'static str = "joint-generator-proposal-linux-v2";
    pub const LOADED_PROFILE: &'static str =
        codex_hepta_infer_core::JOINT_V4_LOADING_PROCESS_PROFILE;

    pub fn observed_input_schema_digest() -> [u8; 32] {
        Digest32::of_bytes(b"hepta.joint.owner-bound-public-command.v2").into_array()
    }

    pub fn observed_state_schema_digest() -> [u8; 32] {
        Digest32::of_bytes(codex_hepta_infer_core::JOINT_V4_STATE_SCHEMA).into_array()
    }

    pub fn observed_output_schema_digest() -> [u8; 32] {
        Digest32::of_bytes(codex_hepta_infer_core::JOINT_V4_OUTPUT_SCHEMA).into_array()
    }

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

    /// The full-loading profile uses the actual encoder component. The other
    /// aggregate manifest slots retain their explicitly opaque asset aliases;
    /// the complete thirteen-component binding is carried by the load event.
    pub fn loaded_encoder_digest(&self) -> Result<[u8; 32], CellGenerationErrorV2> {
        Ok(
            crate::inspect_joint_v4_generation_weights_v1(&self.weights)?
                .components()
                .encoder
                .into_array(),
        )
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

    /// Check the selected content, runtime, schema and observed device pins.
    /// Successful validation grants no adoption or publication authority.
    pub fn validate_manifest(
        &self,
        manifest: &CellBackendManifestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        manifest.digest()?;
        let loading = manifest.profile == Self::LOADED_PROFILE;
        let observed = loading || manifest.profile == Self::OBSERVED_PROFILE;
        let encoder = if loading {
            self.loaded_encoder_digest()?
        } else {
            self.encoder_digest()
        };
        let schemas = if observed {
            (
                Self::observed_input_schema_digest(),
                Self::observed_state_schema_digest(),
                Self::observed_output_schema_digest(),
            )
        } else {
            (
                Self::input_schema_digest(),
                Self::state_schema_digest(),
                Self::output_schema_digest(),
            )
        };
        if ![Self::PROFILE, Self::OBSERVED_PROFILE, Self::LOADED_PROFILE]
            .contains(&manifest.profile.as_str())
            || manifest.source_digest != self.source_digest
            || manifest.runtime_digest != self.executable_digest
            || manifest.device_digest != self.device_digest
            || (
                manifest.input_schema,
                manifest.state_schema,
                manifest.output_schema,
            ) != schemas
            || manifest.encoder != Some(encoder)
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
        let loading = manifest.profile == Self::LOADED_PROFILE;
        let loading_commitment = if loading {
            let inspection = crate::inspect_joint_v4_generation_weights_v1(&self.weights)?;
            Some(
                codex_hepta_infer_core::joint_v4_loading_commitment_v1(
                    inspection.physical_weights_digest().into_array(),
                    inspection.components(),
                )
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
            )
        } else {
            None
        };
        let payload = if loading || manifest.profile == Self::OBSERVED_PROFILE {
            let input =
                match serde_json::from_slice::<crate::JointGenerationInputV2>(&request.input) {
                    Ok(value) if value.public_digest == self.public_digest => value,
                    _ => {
                        return unstarted_proposal(
                            manifest,
                            request,
                            started,
                            CellGenerationDispositionV2::Rejected,
                        );
                    }
                };
            crate::cell_joint_observed::request_bytes(
                request,
                &input,
                &self.weights,
                &self.public,
                (self.clock)(),
            )
        } else {
            let input = match serde_json::from_slice::<JointGenerationInputV1>(&request.input) {
                Ok(value) if value.public_digest == self.public_digest => value,
                _ => {
                    return unstarted_proposal(
                        manifest,
                        request,
                        started,
                        CellGenerationDispositionV2::Rejected,
                    );
                }
            };
            cell_joint_protocol::request_bytes(
                request_digest,
                &self.weights,
                &self.public,
                &request.predecessor.state,
                &request.predecessor.prefix,
                &input.command,
            )
        };
        let mut payload = match payload {
            Ok(value) => value,
            Err(CellGenerationErrorV2::Deadline) => {
                return unstarted_proposal(
                    manifest,
                    request,
                    started,
                    CellGenerationDispositionV2::DeadlineExceeded,
                );
            }
            Err(_) => {
                return unstarted_proposal(
                    manifest,
                    request,
                    started,
                    CellGenerationDispositionV2::Rejected,
                );
            }
        };
        if loading {
            payload[..8].copy_from_slice(b"HJREQV03");
        }
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
                            proposal.loading_commitment == loading_commitment
                                && proposal.state.len() <= manifest.max_state_bytes as usize
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
            crate::cell_joint_loading::record_child_phases(
                &mut cost,
                manifest,
                request_digest,
                loading_commitment,
                phase_micros,
            )?;
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

fn unstarted_proposal(
    manifest: &CellBackendManifestV2,
    request: &CellGenerationRequestV2,
    started: Instant,
    disposition: CellGenerationDispositionV2,
) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
    let (event_domain, outcome): (&[u8], _) = match disposition {
        CellGenerationDispositionV2::Rejected => (
            b"hepta.joint.rejected-input.v1\0",
            CellCostOutcomeV2::Rejected,
        ),
        CellGenerationDispositionV2::DeadlineExceeded => (
            b"hepta.joint.unstarted-deadline.v2\0",
            CellCostOutcomeV2::Cancelled,
        ),
        _ => return Err(CellGenerationErrorV2::InvalidBinding),
    };
    let request_digest = request.digest()?;
    let identity = CellTaskCostIdentityV2 {
        task_digest: request.task_digest,
        source_digest: manifest.source_digest,
    };
    let mut cost =
        CellTaskCostV2::new(identity).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    cost.record(CellCostEntryV2 {
        event_id: Digest32::of_parts(&[event_domain, &request_digest]).into_array(),
        identity,
        stage: CellCostStageV2::Codec,
        outcome,
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
        disposition,
        cost,
    })
}

#[cfg(test)]
#[path = "cell_joint_generation_tests.rs"]
mod tests;
