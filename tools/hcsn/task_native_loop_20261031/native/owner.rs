//! Linux research owner: decide, perform the selected effect, acknowledge once.
use crate::cell::Cell;
use crate::cell::Family;
use crate::content;
use crate::native;
use crate::policy::Controller;
use crate::policy::Policy;
use crate::policy::{self};
use crate::port::nanos;
use crate::port::Costs;
use crate::port::DecisionPort;
use crate::store::Identity;
use crate::store::Pair;
use crate::store::{self};
use crate::task::Action;
use crate::task::Event;
use crate::task::Public;
use crate::task::State;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Serialize;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Debug, Serialize)]
pub struct Receipt {
    pub sequence: u64,
    pub action: Action,
    pub before: State,
    pub after: State,
    pub public_features: Vec<f64>,
    pub cell_features: Option<[f64; 5]>,
    pub q: Option<[f64; 4]>,
    pub legal: [bool; 4],
    pub driver: f64,
    pub horizon_micros: u64,
    pub event: Event,
    pub stage_costs: Costs,
    pub signals_q24: Vec<i64>,
    pub acknowledged_sha256: String,
    pub native_checkpoint: String,
    pub journal_bytes_written: u64,
    pub checkpoint_bytes_written: u64,
    pub owner_nanos: u64,
}

pub struct Owner {
    pub pair: Pair,
    pub acknowledged_sha256: String,
    pub external_ack_verified: bool,
    pub artifact_load_nanos: u64,
    pub public: Public,
    pub policy: Policy,
    cell: Cell,
    content: content::Model,
    folder: PathBuf,
    snapshot: PathBuf,
    runtime: Option<NeuronRuntime<FileAnchorWitnessStore>>,
    bootstrap: Option<Bootstrap>,
    config: NeuronRuntimeConfigV1,
    subject: codex_hepta_types::StableId,
    objective: Digest32,
    poisoned: bool,
}

struct Bootstrap {
    journal: File,
    sparse: SparseConfig,
    scope: JournalScope,
    witness: FileAnchorWitnessStore,
}

pub struct Open<'a> {
    pub public: &'a Path,
    pub content: &'a Path,
    pub policy: &'a Path,
    pub family: Family,
    pub controller: Controller,
    pub snapshot: &'a Path,
    pub ack: Option<&'a str>,
}

