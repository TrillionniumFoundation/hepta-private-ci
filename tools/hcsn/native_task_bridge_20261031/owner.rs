//! Actual current-main NeuronRuntime owns native state and its independent durable witness.
use crate::config::configuration;
use crate::contract::*;
use crate::model::load;
use crate::model::FrozenModel;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Serialize;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Instant;

fn private_file(path: &Path) -> Result<File, String> {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|error| error.to_string())?;
    if !file
        .metadata()
        .map_err(|error| error.to_string())?
        .is_file()
    {
        return Err("native owner requires regular files".into());
    }
    Ok(file)
}

#[derive(Serialize)]
pub struct Receipt {
    pub numeric_contract: &'static str,
    pub deployment_identity_sha256: String,
    pub schema: &'static str,
    pub sequence: u64,
    pub action: &'static str,
    pub action_index: usize,
    pub q_values: [f64; 4],
    pub checkpoint_before: String,
    pub checkpoint_after: String,
    pub external_cell_snapshot_sha256: String,
    pub external_public_state_sha256: String,
    pub model_sha256: String,
    pub native_source_digest: &'static str,
    pub model_runtime_digest: String,
    pub native_execution_micros: u64,
    pub model_execution_micros: u64,
    pub adapter_wall_micros: u64,
    pub journal_bytes_written: u64,
    pub checkpoint_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub native_abstain: bool,
    pub native_physics_executed: bool,
    pub production_activation: bool,
    pub authority: &'static str,
}

pub struct Owner {
    runtime: NeuronRuntime<FileAnchorWitnessStore>,
    model: FrozenModel,
    run_id: String,
    objective: Digest32,
    sequence: u64,
}

impl Owner {
    pub fn open(
        root: &Path,
        bytes: &[u8],
        run_id: &str,
        objective: &str,
        expected_sequence: u64,
        expected_checkpoint: &str,
    ) -> Result<Self, String> {
        let (checkpoint, model_digest) = load(bytes)?;
        let objective = digest(objective)?;
        if objective.is_zero() || root.is_symlink() || !root.is_dir() {
            return Err("invalid objective or owner directory".into());
        }
        let (native, config) = configuration(model_digest, checkpoint.norm.mean.len())?;
        let subject = id(run_id)?;
        let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
        let length = u32::try_from(subject.as_str().len()).map_err(|error| error.to_string())?;
        scope_bytes.extend_from_slice(&length.to_be_bytes());
        scope_bytes.extend_from_slice(subject.as_str().as_bytes());
        let scope = JournalScope {
            scope_digest: Digest32::of_bytes(&scope_bytes),
            objective_digest: objective,
        };
        let witness = FileAnchorWitnessStore::open(
            private_file(&root.join("witness.bin"))?,
            scope,
            Generation::new(1).map_err(|error| error.to_string())?,
            LIMIT,
        )
        .map_err(|error| error.to_string())?;
        let prior = witness.current().map_err(|error| error.to_string())?;
        if prior.map_or(0, |anchor| anchor.sequence) != expected_sequence
            || prior.map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest)
                != digest(expected_checkpoint)?
        {
            return Err("externally acknowledged frontier mismatch".into());
        }
        let journal = private_file(&root.join("journal.bin"))?;
        let runtime = match prior {
            None => {
                NeuronRuntime::bootstrap(journal, native, scope, LIMIT, config.clone(), witness)
            }
            Some(anchor) => NeuronRuntime::recover(
                journal,
                native,
                scope,
                LIMIT,
                config.clone(),
                anchor,
                witness,
            ),
        }
        .map_err(|error| error.to_string())?;
        if runtime
            .current_anchor()
            .map_err(|error| error.to_string())?
            != prior
        {
            return Err("unreconciled committed native suffix".into());
        }
        Ok(Self {
            runtime,
            model: FrozenModel {
                checkpoint,
                config,
                checkpoint_bytes: bytes.len(),
                last_scores: None,
            },
            run_id: run_id.into(),
            objective,
            sequence: expected_sequence,
        })
    }

    pub fn tick(&mut self, request: Request) -> Result<Receipt, String> {
        let start = Instant::now();
        if request.sequence != self.sequence + 1
            || digest(&request.model_sha256)? != self.model.config.weights_digest
        {
            return Err("sequence or frozen model identity mismatch".into());
        }
        let packed = request.packed(self.model.checkpoint.norm.mean.len())?;
        let input = NeuronTickInputV1 {
            tick_id: id(&format!("task.native.{}", request.sequence))?,
            subject_id: id(&self.run_id)?,
            logical_sequence: request.sequence,
            monotonic_time_micros: request.monotonic_time_micros,
            checkpoint_digest: digest(&request.checkpoint_before)?,
            input_feature_digest: canonical_feature_vector_digest_v1(&packed),
            feature_vector_q24: packed,
            objective_digest: self.objective,
            ndu_snapshot_digest: request.evidence_digest()?,
            body_generation: Some(1),
            modulator_digest: None,
        };
        let output = self
            .runtime
            .tick(&mut self.model, input)
            .map_err(|error| error.to_string())?;
        self.sequence = request.sequence;
        let active = &output.tick.active_indices;
        if active.len() != 1 || active[0] >= 4 || !request.feasible[active[0] as usize] {
            return Err("native activation violated action contract after durable commit".into());
        }
        let action_index = active[0] as usize;
        let resources = output.tick.resource_receipt;
        Ok(Receipt {
            numeric_contract: NUMERIC_CONTRACT,
            deployment_identity_sha256: deployment_digest(self.model.config.weights_digest)
                .to_string(),
            schema: "hepta.task.native-bridge.receipt.v2",
            sequence: request.sequence,
            action: ACTIONS[action_index],
            action_index,
            q_values: self
                .model
                .last_scores
                .ok_or("missing executed model scores")?,
            checkpoint_before: output.tick.checkpoint_before.to_string(),
            checkpoint_after: output.tick.checkpoint_after.to_string(),
            external_cell_snapshot_sha256: request.cell_snapshot_sha256,
            external_public_state_sha256: request.public_state_sha256,
            model_sha256: request.model_sha256,
            native_source_digest: env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST"),
            model_runtime_digest: output.signal.model_runtime_digest.to_string(),
            native_execution_micros: resources.execution_micros,
            model_execution_micros: output.model_runtime.latency_micros,
            adapter_wall_micros: start.elapsed().as_micros().try_into().unwrap_or(u64::MAX),
            journal_bytes_written: resources.journal_bytes_written,
            checkpoint_bytes: resources.checkpoint_bytes,
            transient_allocation_bytes: resources.transient_allocation_bytes,
            native_abstain: output.signal.abstain,
            native_physics_executed: false,
            production_activation: false,
            authority: "DENY_ALL",
        })
    }
}
