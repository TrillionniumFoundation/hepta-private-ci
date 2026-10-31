//! Linux-only finite-kernel research executable; no production activation.
#[path = "../../round9_20261031/native/src/cell.rs"]
mod cell;
#[path = "../../round9_20261031/native/src/content.rs"]
mod content;
#[path = "../../round9_20261031/native/src/native.rs"]
mod native;
mod owner;
mod policy;
mod port;
mod store;
mod task;

use cell::Family;
use owner::Open;
use owner::Owner;
use policy::Controller;
use serde_json::json;
use std::collections::BTreeMap;
use std::path::Path;
use std::time::Instant;

fn run() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let mut options = BTreeMap::new();
    while let Some(key) = args.next() {
        if ![
            "--public",
            "--content-model",
            "--policy",
            "--family",
            "--controller",
            "--steps",
            "--snapshot",
            "--ack",
        ]
        .contains(&key.as_str())
        {
            return Err(format!("unknown option: {key}"));
        }
        let value = args.next().ok_or_else(|| format!("missing value: {key}"))?;
        if options.insert(key.clone(), value).is_some() {
            return Err(format!("duplicate option: {key}"));
        }
    }
    let get = |name: &str| {
        options
            .get(name)
            .map(String::as_str)
            .ok_or_else(|| format!("required option: {name}"))
    };
    let family = match get("--family")? {
        "ordinary" => Family::Ordinary,
        "distribution" => Family::Distribution,
        _ => return Err("family must be ordinary or distribution".into()),
    };
    let controller = match get("--controller")? {
        "fixed" => Controller::Fixed,
        "value" => Controller::Value,
        "direct_fixed" => Controller::DirectFixed,
        _ => return Err("controller must be fixed, value or direct_fixed".into()),
    };
    let steps = get("--steps")?
        .parse::<usize>()
        .map_err(|e| e.to_string())?;
    if steps > 32 {
        return Err("steps envelope 0..32".into());
    }
    let load_start = Instant::now();
    let mut owner = Owner::open(Open {
        public: Path::new(get("--public")?),
        content: Path::new(get("--content-model")?),
        policy: Path::new(get("--policy")?),
        family,
        controller,
        snapshot: Path::new(get("--snapshot")?),
        ack: options.get("--ack").map(String::as_str),
    })?;
    let load_nanos = port::nanos(load_start);
    let start = owner.pair.clone();
    let mut receipts = Vec::new();
    for _ in 0..steps {
        if owner.pair.task.terminal {
            break;
        }
        receipts.push(owner.step()?);
    }
    println!(
        "{}",
        json!({ "schema":"hcsn.task.native.run.v1", "source_digest":env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST"),
        "public_sha256":owner.pair.identity.public_sha256, "policy_sha256":owner.pair.identity.policy_sha256,
        "content_model_sha256":owner.pair.identity.content_model_sha256, "family":family, "controller":controller,
        "start":start, "end":owner.pair, "receipts":receipts, "acknowledged_sha256":owner.acknowledged_sha256,
        "external_ack_verified":owner.external_ack_verified, "load_nanos":load_nanos,
        "artifact_load_nanos":owner.artifact_load_nanos,
        "native_neuron_runtime":true, "finite_kernel":true, "production_activation":false, "authority":"DENY_ALL",
        "recovery_scope":"acknowledged synchronous action boundaries; incomplete commit refuses replay",
        "cost_scope":"stage nanoseconds are disjoint; owner_nanos overlaps them; artifact_load_nanos is a subset of load_nanos; process CPU/energy measured externally" })
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        println!(
            "{}",
            json!({"ok":false,"error":error,"production_activation":false,"authority":"DENY_ALL"})
        );
        std::process::exit(1);
    }
}

#[cfg(test)]
#[path = "native_tests.rs"]
mod tests;
