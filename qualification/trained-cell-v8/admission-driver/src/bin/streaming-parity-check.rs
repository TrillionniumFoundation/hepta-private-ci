//! Full-stream engineering comparison; does not publish or read labels.
use codex_hepta_types::Digest32;
use hepta_handoff_recovery_v7::streaming_parity::Inputs;
use hepta_profile_admission_v8::Result;
use serde_json::json;
use std::fs;
use std::io::Write;
use std::path::Path;

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 4 {
        return Err("ROOT PROTOCOL_SHA HOST_HEADER_SHA NEW_RECEIPT".into());
    }
    let inputs = Inputs::load(Path::new(&args[0]))?;
    inputs.verify_family(&args[1])?;
    if inputs.header_digest != args[2].parse::<Digest32>()? {
        return Err("stream header differs from host pin".into());
    }
    let result = json!({"schema":"hepta.full-stream-qualification.v8","header_sha256":inputs.header_digest.to_string(),
        "versions":[inputs.compare_unpublished(0)?,inputs.compare_unpublished(1)?],
        "row_subsampling":false,"owner_opened":false,"candidate_published":false,"production_authority":false});
    let encoded = serde_json::to_vec_pretty(&result)?;
    fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&args[3])?
        .write_all(&encoded)?;
    println!("{}", Digest32::of_bytes(&encoded));
    Ok(())
}
