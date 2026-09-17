//! Independent operator-approval signer for final-use grants.
//!
//! This binary intentionally owns no grant-issuer key. Production hosts verify
//! its signature independently from the grant issuer, so compromise of one key
//! does not by itself authorize a final-use operation.

use std::io::Read;
use std::path::Path;
use std::process::ExitCode;

use codex_hepta_contracts::FinalUseApproval;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_supervisor::load_signing_key_from_path;
use ed25519_dalek::Signer;

const MAX_GRANT_BYTES: u64 = 16 * 1024;

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("hepta-final-use-approver: {error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 5 || args[0] != "approve" || args[1] != "--approver-id" || args[3] != "--key" {
        return Err(
            "usage: hepta-final-use-approver approve --approver-id ID --key ABSOLUTE_OWNER_ONLY_SEED_FILE < grant.json"
                .into(),
        );
    }
    let approver_id = args[2].clone();
    let mut proposal = Vec::new();
    std::io::stdin()
        .take(MAX_GRANT_BYTES + 1)
        .read_to_end(&mut proposal)?;
    if proposal.len() as u64 > MAX_GRANT_BYTES {
        return Err("grant proposal exceeds 16 KiB".into());
    }
    let grant: FinalUseGrant = serde_json::from_slice(&proposal)?;
    let approval = FinalUseApproval::for_grant(approver_id, &grant)?;
    let signing_key = load_signing_key_from_path(Path::new(&args[4]))?;
    let signature = signing_key
        .sign(&approval.signing_bytes()?)
        .to_bytes()
        .to_vec();
    serde_json::to_writer(
        std::io::stdout(),
        &SignedFinalUseApproval { approval, signature },
    )?;
    println!();
    Ok(())
}
