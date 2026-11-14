//! Actual retained model assets and ordinary Fleet identities for this run.

use std::fs::File;
use std::path::Path;
use std::time::Duration;

use anyhow::Result;
use codex_hepta_agentd::*;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;

use super::super::descriptor;
use super::super::lifecycle::owner_files;

pub(super) struct Assets {
    pub input: descriptor::Descriptor,
    pub digest: Digest32,
    pub prepared: AgentdV13GenerationWorkerV1,
    retained: [File; 2],
}

impl Assets {
    pub fn load(path: &Path, expected: Digest32) -> Result<Self> {
        let descriptor::Input {
            descriptor,
            digest,
            files,
            retained,
        } = descriptor::load(path, expected)?;
        let prepared = prepare_agentd_v13_generation_worker_v1(
            V13GenerationProcessConfigV1 {
                interpreter_argv0: descriptor.interpreter_argv0.clone(),
                interpreter_digest: descriptor.interpreter.sha256.into_array(),
                worker_digest: descriptor.worker.sha256.into_array(),
                source_digest: descriptor.source_digest,
                device_digest: V13GenerationProcessWorkerV1::observed_device_digest()?,
                closure: descriptor.closure.clone(),
                phase_cpu_seconds: 15,
                address_space_bytes: 4 * 1024_u64.pow(3),
                wall_limit: Duration::from_secs(60),
            },
            files,
        )?;
        Ok(Self {
            input: descriptor,
            digest,
            prepared,
            retained,
        })
    }

    pub fn configuration(
        &self,
        identity: &AgentdIdentity,
        task: &V13TaskInputV1,
        generation: u64,
    ) -> Result<AgentdV13GenerationBootstrapConfigV1> {
        let CellLearningBindingV2::Resumable { weights, .. } = &self.input.closure.learning else {
            anyhow::bail!("complete actual learning state required");
        };
        let manifest = CellBackendManifestV2 {
            profile: V13GenerationProcessWorkerV1::PROFILE.into(),
            source_digest: self.input.source_digest,
            bundle_digest: self.prepared.worker().bundle_digest(),
            encoder: Some(self.input.closure.encoder_digest),
            head: Some(*weights),
            memory: None,
            world_model: None,
            decoder: None,
            runtime_digest: self.prepared.worker().runtime_digest(),
            device_digest: V13GenerationProcessWorkerV1::observed_device_digest()?,
            input_schema: V13GenerationProcessWorkerV1::input_schema_digest(),
            state_schema: V13GenerationProcessWorkerV1::state_schema_digest(),
            output_schema: V13GenerationProcessWorkerV1::output_schema_digest(),
            learning: self.input.closure.learning.clone(),
            evolution: self.input.evolution.clone(),
            max_input_bytes: 8192,
            max_state_bytes: 1,
            max_delta_bytes: 65_536,
            max_prefix_bytes: 65_536,
            max_step_cost_entries: 8,
            max_ack_cost_entries: 1,
        };
        Ok(AgentdV13GenerationBootstrapConfigV1 {
            expected_identity_digest: neuron_generation_process_identity_digest_v1(identity)?,
            expected_boot_id_digest: self.prepared.boot_id_digest(),
            generation: CellGenerationConfigV2 {
                initial: CellRuntimeSnapshotV2 {
                    scope: CellGenerationScopeV2 {
                        principal_digest: Digest32::of_parts(&[
                            b"hepta.v13.guarded-qualification.v1\0",
                            self.digest.as_array(),
                        ])
                        .into_array(),
                        agent_id: identity.agent_id.to_string(),
                        cell_id: "v13-guarded-qualification".into(),
                        run_id: format!("{}-{generation}", self.digest),
                    },
                    manifest_digest: manifest.digest()?,
                    generation,
                    writer_epoch: generation,
                    revision: 0,
                    state: Vec::new(),
                    prefix: Vec::new(),
                    stopped: false,
                },
                manifest,
                source_frontier: self.input.closure.source_version,
                task_digest: Digest32::of_bytes(&task.encode()?).into_array(),
            },
            max_records: 128,
            control_capacity: 16,
            queue_capacity: 4,
            rpc_timeout: Duration::from_secs(1),
        })
    }

    pub fn inputs<'a>(
        &'a self,
        identity: &'a AgentdIdentity,
        config: AgentdV13GenerationBootstrapConfigV1,
        root: &Path,
        mode: V13GenerationOwnerModeV1,
    ) -> Result<AgentdV13GenerationUpdateInputsV1<'a>> {
        Ok(AgentdV13GenerationUpdateInputsV1 {
            identity,
            config,
            files: owner_files(root, mode, &self.retained)?,
            prepared: &self.prepared,
        })
    }
}
