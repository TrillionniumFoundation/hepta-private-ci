//! Acknowledged policy/native journal pair; incomplete publication fails closed.
use crate::model::Identity;
use crate::model::Model;
use crate::model::Prediction;
use crate::model::Request;
use crate::model::State;
use crate::model::{self};
use crate::port::LIMIT;
use crate::port::Port;
use crate::port::Q;
use crate::port::{self};
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Pair {
    pub schema: String,
    pub source_digest: String,
    pub identity: Identity,
    pub state: State,
    pub native_checkpoint: String,
    pub last_public_state_sha256: String,
}

#[derive(Serialize)]
pub struct Receipt {
    pub pair_after: String,
    pub native_checkpoint: String,
    pub prediction: Prediction,
    pub signals_q24: Vec<i64>,
    pub runtime_abstained: bool,
    pub kernel_version: &'static str,
    pub native_runtime_nanos: u64,
    pub persistence_nanos: u64,
    pub complete_owner_nanos: u64,
    pub durable_bytes_written: u64,
    pub production_activation: bool,
    pub authority: &'static str,
}

fn private_file(path: &Path) -> Result<File, String> {
    let f = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(|e| e.to_string())?;
    if !f.metadata().map_err(|e| e.to_string())?.is_file() {
        return Err("regular owner file required".into());
    }
    Ok(f)
}

pub fn read(path: &Path, limit: u64) -> Result<Vec<u8>, String> {
    let f = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(|e| e.to_string())?;
    if !f.metadata().map_err(|e| e.to_string())?.is_file() {
        return Err("regular input file required".into());
    }
    let mut bytes = Vec::new();
    f.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() as u64 > limit {
        return Err("file size limit".into());
    }
    Ok(bytes)
}

pub struct Owner {
    pub pair: Pair,
    pub pair_digest: String,
    model: Model,
    root: PathBuf,
    runtime: NeuronRuntime<FileAnchorWitnessStore>,
    config: NeuronRuntimeConfigV1,
    _lock: File,
    poisoned: bool,
}