impl Owner {
    pub fn open(args: Open<'_>) -> Result<Self, String> {
        let artifact_start = Instant::now();
        let public_bytes = store::read(args.public, 128_000)?;
        let policy_bytes = store::read(args.policy, 1_000_000)?;
        let content_bytes = store::read(args.content, 2_000_000)?;
        let public: Public = serde_json::from_slice(&public_bytes).map_err(|e| e.to_string())?;
        public.validate()?;
        let policy: Policy = serde_json::from_slice(&policy_bytes).map_err(|e| e.to_string())?;
        policy.validate(&public, args.family, args.controller)?;
        let identity = Identity {
            source_digest: env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST").into(),
            public_sha256: store::digest(&public_bytes),
            policy_sha256: store::digest(&policy_bytes),
            content_model_sha256: store::digest(&content_bytes),
            family: args.family,
            controller: args.controller,
        };
        let content = content::Model::load(args.content, &identity.content_model_sha256)?;
        let mut cell = Cell::new(policy.parameters, args.family, policy.seed)?;
        let artifact_load_nanos = nanos(artifact_start);
        let exists = args.snapshot.exists() || args.snapshot.is_symlink();
        if !args.snapshot.parent().is_some_and(Path::is_dir)
            || store::sibling(args.snapshot, ".pending").exists()
        {
            return Err("existing snapshot directory and no incomplete commit required".into());
        }
        let (pair, mut acknowledged_sha256) = if exists {
            let bytes = store::read(args.snapshot, 1_000_000)?;
            let digest = store::digest(&bytes);
            if args.ack.is_some_and(|ack| ack != digest) {
                return Err("external acknowledged digest mismatch".into());
            }
            let pair: Pair = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
            if pair.schema != "hcsn.task.native.pair.v1" || pair.identity != identity {
                return Err("checkpoint source/public/model/policy identity mismatch".into());
            }
            (pair, digest)
        } else {
            if args.ack.is_some() {
                return Err("ack supplied for absent checkpoint".into());
            }
            (
                Pair {
                    schema: "hcsn.task.native.pair.v1".into(),
                    identity: identity.clone(),
                    sequence: 0,
                    native_checkpoint: Digest32::ZERO.to_string(),
                    task: State::initial(&public),
                    cell: cell.snapshot(),
                    content: content::State::new(&content),
                },
                String::new(),
            )
        };
        pair.task.validate(&public, policy.confusion)?;
        if pair.sequence != pair.task.history.len() as u64 {
            return Err("task sequence mismatch".into());
        }
        cell.restore(&pair.cell)?;
        let direct = policy.controller == Controller::DirectFixed;
        if (!direct
            && (cell.sequence != pair.sequence || cell.elapsed_micros != pair.task.elapsed_micros))
            || (direct && (cell.sequence != 0 || cell.elapsed_micros != 0))
        {
            return Err("task/cell clock frontier mismatch".into());
        }
        pair.content.validate(&content, pair.sequence)?;
        if pair.content.completed_reads != pair.task.counts.content_invocations {
            return Err("task/content completed-read mismatch".into());
        }
        if let Some(last) = &pair.content.last {
            let event = pair
                .task
                .history
                .iter()
                .rev()
                .find(|e| e.action == Action::Read && e.error.is_none())
                .ok_or("content lacks successful READ history")?;
            if event.payload_sha256.as_ref() != Some(&last.payload_sha256)
                || event.payload_bytes != last.payload_bytes
                || event.observation != Some(last.observation)
            {
                return Err("last content receipt mismatch".into());
            }
        }
        let model = Digest32::of_bytes(&serde_json::to_vec(&identity).map_err(|e| e.to_string())?);
        let (sparse, mut config) = native::configuration(model);
        config.input_feature_dimension = 62;
        config.encoder_digest = native::marker("factorial-public62.v1");
        config.preprocessor_digest = native::marker("bounded-port-input;unclipped-policy67.v1");
        config.quantization_digest = native::marker("selected-action-onehot.q24.v1");
        let subject = native::id("hcsn.factorial-task-owner.v1");
        let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
        scope_bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
        scope_bytes.extend_from_slice(subject.as_str().as_bytes());
        let objective = identity
            .public_sha256
            .parse::<Digest32>()
            .map_err(|e| e.to_string())?;
        let scope = JournalScope {
            scope_digest: Digest32::of_bytes(&scope_bytes),
            objective_digest: objective,
        };
        let witness = FileAnchorWitnessStore::open(
            store::private_file(&store::sibling(args.snapshot, ".witness"))?,
            scope,
            Generation::new(1).map_err(|e| e.to_string())?,
            native::LIMIT,
        )
        .map_err(|e| e.to_string())?;
        let prior = witness.current().map_err(|e| e.to_string())?;
        let checkpoint = pair
            .native_checkpoint
            .parse::<Digest32>()
            .map_err(|e| e.to_string())?;
        if prior.map_or(0, |a| a.sequence) != pair.sequence
            || prior.map_or(Digest32::ZERO, |a| a.checkpoint_digest) != checkpoint
        {
            return Err("unacknowledged native/task frontier; refuse replay".into());
        }
        let journal = store::private_file(&store::sibling(args.snapshot, ".journal"))?;
        let (runtime, bootstrap) = match prior {
            None => {
                // An inspect-only genesis has no native tick or journal header.
                // Refuse an unknown partial journal; never erase it to retry.
                if journal.metadata().map_err(|e| e.to_string())?.len() != 0 {
                    return Err("unacknowledged genesis journal; refuse bootstrap".into());
                }
                (
                    None,
                    Some(Bootstrap {
                        journal,
                        sparse,
                        scope,
                        witness,
                    }),
                )
            }
            Some(anchor) => {
                let runtime = NeuronRuntime::recover(
                    journal,
                    sparse,
                    scope,
                    native::LIMIT,
                    config.clone(),
                    anchor,
                    witness,
                )
                .map_err(|e| e.to_string())?;
                if runtime.current_anchor().map_err(|e| e.to_string())? != prior {
                    return Err("unreconciled journal suffix".into());
                }
                (Some(runtime), None)
            }
        };
        if !exists {
            acknowledged_sha256 = store::save(args.snapshot, &pair)?.0;
        }
        Ok(Self {
            pair,
            acknowledged_sha256,
            external_ack_verified: args.ack.is_some(),
            artifact_load_nanos,
            public,
            policy,
            cell,
            content,
            folder: args.public.parent().ok_or("public parent")?.to_path_buf(),
            snapshot: args.snapshot.into(),
            runtime,
            bootstrap,
            config,
            subject,
            objective,
            poisoned: false,
        })
    }

