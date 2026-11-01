//! CLI for the durable research owner. No experiment labels are accepted here.
mod cell;
mod content;
mod owner;
mod policy;
mod port;
mod runtime;
mod store;
mod task;
#[cfg(test)]
mod tests;

use serde::Serialize;
use std::path::PathBuf;
use std::time::Instant;

struct Arguments {
    public: PathBuf,
    content: PathBuf,
    policy: PathBuf,
    snapshot: PathBuf,
    controller: policy::Controller,
    seed: u64,
    steps: usize,
    ack: Option<String>,
    forced: Vec<usize>,
    mode: String,
}

fn arguments() -> Result<Arguments, String> {
    let mut values = std::collections::BTreeMap::new();
    let mut args = std::env::args().skip(1);
    while let Some(key) = args.next() {
        if ![
            "--public",
            "--content-model",
            "--policy",
            "--snapshot",
            "--controller",
            "--seed",
            "--steps",
            "--ack",
            "--forced-actions",
            "--mode",
        ]
        .contains(&key.as_str())
        {
            return Err(format!("unknown argument {key}"));
        }
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {key}"))?;
        if values.insert(key.clone(), value).is_some() {
            return Err(format!("duplicate argument {key}"));
        }
    }
    let required = |key: &str| {
        values
            .get(key)
            .cloned()
            .ok_or_else(|| format!("required argument {key}"))
    };
    let controller = match required("--controller")?.as_str() {
        "fixed" => policy::Controller::Fixed,
        "value" => policy::Controller::Value,
        _ => return Err("controller must be fixed or value".into()),
    };
    let forced = match values.get("--forced-actions") {
        None => vec![],
        Some(s) => s
            .split(',')
            .map(|name| {
                task::NAMES
                    .iter()
                    .position(|x| *x == name)
                    .ok_or_else(|| format!("unknown forced action {name}"))
            })
            .collect::<Result<Vec<_>, _>>()?,
    };
    let mode = values
        .get("--mode")
        .cloned()
        .unwrap_or_else(|| "experiment".into());
    if !["experiment", "qualification"].contains(&mode.as_str())
        || (!forced.is_empty() && mode != "qualification")
    {
        return Err("forced control is available only in explicit qualification mode".into());
    }
    let steps = required("--steps")?
        .parse::<usize>()
        .map_err(|e| e.to_string())?;
    if steps > 7 || (!forced.is_empty() && forced.len() != steps) {
        return Err(
            "steps must be 0..7, with one supplied forced action for each requested step".into(),
        );
    }
    Ok(Arguments {
        public: required("--public")?.into(),
        content: required("--content-model")?.into(),
        policy: required("--policy")?.into(),
        snapshot: required("--snapshot")?.into(),
        controller,
        seed: required("--seed")?
            .parse::<u64>()
            .map_err(|e| e.to_string())?,
        steps,
        ack: values.get("--ack").cloned(),
        forced,
        mode,
    })
}

pub fn cpu_nanos() -> Result<u64, String> {
    let mut time = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // The operating-system process clock includes all native CPU work in this invocation.
    if unsafe { libc::clock_gettime(libc::CLOCK_PROCESS_CPUTIME_ID, &mut time) } != 0 {
        return Err(std::io::Error::last_os_error().to_string());
    }
    Ok((time.tv_sec as u64)
        .saturating_mul(1_000_000_000)
        .saturating_add(time.tv_nsec as u64))
}

#[derive(Serialize)]
struct Output {
    schema: &'static str,
    before: owner::Pair,
    after: owner::Pair,
    receipts: Vec<owner::Receipt>,
    acknowledged_sha256: String,
    source_digest: &'static str,
    family: String,
    fit: u64,
    controller: policy::Controller,
    actual_native: bool,
    production_activation: bool,
    authority: &'static str,
    mode: String,
    forced_control: bool,
    external_ack_verified: bool,
    artifact_load_nanos: u64,
    wall_nanos: u64,
    cpu_nanos: u64,
    initial_persistence_bytes: u64,
    persistence_bytes: u64,
    calibration_scope: &'static str,
    approximation: &'static str,
}

fn run() -> Result<(), String> {
    let start = Instant::now();
    let cpu_start = cpu_nanos()?;
    let args = arguments()?;
    let mut owner = owner::Owner::open(owner::Open {
        public: &args.public,
        content: &args.content,
        policy: &args.policy,
        snapshot: &args.snapshot,
        controller: args.controller,
        seed: args.seed,
        ack: args.ack.as_deref(),
        mode: &args.mode,
        first_forced: args.forced.first().copied(),
    })?;
    let before = owner.pair.clone();
    let mut receipts = vec![];
    for i in 0..args.steps {
        if owner.pair.task.terminal {
            break;
        }
        receipts.push(owner.step(args.forced.get(i).copied())?);
    }
    let persistence_bytes = owner.initial_persistence_bytes
        + receipts
            .iter()
            .map(|r| r.journal_bytes + r.witness_bytes + r.checkpoint_bytes)
            .sum::<u64>();
    let output = Output {
        schema: "digital-read-before-native-run-v1",
        before,
        after: owner.pair.clone(),
        receipts,
        acknowledged_sha256: owner.acknowledged_sha256.clone(),
        source_digest: env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST"),
        family: owner.policy.family.clone(),
        fit: owner.policy.fit,
        controller: args.controller,
        actual_native: true,
        production_activation: false,
        authority: "DENY_ALL",
        mode: args.mode,
        forced_control: !args.forced.is_empty(),
        external_ack_verified: owner.external_ack_verified,
        artifact_load_nanos: owner.artifact_load_nanos,
        wall_nanos: port::nanos(start),
        cpu_nanos: cpu_nanos()?.saturating_sub(cpu_start),
        initial_persistence_bytes: owner.initial_persistence_bytes,
        persistence_bytes,
        calibration_scope: "research worst-case placeholder; no calibration or production qualification claim",
        approximation: "hard-sampled 17-state finite projection of exported Brownian-image tables; not an exact continuous-path simulation",
    };
    println!(
        "{}",
        serde_json::to_string(&output).map_err(|e| e.to_string())?
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!(
            "{}",
            serde_json::json!({"schema":"digital-read-before-native-error-v1", "error":error})
        );
        std::process::exit(2);
    }
}
