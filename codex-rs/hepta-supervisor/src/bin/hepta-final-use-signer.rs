//! Separately invoked authority-owner utility. Reads an explicit bounded grant
//! proposal on stdin and signs it using an owner-only raw 32-byte seed file.

use std::io::Read;
use std::process::ExitCode;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseGrant;
#[path = "../final_use_signing.rs"]
mod signing;
use signing::OwnerSignatureProfile;

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("hepta-final-use-signer: {error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() < 3 || args[0] != "sign" || args[1] != "--key" {
        return Err(
            "usage: hepta-final-use-signer sign --key OWNER_ONLY_SEED_FILE [--pq-key-id HEX] < grant.json".into(),
        );
    }
    let profile = OwnerSignatureProfile::parse_tail(&args, 3)?;
    let mut proposal = Vec::new();
    std::io::stdin().take(16_385).read_to_end(&mut proposal)?;
    if proposal.len() > 16_384 {
        return Err("grant proposal exceeds 16 KiB".into());
    }
    let grant: FinalUseGrant = serde_json::from_slice(&proposal)?;
    let signing_bytes = grant.signing_bytes()?;
    if grant.schema_version != profile.grant_schema() {
        return Err("grant schema does not match the explicit signature profile".into());
    }
    let signature = profile.sign(&args[2], &signing_bytes)?;
    serde_json::to_writer(std::io::stdout(), &SignedFinalUseGrant { grant, signature })?;
    println!();
    Ok(())
}
