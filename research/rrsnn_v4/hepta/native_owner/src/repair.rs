//! Explicit initialization recovery experiment. No automatic unanchored fallback.
mod config;
mod model;

use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_neuron::{
    AnchorWitnessStore, FileAnchorWitnessStore, InferenceControlModelPort, JournalAnchor,
    NeuronInferenceControlPort, NeuronRuntime, SparseTick, WitnessStoreError, sparse_tick,
};
use codex_hepta_types::Digest32;
use model::Projection;
use serde_json::{Value, json};
use std::error::Error;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

type Outcome<T> = Result<T, Box<dyn Error>>;
const CAP: usize = 256;

fn file(path: &Path, create: bool) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(create)
        .open(path)
}
fn paths(root: &Path) -> (PathBuf, PathBuf) {
    (root.join("journal-0.bin"), root.join("witness-0.bin"))
}
fn context(model: &Projection) -> Value {
    let native = config::native();
    let scope = config::scope(0);
    json!({"generation":native.generation.get(),"scope":scope.scope_digest.to_string(),
        "objective":scope.objective_digest.to_string(),"native_config":native.digest().expect("valid native").to_string(),
        "weights":model.tuple.weights_digest.to_string(),"runtime":model.tuple.runtime_digest.to_string(),
        "device":model.tuple.device_digest.to_string(),
        "fixture_config_debug_sha256":Digest32::of_bytes(format!("{:?}",config::config(model)).as_bytes()).to_string()})
}
// Independently execute the fixed input/model before the faulting owner exists.
// No journal or witness is opened, scanned, or used to construct this intent.
fn intent(model: &mut Projection) -> Outcome<Value> {
    let runtime = config::config(model);
    let native = config::native();
    let scope = config::scope(0);
    let first_input = config::input(0, 1, Digest32::ZERO).semantic_digest()?;
    let mut previous = None;
    let mut checkpoints = Vec::new();
    for sequence in 1..=3 {
        let input = config::input(
            0,
            sequence,
            previous
                .as_ref()
                .map_or(Digest32::ZERO, codex_hepta_neuron::SparseCheckpoint::digest),
        );
        let input_digest = input.semantic_digest()?;
        let request = NeuronFeatureRequestV1 {
            request_id: input.tick_id.clone(),
            generation: runtime.generation,
            model_id: runtime.model_id.clone(),
            encoder_digest: runtime.encoder_digest,
            head_digest: runtime.head_digest,
            weights_digest: runtime.weights_digest,
            input_digest,
            feature_vector_q24: input.feature_vector_q24.clone(),
            expected_output_width: runtime.state_width,
        };
        let output = model.execute_feature(&request)?;
        let mut body = b"hepta.neuron.body-binding.v1".to_vec();
        body.extend_from_slice(runtime.head_digest.as_array());
        body.extend_from_slice(&runtime.generation.get().to_be_bytes());
        body.extend_from_slice(&input.body_generation.unwrap_or(0).to_be_bytes());
        let tick = SparseTick {
            scope_digest: scope.scope_digest,
            objective_digest: scope.objective_digest,
            ndu_digest: input.ndu_snapshot_digest,
            body_digest: Digest32::of_bytes(&body),
            input_digest,
            sequence,
            monotonic_micros: input.monotonic_time_micros,
            drive_q24: output.drive_q24,
            prediction_q24: output.prediction_q24,
        };
        let (checkpoint, _) = sparse_tick(&native, &tick, previous.as_ref())?;
        checkpoints.push(checkpoint.digest().to_string());
        previous = Some(checkpoint);
    }
    Ok(
        json!({"schema":"rrsnn.initialization-intent.fixture.v1","context":context(model),
        "first_input_digest":first_input.to_string(),"expected_checkpoints":checkpoints}),
    )
}
fn authenticate_intent(
    path: &Path,
    externally_pinned_sha256: &str,
    model: &Projection,
) -> Outcome<JournalAnchor> {
    let bytes = fs::read(path).map_err(|_| "MissingInitializationIntent")?;
    let pinned: Digest32 = externally_pinned_sha256
        .parse()
        .map_err(|_| "InvalidExternalIntentPin")?;
    if pinned.is_zero() || Digest32::of_bytes(&bytes) != pinned {
        return Err("InitializationIntentPinMismatch".into());
    }
    let value: Value = serde_json::from_slice(&bytes)?;
    let object = value.as_object().ok_or("InvalidInitializationIntent")?;
    let mut keys = object.keys().map(String::as_str).collect::<Vec<_>>();
    keys.sort_unstable();
    if keys
        != [
            "context",
            "expected_checkpoints",
            "first_input_digest",
            "schema",
        ]
        || value["schema"] != "rrsnn.initialization-intent.fixture.v1"
        || value["context"] != context(model)
        || value["first_input_digest"]
            != config::input(0, 1, Digest32::ZERO)
                .semantic_digest()?
                .to_string()
    {
        return Err("InitializationIntentBindingMismatch".into());
    }
    let checkpoints = value["expected_checkpoints"]
        .as_array()
        .ok_or("InvalidExpectedCheckpoints")?;
    if checkpoints.len() != 3 {
        return Err("InvalidExpectedCheckpoints".into());
    }
    let first: Digest32 = checkpoints[0]
        .as_str()
        .ok_or("InvalidExpectedFirstAnchor")?
        .parse()?;
    Ok(JournalAnchor {
        sequence: 1,
        checkpoint_digest: first,
    })
}

