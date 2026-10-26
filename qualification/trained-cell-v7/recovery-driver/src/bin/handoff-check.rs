//! Development-only exact codec/restore qualification. No scientific admission,
//! owner mutation, selection or production trust is installed by this command.

use codex_hepta_neuron::MAX_TRAINING_HANDOFF_BYTES_V7;
use codex_hepta_neuron::TrainingHandoffBundleV7;
use codex_hepta_types::Digest32;
use std::fs;
use std::io::Write;
use std::path::Path;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 4 {
        return Err(
            "usage: handoff-check INPUT EXPECTED_SHA256 PROTOCOL_SHA256 NEW_RECEIPT".into(),
        );
    }
    let input = Path::new(&args[0]);
    let info = fs::symlink_metadata(input)?;
    if !info.is_file()
        || info.file_type().is_symlink()
        || info.len() > MAX_TRAINING_HANDOFF_BYTES_V7 as u64
    {
        return Err("bounded regular handoff payload required".into());
    }
    let expected: Digest32 = args[1].parse()?;
    let bundle = TrainingHandoffBundleV7::decode(&fs::read(input)?, expected)?;
    if bundle.protocol_digest() != args[2].parse()? {
        return Err("controller protocol differs from caller pin".into());
    }
    let mut result = hepta_handoff_recovery_v7::handoff_dump::dump(&bundle)?;
    result["qualification_scope"] =
        serde_json::json!("development codec/restore only; no scientific candidate acceptance");
    result["candidate_published"] = serde_json::json!(false);
    result["compiled_codec_source_sha256"] = serde_json::json!({
        "types":Digest32::of_bytes(include_bytes!("../../../../../codex-rs/hepta-neuron/src/training_handoff_v7.rs")).to_string(),
        "codec":Digest32::of_bytes(include_bytes!("../../../../../codex-rs/hepta-neuron/src/training_handoff_codec_v7.rs")).to_string(),
        "state":Digest32::of_bytes(include_bytes!("../../../../../codex-rs/hepta-neuron/src/training_handoff_state_v7.rs")).to_string()});
    let mut output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args[3])?;
    output.write_all(&serde_json::to_vec_pretty(&result)?)?;
    output.sync_all()?;
    println!(
        "{}",
        serde_json::json!({"handoff_sha256":bundle.content_digest().to_string(),
        "checkpoints":bundle.checkpoints().len(),"pending_actions":bundle.checkpoints().iter().map(|c|c.pending_actions().len()).collect::<Vec<_>>(),
        "candidate_published":false,"production_activation":false})
    );
    Ok(())
}
