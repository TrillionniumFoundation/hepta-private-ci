//! Separately invoked authority-owner utility. Reads an explicit bounded grant
//! proposal on stdin and signs it using an owner-only raw 32-byte seed file.

use std::io::Read;
use std::process::ExitCode;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use zeroize::Zeroizing;

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
    if args.len() != 3 || args[0] != "sign" || args[1] != "--key" {
        return Err(
            "usage: hepta-final-use-signer sign --key OWNER_ONLY_SEED_FILE < grant.json".into(),
        );
    }
    let mut proposal = Vec::new();
    std::io::stdin().take(16_385).read_to_end(&mut proposal)?;
    if proposal.len() > 16_384 {
        return Err("grant proposal exceeds 16 KiB".into());
    }
    let grant: FinalUseGrant = serde_json::from_slice(&proposal)?;
    let signing_bytes = grant.signing_bytes()?;
    let mut file = private_key_file(&args[2])?;
    let mut seed = Zeroizing::new(Vec::new());
    file.by_ref().take(33).read_to_end(&mut seed)?;
    if seed.len() != 32 {
        return Err("private seed must be exactly 32 raw bytes".into());
    }
    let mut key_bytes = Zeroizing::new([0_u8; 32]);
    key_bytes.copy_from_slice(&seed);
    let key = SigningKey::from_bytes(&key_bytes);
    let signature = key.sign(&signing_bytes).to_bytes().to_vec();
    serde_json::to_writer(std::io::stdout(), &SignedFinalUseGrant { grant, signature })?;
    println!();
    Ok(())
}

#[cfg(unix)]
fn private_key_file(path: &str) -> Result<std::fs::File, Box<dyn std::error::Error>> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(
            "private seed must be a regular, non-linked owner-only file (mode 0600)".into(),
        );
    }
    Ok(file)
}

#[cfg(not(unix))]
fn private_key_file(_path: &str) -> Result<std::fs::File, Box<dyn std::error::Error>> {
    Err(
        "this signer requires a Unix owner-only file; use an approved issuer on this platform"
            .into(),
    )
}