struct SupervisedWitness {
    inner: FileAnchorWitnessStore,
    sequence: u64,
    phase: String,
}
impl SupervisedWitness {
    fn pause(&self, phase: &str, anchor: JournalAnchor) {
        if self.sequence == anchor.sequence && self.phase == phase {
            println!("{}", json!({"ready":phase,"sequence":anchor.sequence}));
            io::stdout().flush().expect("supervised marker");
            let mut line = String::new();
            io::stdin()
                .read_line(&mut line)
                .expect("supervised barrier");
            panic!("supervisor must kill this process");
        }
    }
}
impl AnchorWitnessStore for SupervisedWitness {
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
fn witness(path: &Path, create: bool, phase: String, sequence: u64) -> Outcome<SupervisedWitness> {
    Ok(SupervisedWitness {
        inner: FileAnchorWitnessStore::open(
            file(path, create)?,
            config::scope(0),
            config::native().generation,
            CAP,
        )?,
        phase,
        sequence,
    })
}
fn crash(
    root: &Path,
    phase: String,
    sequence: u64,
    drift: bool,
    model: &mut Projection,
) -> Outcome<Value> {
    if ![1, 2].contains(&sequence) || !["before_witness", "after_witness"].contains(&phase.as_str())
    {
        return Err("InvalidFaultCase".into());
    }
    fs::create_dir(root)?;
    let (j, w) = paths(root);
    let store = witness(&w, true, phase, sequence)?;
    let mut owner = NeuronRuntime::bootstrap(
        file(&j, true)?,
        config::native(),
        config::scope(0),
        CAP,
        config::config(model),
        store,
    )?;
    for seq in 1..=sequence {
        let cp = owner
            .current_anchor()?
            .map_or(Digest32::ZERO, |a| a.checkpoint_digest);
        let mut input = config::input(0, seq, cp);
        if drift {
            input.feature_vector_q24[0] += model::Q / 8;
            input.input_feature_digest =
                codex_hepta_neuron::canonical_feature_vector_digest_v1(&input.feature_vector_q24);
        }
        owner.tick(&mut InferenceControlModelPort::new(model), input)?;
    }
    Err("FaultBarrierNotReached".into())
}
fn recover(
    root: &Path,
    initial: bool,
    intent_path: &Path,
    pin: &str,
    phase: String,
    model: &mut Projection,
) -> Outcome<Value> {
    // This explicit initial mode is permitted only by an independent controller
    // that still records this generation as pending its first publication.
    // File absence never selects the mode. An old intent is not a lifecycle proof.
    let expected = if initial {
        Some(authenticate_intent(intent_path, pin, model)?)
    } else {
        None
    };
    let (j, w) = paths(root);
    let store = witness(&w, false, phase, 1)?;
    let published = store.current()?;
    let mut owner = if let Some(first) = expected {
        NeuronRuntime::recover_bootstrap_anchored(
            file(&j, false)?,
            config::native(),
            config::scope(0),
            CAP,
            config::config(model),
            first,
            store,
        )?
    } else {
        let anchor = published.ok_or("NoPublishedAnchorNoAutomaticFallback")?;
        NeuronRuntime::recover(
            file(&j, false)?,
            config::native(),
            config::scope(0),
            CAP,
            config::config(model),
            anchor,
            store,
        )?
    };
    let anchor = owner.current_anchor()?.ok_or("MissingRecoveredAnchor")?;
    let calls = model.calls;
    let output = owner.tick(
        &mut InferenceControlModelPort::new(model),
        config::input(0, anchor.sequence + 1, anchor.checkpoint_digest),
    )?;
    if output.signal.authority.grants_any() {
        return Err("UnexpectedAuthority".into());
    }
    Ok(
        json!({"recovered_sequence":anchor.sequence,"recovered_digest":anchor.checkpoint_digest.to_string(),
        "model_calls_during_recovery":calls,"next_sequence":anchor.sequence+1,
        "next_checkpoint":output.tick.checkpoint_after.to_string(),"next_model_calls":model.calls-calls,
        "explicit_initial_mode":initial,"authority_granted":false}),
    )
}
fn run() -> Outcome<Value> {
    let args = std::env::args().collect::<Vec<_>>();
    if args.len() < 4 {
        return Err("usage: repair MODE ROOT METADATA [options]".into());
    }
    let root = Path::new(&args[2]);
    let binary = fs::read(std::env::current_exe()?)?;
    let metadata = fs::read(&args[3])?;
    let mut model = Projection::new(&binary, &metadata);
    let result = match args[1].as_str() {
        "intent" if args.len() == 4 => intent(&mut model)?,
        "crash" if args.len() == 7 => crash(
            root,
            args[4].clone(),
            args[5].parse()?,
            args[6] == "drift",
            &mut model,
        )?,
        "recover-initial" if args.len() == 7 => recover(
            root,
            true,
            Path::new(&args[4]),
            &args[5],
            args[6].clone(),
            &mut model,
        )?,
        "recover-anchored" if args.len() == 4 => {
            recover(root, false, Path::new(""), "", String::new(), &mut model)?
        }
        _ => return Err("UnsupportedMode".into()),
    };
    Ok(
        json!({"result":result,"binary_sha256":Digest32::of_bytes(&binary).to_string(),
        "metadata_sha256":Digest32::of_bytes(&metadata).to_string(),"production_owner_intent":false}),
    )
}
fn main() {
    match run() {
        Ok(value) => println!("{value}"),
        Err(error) => {
            eprintln!("{}", json!({"error":error.to_string()}));
            std::process::exit(2);
        }
    }
}
