//! Experimental host adapter over the unchanged production journal APIs.
//! Receipt hashing binds evidence; it does not authenticate a remote provider.
#![forbid(unsafe_code)]

use codex_hepta_neuron::{
    AnchorWitnessStore, FileAnchorWitnessStore, JournalAnchor, JournalScope, SparseConfig,
    SparseJournal, SparseTick,
};
use codex_hepta_types::{AuthorityPosture, Digest32, Generation};
use std::error::Error;
use std::fs::{self, File, OpenOptions};
use std::io;
use std::io::Read;
use std::path::Path;
use std::str::FromStr;

const Q: i64 = 1 << 24;

fn open_owned(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
}

fn run() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 9 {
        return Err(
            "usage: bridge ROOT RUN_SHA OBJECTIVE_SHA GENERATION SEQUENCE BEFORE_SHA RECEIPT PHASE"
                .into(),
        );
    }
    let root = Path::new(&args[1]);
    let run = Digest32::from_str(&args[2])?;
    let objective = Digest32::from_str(&args[3])?;
    let generation = Generation::new(args[4].parse()?)?;
    let sequence: u64 = args[5].parse()?;
    let before = Digest32::from_str(&args[6])?;
    if run.is_zero() || objective.is_zero() || sequence == 0 || sequence > 128 {
        return Err("invalid bounded host context".into());
    }
    let mut receipt = Vec::with_capacity(1025);
    File::open(&args[7])?.take(1025).read_to_end(&mut receipt)?;
    if receipt.len() > 1024 {
        return Err("provider receipt exceeds bound".into());
    }
    let text = std::str::from_utf8(&receipt)?;
    let fields: Vec<&str> = text
        .strip_suffix('\n')
        .ok_or("missing canonical newline")?
        .split('\t')
        .collect();
    if fields.len() != 7
        || fields[0] != "EFFECT"
        || fields[1] != args[2]
        || !matches!(fields[3], "READ" | "REFRESH")
    {
        return Err("provider receipt context or type mismatch".into());
    }
    let token: u8 = fields[4].parse()?;
    let fee: u64 = fields[5].parse()?;
    let effect_index: u64 = fields[6].parse()?;
    if fields[2].is_empty()
        || fields[2].len() > 160
        || token > 4
        || (fields[3] == "REFRESH" && token > 3)
        || fee > 1_000_000
        || effect_index != sequence
    {
        return Err("provider effect outside declared profile".into());
    }
    if !matches!(args[8].as_str(), "ack" | "after_append") {
        return Err("unknown fault phase".into());
    }
    let scope = JournalScope {
        scope_digest: run,
        objective_digest: objective,
    };
    let config = SparseConfig {
        model_digest: Digest32::of_bytes(b"hcsn.experimental.provider-receipt.bridge.v1"),
        normalization_digest: Digest32::of_bytes(b"hcsn.receipt.integer-microcredit.v1"),
        generation,
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    };
    // Directory enrollment and provider authentication remain host duties.
    fs::create_dir_all(root)?;
    let mut witness =
        FileAnchorWitnessStore::open(open_owned(&root.join("witness"))?, scope, generation, 128)?;
    let acknowledged = witness.current()?;
    let next_sequence = acknowledged.map_or(1, |anchor| anchor.sequence + 1);
    if sequence > next_sequence {
        return Err("an earlier append must be acknowledged first".into());
    }
    let mut journal = match acknowledged {
        Some(anchor) => SparseJournal::open_anchored(
            open_owned(&root.join("journal"))?,
            config,
            scope,
            128,
            anchor,
        )?,
        None => SparseJournal::open(open_owned(&root.join("journal"))?, config, scope, 128)?,
    };
    let tick = SparseTick {
        scope_digest: run,
        objective_digest: objective,
        ndu_digest: objective,
        body_digest: Digest32::of_bytes(b"hcsn.r18.receipt.bridge.body.v1"),
        input_digest: Digest32::of_bytes(&receipt),
        sequence,
        monotonic_micros: sequence.checked_mul(1000).ok_or("clock overflow")?,
        drive_q24: vec![(i64::from(token) + 1) * Q / 8, Q / 4, 0, 0, 0],
        prediction_q24: vec![0; 5],
    };
    let committed = journal.commit(before, &tick)?;
    if committed.authority != AuthorityPosture::DENY_ALL || !committed.requires_calibration {
        return Err("production mechanism unexpectedly granted authority or calibration".into());
    }
    if args[8] == "after_append" {
        println!(
            "{{\"phase\":\"after_append\",\"sequence\":{sequence},\"checkpoint\":\"{}\"}}",
            committed.checkpoint_after
        );
        use std::io::Write;
        std::io::stdout().flush()?;
        // Parent kills this process after receiving the durable boundary.
        loop {
            std::thread::park();
        }
    }
    if acknowledged.is_none_or(|anchor| anchor.sequence < sequence) {
        witness.compare_and_swap(
            acknowledged,
            JournalAnchor {
                sequence,
                checkpoint_digest: committed.checkpoint_after,
            },
        )?;
    }
    let frontier = witness.current()?.ok_or("missing acknowledged frontier")?;
    println!(
        "{{\"phase\":\"ack\",\"sequence\":{sequence},\"receipt_sha256\":\"{}\",\"before\":\"{}\",\"checkpoint\":\"{}\",\"witness_sequence\":{},\"requires_calibration\":true,\"authority\":\"DENY_ALL\"}}",
        tick.input_digest,
        committed.checkpoint_before,
        committed.checkpoint_after,
        frontier.sequence
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
