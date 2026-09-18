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
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use zeroize::Zeroizing;

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
    if args.len() != 9
        || args[0] != "sign"
        || args[1] != "--distributor-id"
        || args[3] != "--key"
        || args[5] != "--issued-at-unix-ms"
        || args[7] != "--expires-at-unix-ms"
    {
        return Err(
            "usage: hepta-final-use-revocation-signer sign --distributor-id ID --key OWNER_ONLY_RAW_SEED_FILE --issued-at-unix-ms N --expires-at-unix-ms N < revocations.json"
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
    let issued_at_unix_ms: u64 = args[6].parse()?;
    let expires_at_unix_ms: u64 = args[8].parse()?;
    let update =
        FinalUseRevocationUpdate::new(args[2].clone(), head, issued_at_unix_ms, expires_at_unix_ms);
    let signing_key = load_private_seed(&args[4])?;
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
        return Err("revocation seed must be a regular, singly linked owner-only file".into());
    }
    let mut seed = Zeroizing::new(Vec::new());
    file.by_ref().take(33).read_to_end(&mut seed)?;
    if seed.len() != 32 {
        return Err("revocation seed must be exactly 32 raw bytes".into());
    }
    let mut key_bytes = Zeroizing::new([0_u8; 32]);
    key_bytes.copy_from_slice(&seed);
    Ok(SigningKey::from_bytes(&key_bytes))
}

#[cfg(not(unix))]
fn load_private_seed(_path: &str) -> Result<SigningKey, Box<dyn std::error::Error>> {
    Err("revocation signing requires an approved platform-specific key-custody backend".into())
}
