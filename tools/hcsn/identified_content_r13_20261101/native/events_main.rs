//! A fresh process reconstructs model, hazard exposure and PRNG from checkpoint.
mod checkpoint;
mod core;
mod events;
mod prepared;
mod sha256;

use events::HazardPolicy;
use events::PathState;
use std::fmt::Write;
use std::path::Path;

fn finite(x: f64) -> String {
    if x.is_finite() {
        x.to_string()
    } else {
        "null".into()
    }
}

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 6 {
        return Err("Usage: hcsn-events-r13 init MODEL SCRIPT NEW_CHECKPOINT SEED | resume CHECKPOINT SCRIPT NEW_CHECKPOINT EXPECTED_MODEL_VERSION".into());
    }
    let mut state = match args[1].as_str() {
        "init" => {
            let (model, prior) = checkpoint::model_file(Path::new(&args[2]))?;
            PathState::new(model, &prior, args[5].parse().map_err(|_| "Invalid seed")?)?
        }
        "resume" => checkpoint::restore(
            Path::new(&args[2]),
            args[5].parse().map_err(|_| "Invalid expected version")?,
        )?,
        _ => return Err("Unknown operation".into()),
    };
    let initial_time = state.time;
    let initial_state = state.current;
    let script = checkpoint::read(Path::new(&args[3]))?;
    let mut jumps = Vec::new();
    let mut migrations = Vec::new();
    for (index, line) in script.lines().enumerate() {
        let fields: Vec<_> = line.split_whitespace().collect();
        if fields.is_empty() || fields[0].starts_with('#') {
            continue;
        }
        if index > 100_000 {
            return Err("Script command limit exceeded".into());
        }
        match fields.as_slice() {
            ["advance", dt] => {
                let dt: f64 = dt.parse().map_err(|_| "Invalid dt")?;
                if !dt.is_finite() || dt < 0.0 {
                    return Err("Invalid dt".into());
                }
                jumps.extend(state.advance_to(state.time + dt)?);
            }
            ["migrate", at, file, policy] => {
                let at = at.parse().map_err(|_| "Invalid migration time")?;
                let policy = match *policy {
                    "preserve" => HazardPolicy::PreserveExposure,
                    "resample" => HazardPolicy::Resample,
                    _ => return Err("Expected preserve or resample".into()),
                };
                let (new_model, _) = checkpoint::model_file(Path::new(file))?;
                jumps.extend(state.advance_to(at)?);
                let old_version = state.model.version;
                let old_identity = state.model.identity.clone();
                let old_rate = state.rate();
                let old_next = finite(state.next_time()?);
                let remaining = state.remaining_exposure();
                jumps.extend(state.migrate(at, new_model, policy)?);
                migrations.push(format!("{{\"at\":{at},\"state\":{},\"old_version\":{old_version},\"new_version\":{},\"old_identity\":\"{old_identity}\",\"new_identity\":\"{}\",\"policy\":\"{}\",\"old_rate\":{old_rate},\"new_rate\":{},\"old_next_time_diagnostic\":{old_next},\"old_remaining_exposure\":{remaining},\"new_threshold\":{},\"new_next_time_diagnostic\":{}}}",
                    state.current, state.model.version, state.model.identity,
                    match policy { HazardPolicy::PreserveExposure => "preserve", HazardPolicy::Resample => "resample" },
                    state.rate(), state.threshold, finite(state.next_time()?)));
            }
            _ => {
                return Err(
                    "Expected advance dt or migrate absolute_time model_file preserve|resample"
                        .into(),
                )
            }
        }
        if jumps.len() > 1_000_000 {
            return Err("Trace event limit exceeded".into());
        }
    }
    let checksum = checkpoint::persist(&state, Path::new(&args[4]))?;
    let mut trace = String::new();
    for (index, jump) in jumps.iter().enumerate() {
        if index > 0 {
            trace.push(',');
        }
        write!(
            trace,
            "{{\"time\":{},\"from\":{},\"to\":{},\"kind\":\"{}\",\"model_version\":{}}}",
            jump.time, jump.from, jump.to, jump.kind, jump.version
        )
        .map_err(|e| e.to_string())?;
    }
    let migrations = migrations.join(",");
    let pid = std::process::id();
    let source = checkpoint::SOURCE;
    println!("{{\"schema\":\"hcsn-r13-exposure-events-v1\",\"pid\":{pid},\"source_identity\":\"{source}\",\"checkpoint_sha256\":\"{checksum}\",\"model_version\":{},\"model_identity\":\"{}\",\"initial_state\":{initial_state},\"initial_time\":{initial_time},\"current\":{},\"time\":{},\"hazard_anchor\":{},\"threshold\":{},\"remaining_exposure\":{},\"next_time_diagnostic\":{},\"rng_state\":{},\"counts\":{:?},\"migration_count\":{},\"history_sha256\":\"{}\",\"migrations\":[{migrations}],\"jumps\":[{trace}]}}",
        state.model.version, state.model.identity, state.current, state.time, state.hazard_anchor,
        state.threshold, state.remaining_exposure(), finite(state.next_time()?), state.rng,
        state.counts, state.migrations, state.history);
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("REFUSE: {error}");
        std::process::exit(2);
    }
}
