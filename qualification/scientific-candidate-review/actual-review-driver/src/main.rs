//! A negative-only qualification against real frozen research evidence.
//! Never installs production trust or activates a research parameter bundle.

mod owner;
mod report;

use codex_hepta_types::Digest32;
use serde_json::json;
use std::fs;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn ensure(condition: bool, message: &str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(message.to_string().into())
    }
}

fn main() -> Result<()> {
    let arguments: Vec<_> = std::env::args_os().skip(1).collect();
    ensure(
        arguments.len() == 6,
        "usage: driver PROTOCOL EVALUATION GATE_INPUT PREDECESSOR CANDIDATE NEW_OUTPUT_DIRECTORY",
    )?;
    let inputs = report::load(
        Path::new(&arguments[0]),
        Path::new(&arguments[1]),
        Path::new(&arguments[2]),
        Path::new(&arguments[3]),
        Path::new(&arguments[4]),
    )?;
    let output = Path::new(&arguments[5]);
    fs::create_dir(output)?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let mut receipt = owner::reject(&inputs, &output.join("owner"), now)?;
    receipt["compiled_source_sha256"] = json!({
        "driver_main":Digest32::of_bytes(include_bytes!("main.rs")).to_string(),
        "driver_report":Digest32::of_bytes(include_bytes!("report.rs")).to_string(),
        "driver_owner":Digest32::of_bytes(include_bytes!("owner.rs")).to_string(),
        "driver_lock":Digest32::of_bytes(include_bytes!("../Cargo.lock")).to_string(),
        "native_candidate_review":Digest32::of_bytes(include_bytes!("../../../../codex-rs/hepta-learning-artifacts/src/candidate_review.rs")).to_string(),
        "native_lib":Digest32::of_bytes(include_bytes!("../../../../codex-rs/hepta-learning-artifacts/src/lib.rs")).to_string(),
    });
    let encoded = serde_json::to_vec_pretty(&receipt)?;
    fs::write(output.join("native-rejection.json"), &encoded)?;
    println!("{}", String::from_utf8(encoded)?);
    Ok(())
}
