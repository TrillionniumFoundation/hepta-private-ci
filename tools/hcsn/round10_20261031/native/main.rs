//! Linux research executable; uses the original Hepta native runtime and decoder.
#[path = "../../round9_20261031/native/src/cell.rs"]
mod cell;
#[path = "../../round9_20261031/native/src/content.rs"]
mod content;
#[path = "../../round9_20261031/native/src/native.rs"]
mod native;
#[path = "../../round9_20261031/native/src/owner.rs"]
mod owner;
mod contract;
mod policy;
mod storage;
mod task_owner;

use serde::Deserialize;
use serde_json::json;
use std::io::BufRead;
use std::io::Write;
use std::path::Path;
use task_owner::TaskOwner;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Model {
    parameters: [f64; 11],
    family: cell::Family,
    seed_hex: String,
    content_model: String,
    content_model_sha256: String,
    tick_micros: u64,
    task: contract::Config,
    policy: policy::Policy,
    payloads: Vec<content::Request>,
}

#[derive(Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    Decide { task_before: String, requested: Option<contract::Action> },
    Snapshot,
}

fn run() -> Result<(), String> {
    let args = std::env::args().collect::<Vec<_>>();
    if args.len() != 4 {
        return Err("usage: hcsn-owner-preread CONFIG.json OWNER_DIR ACKNOWLEDGED_TASK_SHA256".into());
    }
    let bytes = storage::read(Path::new(&args[1]), /*limit*/ 32_000_000)?;
    let model: Model = serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
    let seed = u64::from_str_radix(&model.seed_hex, /*radix*/ 16).map_err(|error| error.to_string())?;
    let setup = task_owner::Setup {
        cell: cell::Cell::new(model.parameters, model.family, seed)?,
        content_model: content::Model::load(Path::new(&model.content_model), &model.content_model_sha256)?,
        task: model.task,
        policy: model.policy,
        payloads: model.payloads,
        tick_micros: model.tick_micros,
    };
    let mut owner = TaskOwner::open(Path::new(&args[2]), &args[3], setup)?;
    for line in std::io::stdin().lock().lines() {
        let line = line.map_err(|error| error.to_string())?;
        if line.len() > 32_768 {
            return Err("request limit".into());
        }
        let response = match serde_json::from_str::<Command>(&line) {
            Ok(Command::Snapshot) => json!({"ok":true,"task_after":owner.acknowledged,
                "state":owner.state,"posterior":owner.task.posterior(&owner.state),
                "legal":owner.task.legal(&owner.state),"state_key":owner.state.key()}),
            Ok(Command::Decide { task_before, requested }) => match owner.step(&task_before, requested) {
                Ok(receipt) => json!({"ok":true,"receipt":receipt}),
                Err(error) => json!({"ok":false,"error":error}),
            },
            Err(error) => json!({"ok":false,"error":error.to_string()}),
        };
        println!("{response}");
        std::io::stdout().flush().map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
#[path = "task_tests.rs"]
mod tests;
