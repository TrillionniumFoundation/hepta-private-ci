//! Independent operator-approval signer for final-use grants.
//!
//! This binary intentionally owns no grant-issuer key. Production hosts verify
//! its signature independently from the grant issuer, so compromise of one key
//! does not by itself authorize a final-use operation.

use std::io::Read;
use std::process::ExitCode;

use codex_hepta_contracts::FinalUseApproval;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseApproval;
#[path = "../final_use_signing.rs"]
mod signing;
use signing::OwnerSignatureProfile;

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
    if args.len() < 5 || args[0] != "approve" || args[1] != "--approver-id" || args[3] != "--key" {
        return Err(
            "usage: hepta-final-use-approver approve --approver-id ID --key OWNER_ONLY_RAW_SEED_FILE [--pq-key-id HEX] < grant.json"
                .into(),
        );
    }
    let approver_id = args[2].clone();
    let profile = OwnerSignatureProfile::parse_tail(&args, 5)?;
    let mut proposal = Vec::new();
    std::io::stdin()
        .take(MAX_GRANT_BYTES + 1)
        .read_to_end(&mut proposal)?;
    if proposal.len() as u64 > MAX_GRANT_BYTES {
        return Err("grant proposal exceeds 16 KiB".into());
    }
    let grant: FinalUseGrant = serde_json::from_slice(&proposal)?;
    let approval = FinalUseApproval::for_grant(approver_id, &grant)?;
    if grant.schema_version != profile.grant_schema() {
        return Err("grant schema does not match the explicit signature profile".into());
    }
    let signature = profile.sign(&args[4], &approval.signing_bytes()?)?;
    serde_json::to_writer(
        std::io::stdout(),
        &SignedFinalUseApproval {
            approval,
            signature,
        },
    )?;
    println!();
    Ok(())
}
