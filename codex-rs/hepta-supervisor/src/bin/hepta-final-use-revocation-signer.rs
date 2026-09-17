//! Independent signer for monotonic final-use revocation heads.
//!
//! Transport/fanout is external to this utility. It emits one authenticated
//! retry-safe update; trusted hosts pin the distributor key and hand verified
//! heads to their durable `FinalUseAuthority` owner.

use std::io::Read;
use std::path::Path;
use std::process::ExitCode;

use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_supervisor::load_signing_key_from_path;
use ed25519_dalek::Signer;

const MAX_HEAD_BYTES: u64 = 8 * 1024 * 1024;

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("hepta-final-use-revocation-signer: {error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 5
        || args[0] != "sign"
        || args[1] != "--distributor-id"
        || args[3] != "--key"
    {
        return Err(
            "usage: hepta-final-use-revocation-signer sign --distributor-id ID --key ABSOLUTE_OWNER_ONLY_SEED_FILE < revocations.json"
                .into(),
        );
    }
    let mut bytes = Vec::new();
    std::io::stdin()
        .take(MAX_HEAD_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_HEAD_BYTES {
        return Err("revocation head exceeds 8 MiB".into());
    }
    let head: FinalUseRevocations = serde_json::from_slice(&bytes)?;
    let update = FinalUseRevocationUpdate::new(args[2].clone(), head);
    let signing_key = load_signing_key_from_path(Path::new(&args[4]))?;
    let signature = signing_key
        .sign(&update.signing_bytes()?)
        .to_bytes()
        .to_vec();
    serde_json::to_writer(
        std::io::stdout(),
        &SignedFinalUseRevocationUpdate { update, signature },
    )?;
    println!();
    Ok(())
}
