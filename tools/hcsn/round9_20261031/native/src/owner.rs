//! Rust cell and real NeuronRuntime owned together. Recovery needs an externally
//! acknowledged pair digest; interruption between the two commits fails closed.
use crate::cell::Cell;
use crate::cell::Jump;
use crate::cell::Snapshot;
use crate::content;
use crate::native::CellPort;
use crate::native::LIMIT;
use crate::native::Q;
use crate::native::{self};
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

#[path = "schedule.rs"]
mod schedule;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct Pair {
    schema: String,
    source_digest: String,
    native_checkpoint: String,
    cell: Snapshot,
    content: Option<content::State>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub sequence: u64,
    pub pair_before: String,
    pub driver: f64,
    pub duration_micros: u64,
    pub horizon_micros: u64,
    pub reset: bool,
    #[serde(default)]
    pub content: Option<content::Request>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Interval {
    pub operation: String,
    pub pair_before: String,
    pub driver: f64,
    pub duration_micros: u64,
    pub horizon_micros: u64,
    pub reset: bool,
    #[serde(default)]
    pub content: Option<content::Request>,
}

#[derive(Debug, Serialize)]
pub struct Receipt {
    pub sequence: u64,
    pub pair_after: String,
    pub native_checkpoint: String,
    pub cell: Snapshot,
    pub content: Option<content::State>,
    pub scheduled_commits: u64,
    pub content_execution_nanos: u64,
    pub features: [f64; 5],
    pub signals_q24: Vec<i64>,
    pub jumps: Vec<Jump>,
    pub physics_execution_nanos: u64,
    pub complete_owner_nanos: u64,
    pub native_execution_micros: u64,
    pub journal_bytes_written: u64,
    pub witness_bytes_written: u64,
    pub physics_checkpoint_bytes_written: u64,
    pub durable_bytes_written: u64,
    pub native_physics_executed: bool,
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
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|e| e.to_string())?;
    if !f.metadata().map_err(|e| e.to_string())?.is_file() {
        return Err("regular file required".into());
    }
    Ok(f)
}
fn encoded(pair: &Pair) -> Result<Vec<u8>, String> {
    serde_json::to_vec(pair).map_err(|e| e.to_string())
}

pub struct Owner {
    pub cell: Cell,
    runtime: NeuronRuntime<FileAnchorWitnessStore>,
    config: NeuronRuntimeConfigV1,
    root: PathBuf,
    pair_digest: Digest32,
    native_checkpoint: Digest32,
    poisoned: bool,
    content_model: Option<content::Model>,
    content_state: Option<content::State>,
}
impl Owner {
    pub fn open(
        root: &Path,
        mut cell: Cell,
        acknowledged: &str,
        content_model: Option<content::Model>,
    ) -> Result<Self, String> {
        let mut content_state = content_model.as_ref().map(content::State::new);
        if !root.is_dir() || root.is_symlink() {
            return Err("private owner directory required".into());
        }
        let expected = acknowledged.parse::<Digest32>().map_err(|e| e.to_string())?;
        let path = root.join("cell-checkpoint.json");
        let checkpoint = if expected.is_zero() {
            if path.exists() || path.is_symlink() {
                return Err("existing physics checkpoint".into());
            }
            Digest32::ZERO
        } else {
            let f = OpenOptions::new()
                .read(true)
                .custom_flags(libc::O_NOFOLLOW)
                .open(&path)
                .map_err(|e| e.to_string())?;
            let mut bytes = Vec::new();
            f.take(32_769).read_to_end(&mut bytes).map_err(|e| e.to_string())?;
            if bytes.len() > 32_768 {
                return Err("checkpoint size limit".into());
            }
            let pair: Pair = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
            if pair.schema != "hcsn.native-content-pair.v2"
                || pair.source_digest != env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST")
                || Digest32::of_bytes(&encoded(&pair)?) != expected
            {
                return Err("acknowledged pair mismatch".into());
            }
            cell.restore(&pair.cell)?;
            match (&content_model, &pair.content) {
                (Some(model), Some(state)) => state.validate(model, cell.sequence)?,
                (None, None) => (),
                _ => return Err("content owner model presence mismatch".into()),
            }
            content_state = pair.content;
            pair.native_checkpoint.parse::<Digest32>().map_err(|e| e.to_string())?
        };
        let (sparse, config) = native::configuration(cell.model);
        let subject = native::id("hcsn.native-cell-owner.v1");
        let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
        bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
        bytes.extend_from_slice(subject.as_str().as_bytes());
        let scope = JournalScope {
            scope_digest: Digest32::of_bytes(&bytes),
            objective_digest: native::marker("finite-cell-qualification.v1"),
        };
        let witness = FileAnchorWitnessStore::open(
            private_file(&root.join("witness.bin"))?,
            scope,
            Generation::new(1).map_err(|e| e.to_string())?,
            LIMIT,
        )
        .map_err(|e| e.to_string())?;
        let prior = witness.current().map_err(|e| e.to_string())?;
        if prior.map_or(0, |a| a.sequence) != cell.sequence
            || prior.map_or(Digest32::ZERO, |a| a.checkpoint_digest) != checkpoint
        {
            return Err("physics/native acknowledged frontier mismatch".into());
        }
        let journal = private_file(&root.join("journal.bin"))?;
        let runtime = match prior {
            None => NeuronRuntime::bootstrap(journal, sparse, scope, LIMIT, config.clone(), witness),
            Some(anchor) => NeuronRuntime::recover(journal, sparse, scope, LIMIT, config.clone(), anchor, witness),
        }
        .map_err(|e| e.to_string())?;
        if runtime.current_anchor().map_err(|e| e.to_string())? != prior {
            return Err("unreconciled native suffix".into());
        }
        Ok(Self {
            cell,
            runtime,
            config,
            root: root.to_path_buf(),
            pair_digest: expected,
            native_checkpoint: checkpoint,
            poisoned: false,
            content_model,
            content_state,
        })
    }

