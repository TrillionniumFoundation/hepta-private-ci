//! Read-only numerical probe of the exact Cell implementation used by the owner.
#[path = "../../round9_20261031/native/src/cell.rs"]
mod cell;

use cell::Cell;
use cell::Family;
use serde::Deserialize;
use serde_json::json;
use std::io::Read;
use std::io::{self};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Event {
    driver: f64,
    micros: u64,
    reset: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    parameters: [f64; 11],
    family: Family,
    seed: u64,
    events: Vec<Event>,
    driver: f64,
    horizon_micros: u64,
    restore_after: Option<usize>,
}

fn run(request: Request) -> Result<serde_json::Value, String> {
    if request.events.len() > 4096 {
        return Err("probe event budget".into());
    }
    let mut cell = Cell::new(request.parameters, request.family, request.seed)?;
    let mut receipts = Vec::new();
    for (i, event) in request.events.iter().enumerate() {
        let jumps = cell.advance(i as u64 + 1, event.driver, event.micros, event.reset)?;
        if request.restore_after == Some(i + 1) {
            let snapshot = cell.snapshot();
            let mut restored = Cell::new(request.parameters, request.family, request.seed)?;
            restored.restore(&snapshot)?;
            cell = restored;
        }
        receipts.push(json!({"snapshot":cell.snapshot(), "jumps":jumps}));
    }
    let features = cell.query(request.driver, request.horizon_micros)?;
    Ok(
        json!({"schema":"hcsn.finite-native-probe.r11.v1", "finite_model":true,
        "continuum_equivalence":false, "production_activation":false,
        "generator":cell.generator(request.driver), "features":features,
        "probability":cell.probability, "events":cell.events, "gates":cell.gates,
        "snapshot":cell.snapshot(), "receipts":receipts}),
    )
}

fn main() {
    let result = (|| {
        let mut input = String::new();
        io::stdin()
            .take(1_000_001)
            .read_to_string(&mut input)
            .map_err(|e| e.to_string())?;
        if input.len() > 1_000_000 {
            return Err("probe input size budget".into());
        }
        let request = serde_json::from_str(&input).map_err(|e| e.to_string())?;
        run(request)
    })();
    match result {
        Ok(value) => println!("{value}"),
        Err(error) => {
            println!("{}", json!({"error":error}));
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
#[path = "probe_tests.rs"]
mod tests;
