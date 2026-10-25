//! Frozen-profile native research gate. Positive admission requires an external
//! signature from the research reviewer pinned before fresh evaluation.

mod census;
mod owner;
#[path = "../../driver/src/parity.rs"]
mod parity;
mod payload;
mod positive;
mod positive_owner;
mod report;
mod serve;

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::TrainedCellBundleV5;
use codex_hepta_neuron::TrainedCellErrorV5;
use codex_hepta_neuron::TrainedCellInputBindingV5;
use codex_hepta_neuron::trained_cell_compatibility_digest_v5;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use owner::id;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeMap;
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
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    let mode = args
        .first()
        .and_then(|s| s.to_str())
        .ok_or("mode required: reject, prepare or execute")?;
    if mode == "parity" {
        ensure(
            args.len() == 4,
            "usage: parity PROTOCOL CONVERSION_DIRECTORY NEW_RECEIPT_FILE",
        )?;
        let protocol = Digest32::of_bytes(&report::read(Path::new(&args[1]))?);
        report::accepted_profile(protocol)?;
        let root = Path::new(&args[2]);
        let inputs = parity::Inputs::load(root)?;
        inputs.verify_family(&protocol.to_string(), report::TASKS)?;
        let receipt = json!({"schema":"hepta.actual-typed-native-parity.v5","protocol_sha256":protocol.to_string(),
            "conversion_manifest_sha256":Digest32::of_bytes(&report::read(&root.join("manifest.json"))?).to_string(),
            "parity":[parity::compare_unpublished(&inputs,0)?,parity::compare_unpublished(&inputs,1)?],
            "heldout_labels_read":false,"candidate_published":false,"scientific_acceptance":false,"production_authority":false,
            "compiled_native_source_sha256":Digest32::of_bytes(include_bytes!("../../../../codex-rs/hepta-neuron/src/trained_cell_v5.rs")).to_string(),
            "compiled_parity_source_sha256":Digest32::of_bytes(include_bytes!("../../driver/src/parity.rs")).to_string()});
        let bytes = serde_json::to_vec_pretty(&receipt)?;
        let mut file = fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(Path::new(&args[3]))?;
        std::io::Write::write_all(&mut file, &bytes)?;
        println!("{}", String::from_utf8(bytes)?);
        return Ok(());
    }
    let expected = match mode {
        "reject" => 8,
        "prepare" => 10,
        "execute" => 11,
        _ => return Err("unknown mode".into()),
    };
    ensure(
        args.len() == expected,
        "usage: MODE PROTOCOL EVALUATION GATE_INPUT PREDECESSOR CANDIDATE CONVERSION_MANIFEST [REPLAY_AUDIT STATISTICS_AUDIT] OUTPUT_DIRECTORY [SIGNATURE_JSON]",
    )?;
    let inputs = report::load(
        Path::new(&args[1]),
        Path::new(&args[2]),
        Path::new(&args[3]),
        Path::new(&args[4]),
        Path::new(&args[5]),
        Path::new(&args[6]),
    )?;
    let output = Path::new(&args[if mode == "reject" { 7 } else { 9 }]);
    let mut receipt = if mode == "reject" {
        fs::create_dir(output)?;
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        owner::reject(&inputs, &output.join("owner"), now)?
    } else {
        let protocol: Value = serde_json::from_slice(&report::read(Path::new(&args[1]))?)?;
        let gate: Value = serde_json::from_slice(&report::read(Path::new(&args[3]))?)?;
        let conversion = Path::new(&args[6]);
        positive::run(
            mode,
            &protocol,
            &inputs,
            &gate,
            [
                Path::new(&args[7]),
                Path::new(&args[8]),
                conversion,
                conversion.parent().ok_or("conversion directory missing")?,
            ],
            output,
            if mode == "execute" {
                Some(Path::new(&args[10]))
            } else {
                None
            },
        )?
    };
    receipt["compiled_source_sha256"] = json!({
        "main":Digest32::of_bytes(include_bytes!("main.rs")).to_string(),
        "report":Digest32::of_bytes(include_bytes!("report.rs")).to_string(),
        "census":Digest32::of_bytes(include_bytes!("census.rs")).to_string(),
        "payload":Digest32::of_bytes(include_bytes!("payload.rs")).to_string(),
        "owner":Digest32::of_bytes(include_bytes!("owner.rs")).to_string(),
        "positive":Digest32::of_bytes(include_bytes!("positive.rs")).to_string(),
        "positive_owner":Digest32::of_bytes(include_bytes!("positive_owner.rs")).to_string(),
        "serve":Digest32::of_bytes(include_bytes!("serve.rs")).to_string(),
        "parity":Digest32::of_bytes(include_bytes!("../../driver/src/parity.rs")).to_string(),
        "native_candidate_review":Digest32::of_bytes(include_bytes!("../../../../codex-rs/hepta-learning-artifacts/src/candidate_review.rs")).to_string(),
        "native_typed_owner":Digest32::of_bytes(include_bytes!("../../../../codex-rs/hepta-learning-artifacts/src/typed_candidate_owner_v5.rs")).to_string(),
        "native_trained_cell":Digest32::of_bytes(include_bytes!("../../../../codex-rs/hepta-neuron/src/trained_cell_v5.rs")).to_string()
    });
    let encoded = serde_json::to_vec_pretty(&receipt)?;
    fs::write(
        output.join(if mode == "reject" {
            "native-rejection.json"
        } else {
            "driver-status.json"
        }),
        &encoded,
    )?;
    println!("{}", String::from_utf8(encoded)?);
    Ok(())
}
