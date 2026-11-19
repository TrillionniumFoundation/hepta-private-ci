//! Native owner-component execution, distinct from production Cell qualification.
mod config;
mod model;

use codex_hepta_neuron::{
    AnchorWitnessStore, FileAnchorWitnessStore, InferenceControlModelPort, JournalAnchor,
    NeuronRuntime, NeuronRuntimeError, WitnessStoreError,
};
use codex_hepta_types::Digest32;
use model::{Projection, process_memory};
use serde_json::{Value, json};
use std::collections::VecDeque;
use std::error::Error;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

type Outcome<T> = Result<T, Box<dyn Error>>;
const CAP: usize = 256;

fn file(path: &Path) -> io::Result<File> {
    OpenOptions::new().read(true).write(true).open(path)
}
fn fresh(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
}
fn paths(root: &Path, index: usize) -> (PathBuf, PathBuf) {
    (
        root.join(format!("journal-{index}.bin")),
        root.join(format!("witness-{index}.bin")),
    )
}
fn open_owner(
    root: &Path,
    index: usize,
    projection: &Projection,
) -> Outcome<NeuronRuntime<FileAnchorWitnessStore>> {
    let (journal_path, witness_path) = paths(root, index);
    let native = config::native();
    let witness = FileAnchorWitnessStore::open(
        file(&witness_path)?,
        config::scope(index),
        native.generation,
        CAP,
    )?;
    let anchor = witness
        .current()?
        .ok_or("no published witness; public recovery requires an anchor")?;
    Ok(NeuronRuntime::recover(
        file(&journal_path)?,
        native,
        config::scope(index),
        CAP,
        config::config(projection),
        anchor,
        witness,
    )?)
}
fn fresh_owner(
    root: &Path,
    index: usize,
    projection: &Projection,
) -> Outcome<NeuronRuntime<FileAnchorWitnessStore>> {
    let (journal_path, witness_path) = paths(root, index);
    let native = config::native();
    let witness = FileAnchorWitnessStore::open(
        fresh(&witness_path)?,
        config::scope(index),
        native.generation,
        CAP,
    )?;
    Ok(NeuronRuntime::bootstrap(
        fresh(&journal_path)?,
        native,
        config::scope(index),
        CAP,
        config::config(projection),
        witness,
    )?)
}
fn measured_sizes(root: &Path, count: usize) -> Outcome<(u64, u64)> {
    let mut journals = 0;
    let mut witnesses = 0;
    for index in 0..count {
        let (j, w) = paths(root, index);
        journals += fs::metadata(j)?.len();
        witnesses += fs::metadata(w)?.len();
    }
    Ok((journals, witnesses))
}
fn anchors(owners: &[NeuronRuntime<FileAnchorWitnessStore>]) -> Outcome<Digest32> {
    let mut bytes = Vec::with_capacity(owners.len() * 40);
    for owner in owners {
        let a = owner.current_anchor()?.ok_or("missing final anchor")?;
        bytes.extend_from_slice(&a.sequence.to_be_bytes());
        bytes.extend_from_slice(a.checkpoint_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}
fn benchmark(
    root: &Path,
    count: usize,
    warmup: usize,
    rounds: usize,
    projection: &mut Projection,
) -> Outcome<Value> {
    if ![64, 256, 1024, 4096].contains(&count)
        || warmup > 16
        || !(16..=128).contains(&rounds)
        || warmup + rounds + 1 > CAP
    {
        return Err("unsupported frozen benchmark dimensions".into());
    }
    fs::create_dir(root)?;
    let initialize = Instant::now();
    let mut owners = (0..count)
        .map(|i| fresh_owner(root, i, projection))
        .collect::<Outcome<Vec<_>>>()?;
    let initialize_ns = initialize.elapsed().as_nanos() as u64;
    let initial_sizes = measured_sizes(root, count)?;
    let mut queue = VecDeque::with_capacity(count);
    let mut owner_ns = Vec::with_capacity(count * rounds);
    let mut batch_ns = Vec::with_capacity(rounds);
    let mut internal_us = Vec::with_capacity(count * rounds);
    let mut queue_us = Vec::with_capacity(count * rounds);
    let mut counted_journal_bytes = 0_u64;
    let mut abstained = 0_u64;
    for round in 1..=warmup + rounds {
        let batch_start = Instant::now();
        for (index, owner) in owners.iter().enumerate() {
            let checkpoint = owner
                .current_anchor()?
                .map_or(Digest32::ZERO, |a| a.checkpoint_digest);
            queue.push_back((
                index,
                config::input(index, round as u64, checkpoint),
                Instant::now(),
            ));
        }
        while let Some((index, input, queued)) = queue.pop_front() {
            projection.queue_started = queued;
            let start = Instant::now();
            let mut port = InferenceControlModelPort::new(projection);
            let output = owners[index].tick(&mut port, input)?;
            let wall = start.elapsed().as_nanos() as u64;
            if output.signal.authority.grants_any() {
                return Err("unexpected authority grant".into());
            }
            counted_journal_bytes += output.tick.resource_receipt.journal_bytes_written;
            if round > warmup {
                owner_ns.push(wall);
                internal_us.push(output.tick.resource_receipt.execution_micros);
                queue_us.push(output.tick.resource_receipt.queue_age_micros);
                abstained += u64::from(output.tick.abstain);
            }
        }
        if round > warmup {
            batch_ns.push(batch_start.elapsed().as_nanos() as u64);
        }
    }
    let measured_sizes = measured_sizes(root, count)?;
    if measured_sizes.0 - initial_sizes.0 != counted_journal_bytes {
        return Err("journal byte receipt mismatch".into());
    }
    let before = anchors(&owners)?;
    let peak = process_memory("VmHWM:")?;
    drop(owners);
    let restart = Instant::now();
    let mut reopened = (0..count)
        .map(|i| open_owner(root, i, projection))
        .collect::<Outcome<Vec<_>>>()?;
    let recovery_ns = restart.elapsed().as_nanos() as u64;
    if anchors(&reopened)? != before {
        return Err("all-owner recovery digest mismatch".into());
    }
    let calls_before = projection.calls;
    for (index, owner) in reopened.iter_mut().enumerate() {
        let a = owner.current_anchor()?.ok_or("missing reopened anchor")?;
        projection.queue_started = Instant::now();
        let mut port = InferenceControlModelPort::new(projection);
        owner.tick(
            &mut port,
            config::input(index, a.sequence + 1, a.checkpoint_digest),
        )?;
    }
    if projection.calls - calls_before != count {
        return Err("continuation invocation count mismatch".into());
    }
    Ok(
        json!({"schema":"rrsnn.native-owner-components.v1","instances":count,
        "unit":"one unmodified NeuronRuntime + one SparseJournal + one independent FileAnchorWitnessStore",
        "warmup_rounds":warmup,"measured_rounds":rounds,"queue_capacity":count,
        "initialize_ns":initialize_ns,"owner_wall_ns":owner_ns,"batch_wall_ns":batch_ns,
        "runtime_receipt_execution_us":internal_us,"queue_age_us":queue_us,
        "peak_rss_bytes":peak,"journal_bytes":measured_sizes.0,"witness_bytes":measured_sizes.1,
        "journal_bytes_added":measured_sizes.0-initial_sizes.0,
        "witness_bytes_added":measured_sizes.1-initial_sizes.1,
        "all_owner_recovery_ns":recovery_ns,"recovery_anchor_digest":before.to_string(),
        "continuation_owner_ticks":count,"actual_model_calls":projection.calls,"abstained_measured":abstained,
        "scope":{"native_owner_executed":true,"upstream_source_modified":false,
            "production_cell_workload":false,"agentd_cns_router":false,"trained_rr_model":false,
            "calibration_fixture_only":true,"dot_verified":false,"future_utility_measured":false,
            "activation_allowed":false}}),
    )
}

struct PausingWitness {
    inner: FileAnchorWitnessStore,
    sequence: u64,
    phase: String,
}
impl PausingWitness {
    fn pause(&self, phase: &str, next: JournalAnchor) {
        if self.sequence == next.sequence && self.phase == phase {
            println!("{}", json!({"ready":phase,"sequence":next.sequence}));
            io::stdout()
                .flush()
                .expect("flush supervised crash barrier");
            let mut line = String::new();
            io::stdin()
                .read_line(&mut line)
                .expect("supervisor barrier");
            panic!("fault supervisor must terminate this process at the barrier");
        }
    }
}
impl AnchorWitnessStore for PausingWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.pause("before_witness", next);
        self.inner.compare_and_swap(expected, next)?;
        self.pause("after_witness", next);
        Ok(())
    }
}
fn crash_worker(
    root: &Path,
    phase: String,
    sequence: u64,
    projection: &mut Projection,
) -> Outcome<()> {
    if !["before_witness", "after_witness"].contains(&phase.as_str()) || ![1, 2].contains(&sequence)
    {
        return Err("invalid supervised crash case".into());
    }
    fs::create_dir(root)?;
    let (j, w) = paths(root, 0);
    let native = config::native();
    let witness = PausingWitness {
        inner: FileAnchorWitnessStore::open(fresh(&w)?, config::scope(0), native.generation, CAP)?,
        sequence,
        phase,
    };
    let mut owner = NeuronRuntime::bootstrap(
        fresh(&j)?,
        native,
        config::scope(0),
        CAP,
        config::config(projection),
        witness,
    )?;
    for seq in 1..=sequence {
        let cp = owner
            .current_anchor()?
            .map_or(Digest32::ZERO, |a| a.checkpoint_digest);
        let mut port = InferenceControlModelPort::new(projection);
        owner.tick(&mut port, config::input(0, seq, cp))?;
    }
    Err("fault barrier not reached".into())
}
fn recovery_probe(root: &Path, projection: &mut Projection) -> Outcome<Value> {
    let (j, w) = paths(root, 0);
    let native = config::native();
    let witness =
        FileAnchorWitnessStore::open(file(&w)?, config::scope(0), native.generation, CAP)?;
    if witness.current()?.is_none() {
        let journal_bytes = fs::metadata(&j)?.len();
        let bootstrap = NeuronRuntime::bootstrap(
            file(&j)?,
            native,
            config::scope(0),
            CAP,
            config::config(projection),
            witness,
        );
        if !matches!(
            bootstrap,
            Err(NeuronRuntimeError::BootstrapRequiresEmptyJournal)
        ) {
            return Err("unexpected initial no-anchor recovery behavior".into());
        }
        return Ok(
            json!({"recovered":false,"reason":"first commit has no witness; bootstrap rejects nonempty journal; recovery requires an anchor",
            "journal_bytes":journal_bytes,"model_calls":0,"source_behavior_preserved":true}),
        );
    }
    drop(witness);
    let mut owner = open_owner(root, 0, projection)?;
    let a = owner.current_anchor()?.ok_or("missing restored anchor")?;
    let model_calls_before = projection.calls;
    let mut port = InferenceControlModelPort::new(projection);
    let output = owner.tick(
        &mut port,
        config::input(0, a.sequence + 1, a.checkpoint_digest),
    )?;
    Ok(
        json!({"recovered":true,"recovered_sequence":a.sequence,"recovered_digest":a.checkpoint_digest.to_string(),
        "model_calls_during_recovery":model_calls_before,"next_sequence":a.sequence+1,
        "next_checkpoint":output.tick.checkpoint_after.to_string(),"next_model_calls":projection.calls-model_calls_before}),
    )
}
fn validate(root: &Path, projection: &mut Projection) -> Outcome<Value> {
    fs::create_dir(root)?;
    let mut owner = fresh_owner(root, 0, projection)?;
    projection.corrupt_receipt = true;
    let invalid = owner.tick(
        &mut InferenceControlModelPort::new(projection),
        config::input(0, 1, Digest32::ZERO),
    );
    if invalid.is_ok() || owner.current_anchor()?.is_some() {
        return Err("corrupt receipt was committed".into());
    }
    projection.corrupt_receipt = false;
    let first = owner.tick(
        &mut InferenceControlModelPort::new(projection),
        config::input(0, 1, Digest32::ZERO),
    )?;
    let calls = projection.calls;
    let stale = owner.tick(
        &mut InferenceControlModelPort::new(projection),
        config::input(0, 1, Digest32::ZERO),
    );
    if stale.is_ok() || projection.calls != calls {
        return Err("stale checkpoint invoked the model".into());
    }
    let (_, w) = paths(root, 0);
    let locked = FileAnchorWitnessStore::open(
        file(&w)?,
        config::scope(0),
        config::native().generation,
        CAP,
    );
    if !matches!(locked, Err(WitnessStoreError::Busy)) {
        return Err("independent witness writer not fenced".into());
    }
    drop(owner);
    let mut recovered = open_owner(root, 0, projection)?;
    if recovered
        .current_anchor()?
        .ok_or("missing recovered anchor")?
        .checkpoint_digest
        != first.tick.checkpoint_after
    {
        return Err("clean recovery changed checkpoint".into());
    }
    let second = recovered.tick(
        &mut InferenceControlModelPort::new(projection),
        config::input(0, 2, first.tick.checkpoint_after),
    )?;
    if second.signal.authority.grants_any() {
        return Err("runtime output grants authority".into());
    }
    Ok(
        json!({"passed":5,"checks":["corrupt model receipt rejected before commit","stale checkpoint rejected before model invocation",
        "independent witness writer fenced","actual owner clean recovery and continuation","all output authority denied"],
        "first_checkpoint":first.tick.checkpoint_after.to_string(),"second_checkpoint":second.tick.checkpoint_after.to_string(),
        "scope":"real upstream owner components with executed fixed projection; no production qualification"}),
    )
}
fn main() -> Outcome<()> {
    let args = std::env::args().collect::<Vec<_>>();
    if args.len() < 4 {
        return Err("usage: native-owner MODE NEW_RUN_DIRECTORY DEVICE_METADATA [COUNTS]".into());
    }
    let root = Path::new(&args[2]);
    let binary = fs::read(std::env::current_exe()?)?;
    let device = fs::read(&args[3])?;
    let mut projection = Projection::new(&binary, &device);
    let result = match args[1].as_str() {
        "measure" if args.len() == 7 => benchmark(
            root,
            args[4].parse()?,
            args[5].parse()?,
            args[6].parse()?,
            &mut projection,
        )?,
        "validate" if args.len() == 4 => validate(root, &mut projection)?,
        "crash" if args.len() == 6 => {
            crash_worker(root, args[4].clone(), args[5].parse()?, &mut projection)?;
            json!(null)
        }
        "recover" if args.len() == 4 => recovery_probe(root, &mut projection)?,
        _ => return Err("unsupported mode or arguments".into()),
    };
    println!(
        "{}",
        json!({"result":result,"binary_digest":Digest32::of_bytes(&binary).to_string(),
        "device_metadata_digest":Digest32::of_bytes(&device).to_string(),"weights_digest":projection.tuple.weights_digest.to_string(),
        "native_profile":"upstream Q24 V1; stochastic RR state is not registered by this harness"})
    );
    Ok(())
}