    pub fn step(&mut self) -> Result<Receipt, String> {
        if self.poisoned || self.pair.task.terminal {
            return Err("terminal or incomplete owner".into());
        }
        let start = Instant::now();
        let before = self.pair.task.clone();
        let driver = before.driver(&self.public);
        let horizon_micros = (self.public.duration[before.tick] * 1e6).round() as u64;
        let public_features = policy::features(&self.public, &before, self.policy.confusion);
        // Bounded transport encoding only. The critic sees the original FP64 values.
        let input = public_features
            .iter()
            .map(|v| (v / (1.0 + v.abs()) * native::Q as f64).round() as i64)
            .collect::<Vec<_>>();
        let legal = before.legal(&self.public);
        let mut port = DecisionPort {
            config: self.config.clone(),
            expected_input: input.clone(),
            public_features: public_features.clone(),
            cell: &self.cell,
            policy: &self.policy,
            state: &before,
            legal,
            driver,
            horizon_micros,
            action: None,
            features: None,
            q: None,
            costs: Costs::default(),
            execution_nanos: 0,
        };
        let sequence = self.pair.sequence + 1;
        let runtime_start = Instant::now();
        self.poisoned = true;
        if let Some(bootstrap) = self.bootstrap.take() {
            self.runtime = Some(
                NeuronRuntime::bootstrap(
                    bootstrap.journal,
                    bootstrap.sparse,
                    bootstrap.scope,
                    native::LIMIT,
                    self.config.clone(),
                    bootstrap.witness,
                )
                .map_err(|e| e.to_string())?,
            );
        }
        let output = self
            .runtime
            .as_mut()
            .ok_or("missing native runtime")?
            .tick(
                &mut port,
                NeuronTickInputV1 {
                    tick_id: native::id(&format!("task-step-{sequence}")),
                    subject_id: self.subject.clone(),
                    logical_sequence: sequence,
                    monotonic_time_micros: before.elapsed_micros + 1,
                    checkpoint_digest: self
                        .pair
                        .native_checkpoint
                        .parse::<Digest32>()
                        .map_err(|e| e.to_string())?,
                    input_feature_digest: canonical_feature_vector_digest_v1(&input),
                    feature_vector_q24: input,
                    objective_digest: self.objective,
                    ndu_snapshot_digest: Digest32::of_bytes(
                        &serde_json::to_vec(&before).map_err(|e| e.to_string())?,
                    ),
                    body_generation: Some(1),
                    modulator_digest: None,
                },
            )
            .map_err(|e| e.to_string())?;
        let mut costs = port.costs.clone();
        costs.persist_nanos = nanos(runtime_start).saturating_sub(port.execution_nanos);
        let action = port.action.ok_or("missing autonomous decision")?;
        let cell_features = port.features;
        let q = port.q;
        if output.tick.active_indices != vec![action.index() as u32] {
            return Err("native action receipt mismatch".into());
        }
        let mut event = before.event(&self.public, action)?;
        let mut candidate_cell = self.cell.clone();
        if self.policy.controller != Controller::DirectFixed {
            let propagation_start = Instant::now();
            candidate_cell.advance(
                sequence,
                driver,
                (event.duration * 1e6).round() as u64,
                action == Action::Fire,
            )?;
            costs.propagation_nanos = nanos(propagation_start);
        }
        let mut candidate = self.pair.clone();
        if action == Action::Read {
            let content_start = Instant::now();
            let request = content::Request {
                path: self
                    .folder
                    .join(&self.public.packets[before.job][before.tick])
                    .to_string_lossy()
                    .into_owned(),
                sha256: self.public.packet_sha256[before.job][before.tick].clone(),
            };
            match self.content.read(&request) {
                Ok(result) => {
                    event.observation = Some(result.observation);
                    event.payload_sha256 = Some(result.payload_sha256.clone());
                    event.payload_bytes = result.payload_bytes;
                    candidate.content.completed_reads += 1;
                    candidate.content.last = Some(result);
                }
                Err(error) => event.error = Some(error),
            }
            costs.content_nanos = nanos(content_start);
        }
        candidate
            .task
            .apply(&self.public, self.policy.confusion, event.clone())?;
        candidate.sequence = sequence;
        candidate.cell = candidate_cell.snapshot();
        candidate.native_checkpoint = output.tick.checkpoint_after.to_string();
        let persist_start = Instant::now();
        let (ack, checkpoint_bytes_written) = store::save(&self.snapshot, &candidate)?;
        costs.persist_nanos += nanos(persist_start);
        self.pair = candidate;
        self.cell = candidate_cell;
        self.acknowledged_sha256 = ack.clone();
        self.poisoned = false;
        Ok(Receipt {
            sequence,
            action,
            before,
            after: self.pair.task.clone(),
            public_features,
            cell_features,
            q,
            legal,
            driver,
            horizon_micros,
            event,
            stage_costs: costs,
            signals_q24: output.signal.signals_q24,
            acknowledged_sha256: ack,
            native_checkpoint: self.pair.native_checkpoint.clone(),
            journal_bytes_written: output.tick.resource_receipt.journal_bytes_written,
            checkpoint_bytes_written,
            owner_nanos: nanos(start),
        })
    }
}
