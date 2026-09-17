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
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use zeroize::Zeroizing;

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
    if args.len() != 5
        || args[0] != "approve"
        || args[1] != "--approver-id"
        || args[3] != "--key"
    {
        return Err(
            "usage: hepta-final-use-approver approve --approver-id ID --key OWNER_ONLY_RAW_SEED_FILE < grant.json"
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
    let signing_key = load_private_seed(&args[4])?;
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

#[cfg(unix)]
fn load_private_seed(path: &str) -> Result<SigningKey, Box<dyn std::error::Error>> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err("approval seed must be a regular, singly linked owner-only file".into());
    }
    let mut seed = Zeroizing::new(Vec::new());
    file.by_ref().take(33).read_to_end(&mut seed)?;
    if seed.len() != 32 {
        return Err("approval seed must be exactly 32 raw bytes".into());
    }
    let mut key_bytes = Zeroizing::new([0_u8; 32]);
    key_bytes.copy_from_slice(&seed);
    Ok(SigningKey::from_bytes(&key_bytes))
}

#[cfg(not(unix))]
fn load_private_seed(_path: &str) -> Result<SigningKey, Box<dyn std::error::Error>> {
    Err("final-use approval signing requires an approved platform-specific key-custody backend".into())
}