impl Owner {
    pub fn open(model: Model, identity: Identity, root: &Path, acknowledged: &str) -> Result<Self, String> {
        if !root.is_dir() || root.is_symlink() {
            return Err("private owner directory required".into());
        }
        let lock = private_file(&root.join("owner.lock"))?;
        if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err("owner already locked".into());
        }
        if root.join("pair.pending").exists() || root.join("pair.pending").is_symlink() {
            return Err("incomplete paired commit".into());
        }
        let expected = acknowledged.parse::<Digest32>().map_err(|e| e.to_string())?;
        let pair = if expected.is_zero() {
            if root.join("pair.json").exists() || root.join("pair.json").is_symlink() {
                return Err("existing acknowledged policy state".into());
            }
            let mut mass = vec![0.0; model.kernel.n + 2];
            mass[model.kernel.n / 2] = 1.0;
            Pair {
                schema: "hepta.r7-native-pair.v1".into(),
                source_digest: env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST").into(),
                identity: identity.clone(),
                state: State { calls: 0, mass },
                native_checkpoint: Digest32::ZERO.to_string(),
                last_public_state_sha256: Digest32::ZERO.to_string(),
            }
        } else {
            let bytes = read(&root.join("pair.json"), /*limit*/ 65536)?;
            if Digest32::of_bytes(&bytes) != expected {
                return Err("acknowledged pair digest mismatch".into());
            }
            let pair: Pair = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
            if pair.schema != "hepta.r7-native-pair.v1"
                || pair.source_digest != env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST")
                || pair.identity != identity
            {
                return Err("checkpoint source/model/policy identity mismatch".into());
            }
            pair
        };
        model.validate(&identity, &pair.state)?;
        pair.last_public_state_sha256
            .parse::<Digest32>()
            .map_err(|e| e.to_string())?;
        let model_identity = Digest32::of_bytes(&serde_json::to_vec(&identity).map_err(|e| e.to_string())?);
        let (sparse, config) = port::configuration(model_identity);
        let subject = port::id("hepta.r7-native-policy-owner.v1");
        let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
        scope_bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
        scope_bytes.extend_from_slice(subject.as_str().as_bytes());
        let scope = JournalScope {
            scope_digest: Digest32::of_bytes(&scope_bytes),
            objective_digest: port::marker("r7-public-task-policy.v1"),
        };
        let witness = FileAnchorWitnessStore::open(
            private_file(&root.join("witness.bin"))?,
            scope,
            Generation::new(1).map_err(|e| e.to_string())?,
            LIMIT,
        )
        .map_err(|e| e.to_string())?;
        let prior = witness.current().map_err(|e| e.to_string())?;
        let checkpoint = pair
            .native_checkpoint
            .parse::<Digest32>()
            .map_err(|e| e.to_string())?;
        if prior.map_or(0, |a| a.sequence) != pair.state.calls
            || prior.map_or(Digest32::ZERO, |a| a.checkpoint_digest) != checkpoint
        {
            return Err("policy/native acknowledged frontier mismatch".into());
        }
        let journal = private_file(&root.join("journal.bin"))?;
        let runtime = match prior {
            None => NeuronRuntime::bootstrap(journal, sparse, scope, LIMIT, config.clone(), witness),
            Some(anchor) => {
                NeuronRuntime::recover(journal, sparse, scope, LIMIT, config.clone(), anchor, witness)
            }
        }
        .map_err(|e| e.to_string())?;
        if runtime.current_anchor().map_err(|e| e.to_string())? != prior {
            return Err("unreconciled native suffix".into());
        }
        Ok(Self {
            pair,
            pair_digest: acknowledged.into(),
            model,
            root: root.into(),
            runtime,
            config,
            _lock: lock,
            poisoned: false,
        })
    }

    pub fn step(&mut self, request: Request) -> Result<Receipt, String> {
        let start = Instant::now();
        if self.poisoned
            || request.sequence != self.pair.state.calls + 1
            || request.sequence > LIMIT as u64
            || request.pair_before != self.pair_digest
            || request.features.len() != 18
            || request.features.iter().any(|x| !x.is_finite() || x.abs() > 64.0)
            || !request.legal.iter().any(|x| *x)
        {
            return Err("stale/poisoned/invalid public input".into());
        }
        request
            .public_state_sha256
            .parse::<Digest32>()
            .map_err(|e| e.to_string())?;
        let packed: Vec<_> = request
            .features
            .iter()
            .map(|x| (x * Q as f64).round() as i64)
            .collect();
        let binding = serde_json::to_vec(&(&request, &self.pair)).map_err(|e| e.to_string())?;
        let input = NeuronTickInputV1 {
            tick_id: port::id(&format!("r7.policy.{}", request.sequence)),
            subject_id: port::id("hepta.r7-native-policy-owner.v1"),
            logical_sequence: request.sequence,
            monotonic_time_micros: request.sequence * 1_000_000 + 1,
            checkpoint_digest: self
                .pair
                .native_checkpoint
                .parse::<Digest32>()
                .map_err(|e| e.to_string())?,
            input_feature_digest: canonical_feature_vector_digest_v1(&packed),
            feature_vector_q24: packed.clone(),
            objective_digest: port::marker("r7-public-task-policy.v1"),
            ndu_snapshot_digest: Digest32::of_bytes(&binding),
            body_generation: Some(1),
            modulator_digest: None,
        };
        let mut port = Port {
            config: self.config.clone(),
            expected_input: packed,
            model: &self.model,
            identity: &self.pair.identity,
            before: &self.pair.state,
            request: &request,
            result: None,
        };
        let before_bytes: u64 = ["journal.bin", "witness.bin"]
            .iter()
            .map(|p| std::fs::metadata(self.root.join(p)).map(|m| m.len()).unwrap_or(0))
            .sum();
        let native_start = Instant::now();
        let output = self.runtime.tick(&mut port, input);
        self.poisoned = true; // A native write may already exist after any dispatch.
        let output = output.map_err(|e| e.to_string())?;
        let native_runtime_nanos = model::nanos(native_start);
        let (state, prediction) = port.result.take().ok_or("native model port was not executed")?;
        let mut expected_signal: Vec<_> = model::ACTIONS
            .iter()
            .map(|a| if *a == prediction.action { Q } else { 0 })
            .collect();
        expected_signal.push(0);
        if output.signal.signals_q24 != expected_signal {
            return Err("native signal differs from selected policy action".into());
        }
        let persistence_start = Instant::now();
        let pair = Pair {
            schema: self.pair.schema.clone(),
            source_digest: self.pair.source_digest.clone(),
            identity: self.pair.identity.clone(),
            state,
            native_checkpoint: output.tick.checkpoint_after.to_string(),
            last_public_state_sha256: request.public_state_sha256,
        };
        let bytes = serde_json::to_vec(&pair).map_err(|e| e.to_string())?;
        let digest = Digest32::of_bytes(&bytes).to_string();
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(self.root.join("pair.pending"))
            .map_err(|e| e.to_string())?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|e| e.to_string())?;
        std::fs::rename(self.root.join("pair.pending"), self.root.join("pair.json"))
            .map_err(|e| e.to_string())?;
        File::open(&self.root)
            .and_then(|f| f.sync_all())
            .map_err(|e| e.to_string())?;
        let after_bytes: u64 = ["journal.bin", "witness.bin"]
            .iter()
            .map(|p| std::fs::metadata(self.root.join(p)).map(|m| m.len()).unwrap_or(0))
            .sum();
        let persistence_nanos = model::nanos(persistence_start);
        self.pair = pair;
        self.pair_digest = digest.clone();
        self.poisoned = false;
        Ok(Receipt {
            pair_after: digest,
            native_checkpoint: self.pair.native_checkpoint.clone(),
            prediction,
            signals_q24: output.signal.signals_q24,
            runtime_abstained: output.signal.abstain,
            kernel_version: model::KERNEL_VERSION,
            native_runtime_nanos,
            persistence_nanos,
            complete_owner_nanos: model::nanos(start),
            durable_bytes_written: after_bytes.saturating_sub(before_bytes) + bytes.len() as u64,
            production_activation: false,
            authority: "DENY_ALL",
        })
    }
}
