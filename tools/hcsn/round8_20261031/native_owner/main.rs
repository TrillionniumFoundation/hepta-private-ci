mod cell;
mod native;
mod owner;
use cell::Cell;
use cell::Family;
use owner::Owner;
use owner::Request;
use serde::Deserialize;
use serde_json::json;
use std::io::BufRead;
use std::io::Write;
use std::path::Path;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Model {
    parameters: [f64; 11],
    family: Family,
    seed_hex: String,
}

fn run() -> Result<(), String> {
    let args = std::env::args().collect::<Vec<_>>();
    if args.len() == 3 && args[1] == "--tail-probe" {
        let model: Model =
            serde_json::from_slice(&std::fs::read(&args[2]).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        let mut rows = Vec::new();
        for index in 0..5 {
            let mut cell = Cell::new(model.parameters, Family::Distribution, 173)?;
            cell.probability = [0.0; 5];
            cell.probability[index] = 1.0;
            for micros in [1, 10, 750_000] {
                rows.push(json!({"initial_state":index,"horizon_micros":micros,
                    "features":cell.query(0.3,micros)?}));
            }
        }
        println!(
            "{}",
            json!({"native_owner_used":false,"driver":0.3,"rows":rows,
            "contract":"pure-physics-tail-probe;all-five-initial-states"})
        );
        return Ok(());
    }
    if args.len() == 4 && args[1] == "--ensemble" {
        let model: Model =
            serde_json::from_slice(&std::fs::read(&args[2]).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        let n = args[3].parse::<u64>().map_err(|e| e.to_string())?;
        if !(100..=50_000).contains(&n) {
            return Err("ensemble envelope".into());
        }
        let mut counts = [0_u64; 5];
        let mut events = 0.0;
        let mut squares = 0.0;
        for seed in 0..n {
            let mut cell = Cell::new(model.parameters, Family::Sampled, seed)?;
            cell.advance(1, 0.3, 4_000_000, false)?;
            counts[cell.index] += 1;
            events += cell.events;
            squares += cell.events * cell.events;
        }
        println!(
            "{}",
            json!({"samples":n,"counts":counts,"event_mean":events/n as f64,
            "event_second_moment":squares/n as f64,"native_owner_used":false,
            "contract":"pure-physics-ensemble;driver=0.3;duration=4s;seeds=0..n"})
        );
        return Ok(());
    }
    if args.len() != 4 {
        return Err("usage: native-cell MODEL.json OWNER_DIR ACKNOWLEDGED_PAIR_SHA256".into());
    }
    let model: Model =
        serde_json::from_slice(&std::fs::read(&args[1]).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    let seed = u64::from_str_radix(&model.seed_hex, 16).map_err(|e| e.to_string())?;
    let cell = Cell::new(model.parameters, model.family, seed)?;
    let mut owner = Owner::open(Path::new(&args[2]), cell, &args[3])?;
    for line in std::io::stdin().lock().lines() {
        let line = line.map_err(|e| e.to_string())?;
        if line.len() > 32_768 {
            return Err("request limit".into());
        }
        let result = serde_json::from_str::<Request>(&line)
            .map_err(|e| e.to_string())
            .and_then(|r| owner.step(r));
        let response = match result {
            Ok(receipt) => json!({"ok":true,"receipt":receipt}),
            Err(error) => json!({"ok":false,"error":error}),
        };
        println!("{response}");
        std::io::stdout().flush().map_err(|e| e.to_string())?;
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
#[path = "tests.rs"]
mod tests;
