//! Unadmitted actual-grid handoff and serving parity. No owner writes or science.

use codex_hepta_neuron::MAX_TRAINING_HANDOFF_BYTES_V7;
use codex_hepta_neuron::TrainingHandoffBundleV7;
use codex_hepta_types::Digest32;
use hepta_handoff_recovery_v7::handoff_dump;
use hepta_handoff_recovery_v7::parity;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeSet;
use std::fs;
use std::io::Write;
use std::path::Path;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn read(path: &Path, limit: u64) -> Result<Vec<u8>> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > limit {
        return Err("bounded regular diagnostic input required".into());
    }
    Ok(fs::read(path)?)
}

fn ensure(value: bool, message: &str) -> Result<()> {
    if value { Ok(()) } else { Err(message.into()) }
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    ensure(
        args.len() == 5,
        "usage: handoff-grid-check INPUT EXPECTED_SHA PROTOCOL_SHA PARITY_DIRECTORY NEW_RECEIPT",
    )?;
    let bytes = read(Path::new(&args[0]), MAX_TRAINING_HANDOFF_BYTES_V7 as u64)?;
    let bundle = TrainingHandoffBundleV7::decode(&bytes, args[1].parse()?)?;
    ensure(
        bundle.protocol_digest() == args[2].parse()?,
        "controller protocol differs",
    )?;
    let root = Path::new(&args[3]);
    let manifest_bytes = read(&root.join("manifest.json"), 1_048_576)?;
    let manifest: Value = serde_json::from_slice(&manifest_bytes)?;
    ensure(
        manifest["schema"] == "hepta.handoff-serving-diagnostic.v7"
            && manifest["authority"] == "DENY_ALL"
            && manifest["scientific_acceptance"] == false
            && manifest["production_authority"] == false
            && parity::hash(&manifest["handoff_sha256"])? == bundle.content_digest()
            && parity::hash(&manifest["protocol_sha256"])? == bundle.protocol_digest(),
        "diagnostic scope or handoff identity differs",
    )?;
    let vectors = read(&root.join("vectors.bin"), 128 * 1024 * 1024)?;
    let expected = read(&root.join("expected.bin"), 128 * 1024 * 1024)?;
    ensure(
        Digest32::of_bytes(&vectors) == parity::hash(&manifest["vectors_sha256"])?
            && Digest32::of_bytes(&expected) == parity::hash(&manifest["expected_sha256"])?
            && manifest["absolute_tolerance"].as_f64() == Some(1e-12),
        "reference bytes differ",
    )?;
    let tasks = manifest["tasks"].as_array().ok_or("task census missing")?;
    ensure(tasks.len() == 2, "two source tasks required")?;
    let mut offset = 0;
    let mut seen_tasks = BTreeSet::new();
    for task in tasks {
        let rows = parity::count(&task["rows"])?;
        ensure(
            seen_tasks.insert(parity::label(&task["task"])?)
                && rows > 0
                && rows <= 16384
                && parity::count(&task["offset_bytes"])? == offset,
            "raw vector census differs",
        )?;
        offset += rows * 384 * 8;
    }
    ensure(offset == vectors.len(), "raw vector coverage differs")?;
    let version = &manifest["versions"][0];
    let binding = bundle.serving().input_binding();
    ensure(
        manifest["versions"].as_array().map(Vec::len) == Some(1)
            && parity::hash(&version["payload_sha256"])? == bundle.serving().content_digest()
            && version["generation"] == bundle.generation().get()
            && parity::hash(&version["encoder_sha256"])? == binding.encoder_digest
            && parity::hash(&version["projection_sha256"])? == binding.projection_digest
            && parity::hash(&version["normalization_sha256"])? == binding.normalization_digest,
        "serving identity differs from pinned envelope bytes",
    )?;
    let cases = version["cases"].as_array().ok_or("case census missing")?;
    ensure(
        cases.len() == bundle.checkpoints().len(),
        "checkpoint parity coverage differs",
    )?;
    let mut cells = BTreeSet::new();
    offset = 0;
    for case in cases {
        let id = parity::label(&case["cell_id"])?;
        let checkpoint = bundle
            .checkpoints()
            .iter()
            .find(|c| c.cell_id().as_str() == id)
            .ok_or("unexpected parity cell")?;
        let state: Value = serde_json::from_slice(checkpoint.state_metadata_json())?;
        let task = tasks
            .iter()
            .find(|t| t["task"] == case["task"])
            .ok_or("unknown task")?;
        ensure(
            cells.insert(id)
                && state["bindings"]["task"] == case["task"]
                && case["rows"] == task["rows"]
                && parity::count(&case["offset_bytes"])? == offset,
            "parity case identity or coverage differs",
        )?;
        offset += parity::count(&case["rows"])? * 8 * 8;
    }
    ensure(
        offset == expected.len(),
        "reference prediction coverage differs",
    )?;
    let payload = bundle.serving().encode();
    let inputs = parity::Inputs {
        manifest,
        vectors,
        expected,
        payloads: [payload.clone(), payload],
    };
    let mut checked = parity::compare_unpublished(&inputs, 0)?;
    checked["all_heads"] = json!(bundle.checkpoints().len());
    let mut result = handoff_dump::dump(&bundle)?;
    result["serving_parity"] = checked;
    result["parity_manifest_sha256"] = json!(Digest32::of_bytes(&manifest_bytes).to_string());
    result["scope"] =
        json!("unadmitted sealed development-grid diagnostic; no scientific approval");
    result["candidate_published"] = json!(false);
    result["production_authority"] = json!(false);
    result["compiled_codec_source_sha256"] = json!({
        "types":Digest32::of_bytes(include_bytes!("../../../../../codex-rs/hepta-neuron/src/training_handoff_v7.rs")).to_string(),
        "codec":Digest32::of_bytes(include_bytes!("../../../../../codex-rs/hepta-neuron/src/training_handoff_codec_v7.rs")).to_string(),
        "state":Digest32::of_bytes(include_bytes!("../../../../../codex-rs/hepta-neuron/src/training_handoff_state_v7.rs")).to_string()});
    let mut output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args[4])?;
    output.write_all(&serde_json::to_vec_pretty(&result)?)?;
    output.sync_all()?;
    println!(
        "{}",
        json!({"handoff_sha256":bundle.content_digest().to_string(),
        "heads":bundle.checkpoints().len(),"serving_parity":result["serving_parity"],
        "candidate_published":false,"production_activation":false})
    );
    Ok(())
}
