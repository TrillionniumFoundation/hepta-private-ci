//! A real NeuronRuntime owner: policy first, interval second, due content third.
use crate::cell;
use crate::content;
use crate::policy;
use crate::port;
use crate::runtime;
use crate::store;
use crate::task;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Identity {
    pub source_digest: String,
    pub public_sha256: String,
    pub policy_sha256: String,
    pub content_model_sha256: String,
    pub controller: policy::Controller,
    pub seed: u64,
    pub mode: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Ledger {
    pub action: usize,
    pub forced_control: bool,
    pub completion: Option<task::Completion>,
    pub content: Option<content::Output>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Pair {
    pub schema: String,
    pub identity: Identity,
    pub sequence: u64,
    pub native_checkpoint: String,
    pub task: task::State,
    pub cell: cell::State,
    pub content: content::State,
    pub ledger: Vec<Ledger>,
}

impl Pair {
    fn validate(
        &self,
        public: &task::Public,
        policy: &policy::Policy,
        model: &content::Model,
    ) -> Result<(), String> {
        if self.schema != "digital-read-before-pair-v1"
            || self.sequence != self.ledger.len() as u64
            || self.sequence > 7
            || (self.identity.mode != "qualification"
                && self.ledger.iter().any(|e| e.forced_control))
        {
            return Err("checkpoint sequence/mode contract".into());
        }
        self.task.validate(public)?;
        self.cell.validate()?;
        self.content.validate(model, self.sequence)?;
        let mut state = task::State::initial();
        let mut cell = cell::State::new(self.identity.seed);
        let mut content = content::State::new(model);
        for entry in &self.ledger {
            let due = state.due(public, entry.action)?;
            if ![0, 4, 5].contains(&entry.action) {
                if let Some(kernel) = &policy.kernel {
                    cell.advance(kernel.lookup(
                        public.duration[state.tick],
                        state.last_symbol,
                        state.last_reliability,
                    )?)?;
                }
            }
            if let Some(output) = &entry.content {
                let source = due.ok_or("unsolicited content in checkpoint")?;
                if entry.completion.as_ref()
                    != Some(&task::Completion {
                        failure: false,
                        observation: Some(output.observation),
                    })
                    || output.payload_sha256 != public.packet_sha256[source]
                {
                    return Err("checkpoint content/observation identity".into());
                }
                content.completed_reads += 1;
                content.last = Some(output.clone());
                content.validate(model, self.sequence)?;
            } else if entry.completion.as_ref().is_some_and(|x| !x.failure) {
                return Err("successful completion lacks actual content receipt".into());
            }
            state = state.successor(public, entry.action, entry.completion.as_ref())?;
        }
        if state != self.task || cell != self.cell || content != self.content {
            return Err("checkpoint does not replay to task/cell/content frontier".into());
        }
        if self.content.completed_reads != self.task.history.len() as u64 {
            return Err("successful read count differs from observed history".into());
        }
        Ok(())
    }
}

#[derive(Debug, Serialize)]
pub struct Receipt {
    pub sequence: u64,
    pub action: usize,
    pub action_name: String,
    pub forced_control: bool,
    pub mode: String,
    pub before: task::State,
    pub after: task::State,
    pub public_features: Vec<f64>,
    pub representation_features: [f64; 12],
    pub q: [f64; 6],
    pub belief_logit: f64,
    pub belief: f64,
    pub legal: [bool; 6],
    pub cell_before: cell::State,
    pub cell_after: cell::State,
    pub cell_event: bool,
    pub draw: Option<cell::Draw>,
    pub due_source: Option<usize>,
    pub completion: Option<task::Completion>,
    pub content: Option<content::Output>,
    pub content_error: Option<String>,
    pub attempted_packet_paths: Vec<String>,
    pub opened_packet_paths: Vec<String>,
    pub read_audit: content::ReadAudit,
    pub actual_content_calls: u64,
    pub duration: f64,
    pub charges: f64,
    pub costs: port::Costs,
    pub signals_q24: Vec<i64>,
    pub acknowledged_sha256: String,
    pub native_checkpoint: String,
    pub journal_bytes: u64,
    pub witness_bytes: u64,
    pub checkpoint_bytes: u64,
    pub owner_nanos: u64,
}

struct Bootstrap {
    journal: File,
    sparse: SparseConfig,
    scope: JournalScope,
    witness: FileAnchorWitnessStore,
}

pub struct Owner {
    pub pair: Pair,
    pub acknowledged_sha256: String,
    pub external_ack_verified: bool,
    pub artifact_load_nanos: u64,
    pub initial_persistence_bytes: u64,
    pub public: task::Public,
    pub policy: policy::Policy,
    content: content::Model,
    folder: PathBuf,
    snapshot: PathBuf,
    runtime: Option<NeuronRuntime<FileAnchorWitnessStore>>,
    bootstrap: Option<Bootstrap>,
    config: NeuronRuntimeConfigV1,
    subject: StableId,
    objective: Digest32,
    poisoned: bool,
}

pub struct Open<'a> {
    pub public: &'a Path,
    pub content: &'a Path,
    pub policy: &'a Path,
    pub controller: policy::Controller,
    pub snapshot: &'a Path,
    pub ack: Option<&'a str>,
    pub seed: u64,
    pub mode: &'a str,
    pub first_forced: Option<usize>,
}

fn file_len(path: &Path) -> Result<u64, String> {
    std::fs::metadata(path)
        .map(|s| s.len())
        .map_err(|e| e.to_string())
}

impl Owner {
    pub fn open(args: Open<'_>) -> Result<Self, String> {
        let start = Instant::now();
        if !["experiment", "qualification"].contains(&args.mode)
            || (args.first_forced.is_some() && args.mode != "qualification")
        {
            return Err("forced actions require qualification mode".into());
        }
        let public_bytes = store::read(args.public, 128_000)?;
        let policy_bytes = store::read(args.policy, 32_000_000)?;
        let content_bytes = store::read(args.content, 2_000_000)?;
        let public: task::Public =
            serde_json::from_slice(&public_bytes).map_err(|e| e.to_string())?;
        public.validate()?;
        let policy: policy::Policy =
            serde_json::from_slice(&policy_bytes).map_err(|e| e.to_string())?;
        policy.validate(&public)?;
        let identity = Identity {
            source_digest: env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST").into(),
            public_sha256: store::digest(&public_bytes),
            policy_sha256: store::digest(&policy_bytes),
            content_model_sha256: store::digest(&content_bytes),
            controller: args.controller,
            seed: args.seed,
            mode: args.mode.into(),
        };
        let content = content::Model::load(args.content, &identity.content_model_sha256)?;
        let exists = args.snapshot.exists() || args.snapshot.is_symlink();
        let pending = store::sibling(args.snapshot, ".pending");
        if !args.snapshot.parent().is_some_and(Path::is_dir)
            || pending.exists()
            || pending.is_symlink()
        {
            return Err("existing snapshot directory and no incomplete commit required".into());
        }
        let (pair, mut ack) = if exists {
            let expected = args
                .ack
                .ok_or("external acknowledged digest is mandatory for recovery")?;
            let bytes = store::read(args.snapshot, 2_000_000)?;
            let digest = store::digest(&bytes);
            if expected != digest {
                return Err("external acknowledged digest mismatch".into());
            }
            let pair: Pair = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
            if pair.identity != identity {
                return Err("checkpoint source/public/model/policy identity mismatch".into());
            }
            (pair, digest)
        } else {
            if args.ack.is_some() {
                return Err("ack supplied for absent checkpoint".into());
            }
            (
                Pair {
                    schema: "digital-read-before-pair-v1".into(),
                    identity: identity.clone(),
                    sequence: 0,
                    native_checkpoint: Digest32::ZERO.to_string(),
                    task: task::State::initial(),
                    cell: cell::State::new(args.seed),
                    content: content::State::new(&content),
                    ledger: vec![],
                },
                String::new(),
            )
        };
        pair.validate(&public, &policy, &content)?;
        // This preflight precedes any owner file creation, including genesis.
        if args
            .first_forced
            .is_some_and(|a| a >= 6 || !pair.task.legal(&public)[a])
        {
            return Err("illegal forced action; no snapshot published".into());
        }
        let model = Digest32::of_bytes(&serde_json::to_vec(&identity).map_err(|e| e.to_string())?);
        let (sparse, config) = runtime::configuration(model, 36);
        let subject = runtime::id("hepta.digital.preread.owner.v1");
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
        let witness_path = store::sibling(args.snapshot, ".witness");
        let witness_start = if witness_path.exists() {
            file_len(&witness_path)?
        } else {
            0
        };
        let witness = FileAnchorWitnessStore::open(
            store::private_file(&witness_path)?,
            scope,
            Generation::new(1).map_err(|e| e.to_string())?,
            runtime::LIMIT,
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
        let (native, bootstrap) = match prior {
            None => {
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
                let native = NeuronRuntime::recover(
                    journal,
                    sparse,
                    scope,
                    runtime::LIMIT,
                    config.clone(),
                    anchor,
                    witness,
                )
                .map_err(|e| e.to_string())?;
                if native.current_anchor().map_err(|e| e.to_string())? != prior {
                    return Err("unreconciled journal suffix".into());
                }
                (Some(native), None)
            }
        };
        let mut initial_persistence_bytes = file_len(&witness_path)?.saturating_sub(witness_start);
        if !exists {
            let saved = store::save(args.snapshot, &pair)?;
            ack = saved.0;
            initial_persistence_bytes += saved.1;
        }
        Ok(Self {
            pair,
            acknowledged_sha256: ack,
            external_ack_verified: args.ack.is_some(),
            artifact_load_nanos: port::nanos(start),
            initial_persistence_bytes,
            public,
            policy,
            content,
            folder: args.public.parent().ok_or("public parent")?.to_path_buf(),
            snapshot: args.snapshot.into(),
            runtime: native,
            bootstrap,
            config,
            subject,
            objective,
            poisoned: false,
        })
    }

    pub fn step(&mut self, forced: Option<usize>) -> Result<Receipt, String> {
        if self.poisoned || self.pair.task.terminal {
            return Err("terminal or incomplete owner".into());
        }
        let start = Instant::now();
        let before = self.pair.task.clone();
        let cell_before = self.pair.cell.clone();
        let legal = before.legal(&self.public);
        if forced.is_some_and(|a| a >= 6 || !legal[a])
            || (forced.is_some() && self.pair.identity.mode != "qualification")
        {
            return Err("illegal forced action; state unchanged".into());
        }
        let public_features = before.public_features(&self.public);
        let input = runtime::packed(&public_features);
        let sequence = self.pair.sequence + 1;
        let mut decision = port::DecisionPort {
            config: self.config.clone(),
            expected_input: input.clone(),
            public_features: public_features.clone(),
            cell: &cell_before,
            state: &before,
            policy: &self.policy,
            controller: self.pair.identity.controller,
            legal,
            forced,
            action: None,
            representation: None,
            scores: None,
            costs: port::Costs::default(),
            execution_nanos: 0,
        };
        let journal_path = store::sibling(&self.snapshot, ".journal");
        let witness_path = store::sibling(&self.snapshot, ".witness");
        let journal_start = file_len(&journal_path)?;
        let witness_start = file_len(&witness_path)?;
        let native_start = Instant::now();
        self.poisoned = true;
        if let Some(bootstrap) = self.bootstrap.take() {
            self.runtime = Some(
                NeuronRuntime::bootstrap(
                    bootstrap.journal,
                    bootstrap.sparse,
                    bootstrap.scope,
                    runtime::LIMIT,
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
                &mut decision,
                NeuronTickInputV1 {
                    tick_id: runtime::id(&format!("digital-step-{sequence}")),
                    subject_id: self.subject.clone(),
                    logical_sequence: sequence,
                    monotonic_time_micros: (before.elapsed * 1e6).round() as u64 + 1,
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
        let mut costs = decision.costs.clone();
        costs.persist_nanos = port::nanos(native_start).saturating_sub(decision.execution_nanos);
        let action = decision.action.ok_or("missing native decision")?;
        let representation_features = decision.representation.ok_or("missing representation")?;
        let scores = decision.scores.take().ok_or("missing learned scores")?;
        if output.tick.active_indices != vec![action as u32] {
            return Err("native selected action mismatch".into());
        }
        let mut candidate = self.pair.clone();
        let mut draw = None;
        if ![0, 4, 5].contains(&action) {
            if let Some(kernel) = &self.policy.kernel {
                let propagation_start = Instant::now();
                draw = Some(candidate.cell.advance(kernel.lookup(
                    self.public.duration[before.tick],
                    before.last_symbol,
                    before.last_reliability,
                )?)?);
                costs.propagation_nanos = port::nanos(propagation_start);
            }
        }
        let due_source = before.due(&self.public, action)?;
        let mut completion = None;
        let mut content_output = None;
        let mut content_error = None;
        let mut read_audit = content::ReadAudit::default();
        let mut attempted_packet_paths = vec![];
        let mut opened_packet_paths = vec![];
        if let Some(source) = due_source {
            let content_start = Instant::now();
            let path = store::relative_packet(&self.folder, &self.public.packets[source])?
                .to_string_lossy()
                .into_owned();
            let request = content::Request {
                path: path.clone(),
                sha256: self.public.packet_sha256[source].clone(),
            };
            attempted_packet_paths.push(path.clone());
            match self.content.read_observed(&request, &mut read_audit) {
                Ok(result) => {
                    completion = Some(task::Completion {
                        failure: false,
                        observation: Some(result.observation),
                    });
                    candidate.content.completed_reads += 1;
                    candidate.content.last = Some(result.clone());
                    content_output = Some(result);
                }
                Err(error) => {
                    completion = Some(task::Completion {
                        failure: true,
                        observation: None,
                    });
                    content_error = Some(error);
                }
            }
            if read_audit.successful_opens > 0 {
                opened_packet_paths.push(path);
            }
            costs.content_nanos = port::nanos(content_start);
        }
        candidate.task = before.successor(&self.public, action, completion.as_ref())?;
        candidate.sequence = sequence;
        candidate.native_checkpoint = output.tick.checkpoint_after.to_string();
        candidate.ledger.push(Ledger {
            action,
            forced_control: forced.is_some(),
            completion: completion.clone(),
            content: content_output.clone(),
        });
        let persist_start = Instant::now();
        let (ack, checkpoint_bytes) = store::save(&self.snapshot, &candidate)?;
        costs.persist_nanos += port::nanos(persist_start);
        self.pair = candidate;
        self.acknowledged_sha256 = ack.clone();
        self.poisoned = false;
        Ok(Receipt {
            sequence,
            action,
            action_name: task::NAMES[action].into(),
            forced_control: forced.is_some(),
            mode: self.pair.identity.mode.clone(),
            duration: self.pair.task.elapsed - before.elapsed,
            charges: self.pair.task.charges - before.charges,
            before,
            after: self.pair.task.clone(),
            public_features,
            representation_features,
            q: scores.q,
            belief_logit: scores.belief_logit,
            belief: scores.belief,
            legal,
            cell_before,
            cell_after: self.pair.cell.clone(),
            cell_event: draw.as_ref().is_some_and(|d| d.event),
            draw,
            due_source,
            completion,
            content: content_output,
            content_error,
            attempted_packet_paths,
            opened_packet_paths,
            actual_content_calls: read_audit.model_executions,
            read_audit,
            costs,
            signals_q24: output.signal.signals_q24,
            acknowledged_sha256: ack,
            native_checkpoint: self.pair.native_checkpoint.clone(),
            journal_bytes: file_len(&journal_path)?.saturating_sub(journal_start),
            witness_bytes: file_len(&witness_path)?.saturating_sub(witness_start),
            checkpoint_bytes,
            owner_nanos: port::nanos(start),
        })
    }
}
