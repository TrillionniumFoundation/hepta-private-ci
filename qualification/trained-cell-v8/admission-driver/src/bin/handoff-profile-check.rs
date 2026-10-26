//! Unadmitted, explicit-mode diagnostic only; no owner or scientific signature.
use codex_hepta_types::Digest32;
use hepta_handoff_recovery_v7::handoff_dump;
use hepta_handoff_recovery_v7::handoff_version::Handoff;
use hepta_profile_admission_v8::Result;
use hepta_profile_admission_v8::report;
use std::fs;
use std::io::Write;
use std::path::Path;

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 5 {
        return Err("VERSION INPUT EXPECTED_SHA PROTOCOL_SHA NEW_RECEIPT".into());
    }
    let version: u8 = args[0].parse()?;
    if ![7, 8].contains(&version) {
        return Err("unsupported explicit controller mode".into());
    }
    let bytes = report::read(Path::new(&args[1]))?;
    let bundle = Handoff::decode(&bytes, args[2].parse()?)?;
    if bundle.version() != version || bundle.protocol_digest() != args[3].parse::<Digest32>()? {
        return Err("controller mode or protocol substitution".into());
    }
    let dump = handoff_dump::dump_versioned(&bundle)?;
    let encoded = serde_json::to_vec_pretty(&dump)?;
    fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&args[4])?
        .write_all(&encoded)?;
    println!("{}", Digest32::of_bytes(&encoded));
    Ok(())
}