    fn decode(&self, request: &Option<content::Request>) -> Result<Option<content::Output>, String> {
        match (request, &self.content_model) {
            (Some(request), Some(model)) => model.read(request).map(Some),
            (Some(_), None) => Err("content model is not configured".into()),
            (None, _) => Ok(None),
        }
    }

    pub fn step(&mut self, request: Request) -> Result<Receipt, String> {
        let start = Instant::now();
        self.validate_request(&request)?;
        let content_start = Instant::now();
        let decoded = self.decode(&request.content)?;
        let content_nanos = content_start.elapsed().as_nanos().try_into().unwrap_or(u64::MAX);
        let mut receipt = self.commit(request, decoded)?;
        receipt.content_execution_nanos = content_nanos;
        receipt.complete_owner_nanos = start.elapsed().as_nanos().try_into().unwrap_or(u64::MAX);
        Ok(receipt)
    }

    fn validate_request(&self, request: &Request) -> Result<(), String> {
        if self.poisoned
            || request.sequence != self.cell.sequence + 1
            || request.sequence > LIMIT as u64
            || request.duration_micros == 0
            || request.duration_micros > 128_000_000
            || !request.driver.is_finite()
            || request.driver.abs() > 1.
            || request.horizon_micros == 0
            || request.horizon_micros > 128_000_000
            || request.pair_before != self.pair_digest.to_string()
        {
            return Err("owner frontier/poisoned/duration".into());
        }
        Ok(())
    }

