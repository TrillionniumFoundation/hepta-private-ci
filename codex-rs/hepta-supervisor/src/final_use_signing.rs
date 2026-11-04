//! Shared bounded key-custody path for the three independently invoked signers.

use std::io::Read;

use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use zeroize::Zeroizing;

pub(super) enum OwnerSignatureProfile {
    Classical,
    MlDsa65 { expected_key_id: [u8; 32] },
}

impl OwnerSignatureProfile {
    pub(super) fn parse_tail(
        args: &[String],
        classical_args: usize,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        if args.len() == classical_args {
            return Ok(Self::Classical);
        }
        if args.len() != classical_args + 2 || args[classical_args] != "--pq-key-id" {
            return Err("optional PQ mode requires --pq-key-id followed by an independently pinned 64-character hex key ID".into());
        }
        let value = args[classical_args + 1].as_bytes();
        if value.len() != 64 || !value.iter().all(u8::is_ascii_hexdigit) {
            return Err("PQ key ID must contain exactly 64 ASCII hexadecimal digits".into());
        }
        let mut expected_key_id = [0; 32];
        for (target, pair) in expected_key_id.iter_mut().zip(value.chunks_exact(2)) {
            *target = u8::from_str_radix(std::str::from_utf8(pair)?, 16)?;
        }
        Ok(Self::MlDsa65 { expected_key_id })
    }

    pub(super) const fn grant_schema(&self) -> u32 {
        match self {
            Self::Classical => 1,
            Self::MlDsa65 { .. } => 2,
        }
    }

    pub(super) fn sign(
        &self,
        path: &str,
        message: &[u8],
    ) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
        let seed = load_private_seed(path)?;
        match self {
            Self::Classical => Ok(SigningKey::from_bytes(&seed)
                .sign(message)
                .to_bytes()
                .to_vec()),
            Self::MlDsa65 { expected_key_id } => {
                let key = PqNativeSigningKey::from_owned_seed(seed, *expected_key_id)?;
                Ok(key.sign_exact_message(message)?.to_vec())
            }
        }
    }
}

#[cfg(unix)]
fn load_private_seed(path: &str) -> Result<Zeroizing<[u8; 32]>, Box<dyn std::error::Error>> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err("private seed must be a regular, singly linked owner-only file".into());
    }
    let mut bytes = Zeroizing::new(Vec::new());
    file.by_ref().take(33).read_to_end(&mut bytes)?;
    if bytes.len() != 32 {
        return Err("private seed must be exactly 32 raw bytes".into());
    }
    let mut seed = Zeroizing::new([0; 32]);
    seed.copy_from_slice(&bytes);
    Ok(seed)
}

#[cfg(not(unix))]
fn load_private_seed(_path: &str) -> Result<Zeroizing<[u8; 32]>, Box<dyn std::error::Error>> {
    Err("this signer requires an approved platform-specific key-custody backend".into())
}
