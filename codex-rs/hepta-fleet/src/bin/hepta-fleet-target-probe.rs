//! Selected-host qualification probe for the existing durable fleet owner.
//!
//! This command writes only to the supplied temporary supervisor state root,
//! records one real procfs capacity observation, reopens it, and emits evidence.

use codex_hepta_fleet::DurableFleetOwner;
use codex_hepta_fleet::LinuxProcfsCapacityObserverV1;
use codex_hepta_fleet::SystemFleetClock;
use codex_hepta_fleet::refresh_capacity_idempotent;
use serde_json::json;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-fleet-target-probe: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let options = Options::parse()?;
    std::fs::create_dir_all(&options.state_root)?;
    let now_ms = unix_ms()?;
    let observer = LinuxProcfsCapacityObserverV1::for_current_host(
        options.host_id.clone(),
        options.failure_domain_id.clone(),
        options.host_generation,
        60_000,
        10_000,
    )?;
    let mut owner = DurableFleetOwner::open_supervisor_state_root(
        &options.state_root,
        Arc::new(SystemFleetClock),
    )?;
    let receipt = refresh_capacity_idempotent(
        &mut owner,
        &format!("target-host-capacity-{now_ms}"),
        &observer,
    )?;
    drop(owner);
    let mut reopened = DurableFleetOwner::open_supervisor_state_root(
        &options.state_root,
        Arc::new(SystemFleetClock),
    )?;
    let metrics = reopened.metrics()?;
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "schema_version": 1,
            "candidate_generation": receipt.generation,
            "candidate_state_sha256": receipt.state_sha256,
            "host_id": options.host_id,
            "failure_domain_id": options.failure_domain_id,
            "host_generation": options.host_generation,
            "observed_capacity": metrics.fleet_observed_capacity,
            "stale_hosts": metrics.fleet_stale_hosts,
            "reopen_verified": true,
            "claim_boundary": {
                "selected_host_observation": true,
                "provider_execution": false,
                "deployment_acceptance": false,
                "release_authority": false
            }
        }))?
    );
    Ok(())
}

fn unix_ms() -> Result<u64, Box<dyn std::error::Error>> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

struct Options {
    state_root: PathBuf,
    host_id: String,
    failure_domain_id: String,
    host_generation: u64,
}

impl Options {
    fn parse() -> Result<Self, Box<dyn std::error::Error>> {
        let mut arguments = std::env::args_os().skip(1);
        let mut state_root = None;
        let mut host_id = None;
        let mut failure_domain_id = None;
        let mut host_generation = None;
        while let Some(flag) = arguments.next() {
            let value = arguments.next().ok_or("missing argument value")?;
            match flag.to_str() {
                Some("--state-root") if state_root.is_none() => {
                    state_root = Some(PathBuf::from(value));
                }
                Some("--host-id") if host_id.is_none() => {
                    host_id = Some(value.into_string().map_err(|_| "host ID is not UTF-8")?);
                }
                Some("--failure-domain-id") if failure_domain_id.is_none() => {
                    failure_domain_id = Some(
                        value
                            .into_string()
                            .map_err(|_| "failure-domain ID is not UTF-8")?,
                    );
                }
                Some("--host-generation") if host_generation.is_none() => {
                    host_generation = Some(
                        value
                            .to_str()
                            .ok_or("host generation is not UTF-8")?
                            .parse::<u64>()?,
                    );
                }
                _ => return Err("unexpected or duplicate argument".into()),
            }
        }
        let state_root = state_root.ok_or("--state-root is required")?;
        if !state_root.is_absolute() {
            return Err("--state-root must be absolute".into());
        }
        let host_generation = host_generation.ok_or("--host-generation is required")?;
        if host_generation == 0 {
            return Err("--host-generation must be non-zero".into());
        }
        Ok(Self {
            state_root,
            host_id: host_id.ok_or("--host-id is required")?,
            failure_domain_id: failure_domain_id.ok_or("--failure-domain-id is required")?,
            host_generation,
        })
    }
}