    fn commit(&mut self, request: Request, decoded: Option<content::Output>) -> Result<Receipt, String> {
        let start = Instant::now();
        self.validate_request(&request)?;
        let mut content_state = self.content_state.clone();
        if let Some(output) = decoded {
            let state = content_state.as_mut().ok_or("missing content state")?;
            state.completed_reads += 1;
            state.last = Some(output);
        }
        let physics_start = Instant::now();
        let mut candidate = self.cell.clone();
        let jumps = candidate.advance(request.sequence, request.driver, request.duration_micros, request.reset)?;
        let snapshot = candidate.snapshot();
        let physics_nanos: u64 = physics_start.elapsed().as_nanos().try_into().unwrap_or(u64::MAX);
        let causal_input = [
            request.driver,
            request.duration_micros as f64 / 128_000_000.0,
            request.horizon_micros as f64 / 128_000_000.0,
            f64::from(u8::from(request.reset)),
            candidate.events / (1.0 + candidate.events),
        ];
        let packed = causal_input
            .iter()
            .map(|x| (x * Q as f64).round() as i64)
            .collect::<Vec<_>>();
        let binding = serde_json::to_vec(&(&request, &snapshot, &content_state)).map_err(|e| e.to_string())?;
        let input = NeuronTickInputV1 {
            tick_id: native::id(&format!("native.cell.{}", request.sequence)),
            subject_id: native::id("hcsn.native-cell-owner.v1"),
            logical_sequence: request.sequence,
            monotonic_time_micros: candidate.elapsed_micros + 1,
            checkpoint_digest: self.native_checkpoint,
            input_feature_digest: canonical_feature_vector_digest_v1(&packed),
            feature_vector_q24: packed.clone(),
            objective_digest: native::marker("finite-cell-qualification.v1"),
            ndu_snapshot_digest: Digest32::of_bytes(&binding),
            body_generation: Some(1),
            modulator_digest: None,
        };
        let mut model = CellPort {
            config: self.config.clone(),
            expected_input: packed,
            cell: candidate.clone(),
            driver: request.driver,
            horizon_micros: request.horizon_micros,
            last_features: None,
            execution_nanos: 0,
        };
        let witness_before = std::fs::metadata(self.root.join("witness.bin"))
            .map_err(|e| e.to_string())?
            .len();
        let result = self.runtime.tick(&mut model, input);
        let output = match result {
            Ok(v) => v,
            Err(error) => {
                self.poisoned = true;
                return Err(error.to_string());
            }
        };
        // Every failure after a successful native commit must block reuse,
        // including failures while constructing or measuring the paired record.
        self.poisoned = true;
        let pair = Pair {
            schema: "hcsn.native-content-pair.v2".into(),
            source_digest: env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST").into(),
            native_checkpoint: output.tick.checkpoint_after.to_string(),
            cell: snapshot.clone(),
            content: content_state.clone(),
        };
        let features = model.last_features.ok_or("missing actual model query")?;
        let bytes = encoded(&pair)?;
        let pair_digest = Digest32::of_bytes(&bytes);
        let temporary = self.root.join("cell-checkpoint.pending");
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(&temporary)
            .map_err(|e| e.to_string())?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|e| e.to_string())?;
        std::fs::rename(&temporary, self.root.join("cell-checkpoint.json")).map_err(|e| e.to_string())?;
        File::open(&self.root)
            .and_then(|f| f.sync_all())
            .map_err(|e| e.to_string())?;
        let witness_bytes = std::fs::metadata(self.root.join("witness.bin"))
            .map_err(|e| e.to_string())?
            .len()
            .checked_sub(witness_before)
            .ok_or("native witness length decreased")?;
        self.cell = candidate;
        self.content_state = content_state.clone();
        self.pair_digest = pair_digest;
        self.native_checkpoint = output.tick.checkpoint_after;
        self.poisoned = false;
        Ok(Receipt {
            sequence: request.sequence,
            pair_after: pair_digest.to_string(),
            native_checkpoint: pair.native_checkpoint,
            cell: snapshot,
            content: content_state,
            scheduled_commits: 1,
            content_execution_nanos: 0,
            features,
            signals_q24: output.signal.signals_q24,
            jumps,
            physics_execution_nanos: physics_nanos.saturating_add(model.execution_nanos),
            complete_owner_nanos: start.elapsed().as_nanos().try_into().unwrap_or(u64::MAX),
            native_execution_micros: output.tick.resource_receipt.execution_micros,
            journal_bytes_written: output.tick.resource_receipt.journal_bytes_written,
            witness_bytes_written: witness_bytes,
            physics_checkpoint_bytes_written: bytes.len() as u64,
            durable_bytes_written: output.tick.resource_receipt.journal_bytes_written
                + witness_bytes
                + bytes.len() as u64,
            native_physics_executed: true,
            production_activation: false,
            authority: "DENY_ALL",
        })
    }
}
