//! Independent signer for monotonic final-use revocation heads.
//!
//! Transport/fanout is external to this utility. It emits one authenticated
//! retry-safe update; trusted hosts pin the distributor key and hand verified
//! heads to their durable `FinalUseAuthority` owner.

use std::io::Read;
use std::process::ExitCode;

use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
#[path = "../final_use_signing.rs"]
mod signing;
use signing::OwnerSignatureProfile;

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
    if args.len() < 9
        || args[0] != "sign"
        || args[1] != "--distributor-id"
        || args[3] != "--key"
        || args[5] != "--issued-at-unix-ms"
        || args[7] != "--expires-at-unix-ms"
    {
        return Err(
            "usage: hepta-final-use-revocation-signer sign --distributor-id ID --key OWNER_ONLY_RAW_SEED_FILE --issued-at-unix-ms N --expires-at-unix-ms N [--pq-key-id HEX] < revocations.json"
                .into(),
        );
    }
    let profile = OwnerSignatureProfile::parse_tail(&args, 9)?;
    let mut bytes = Vec::new();
    std::io::stdin()
        .take(MAX_HEAD_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_HEAD_BYTES {
        return Err("revocation head exceeds 8 MiB".into());
    }
    let head: FinalUseRevocations = serde_json::from_slice(&bytes)?;
    let issued_at_unix_ms: u64 = args[6].parse()?;
    let expires_at_unix_ms: u64 = args[8].parse()?;
    let update = match profile.grant_schema() {
        1 => FinalUseRevocationUpdate::new(
            args[2].clone(),
            head,
            issued_at_unix_ms,
            expires_at_unix_ms,
        ),
        2 => FinalUseRevocationUpdate::new_pq(
            args[2].clone(),
            head,
            issued_at_unix_ms,
            expires_at_unix_ms,
        ),
        _ => return Err("unsupported signature profile".into()),
    };
    let signature = profile.sign(&args[4], &update.signing_bytes()?)?;
    serde_json::to_writer(
        std::io::stdout(),
        &SignedFinalUseRevocationUpdate { update, signature },
    )?;
    println!();
    Ok(())
}
