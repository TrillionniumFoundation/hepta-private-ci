//! Bounded verification of the pinned raw-Ed25519 SSHSIG policy.
//! Wire format: openssh-portable/PROTOCOL.sshsig. No process, pathname, or
//! mutable environment is consulted to decide signature validity.
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use sha2::Digest as _;

use crate::AcceptanceError;

const MAX_SIGNATURE_BYTES: usize = 4096;

pub(crate) fn verify(
    statement: &[u8],
    envelope: &[u8],
    allowed_signers: &[u8],
    principal: &str,
    namespace: &str,
) -> Result<(), AcceptanceError> {
    if envelope.len() > MAX_SIGNATURE_BYTES || namespace.is_empty() {
        return Err(invalid());
    }
    let armor = envelope
        .strip_prefix(b"-----BEGIN SSH SIGNATURE-----\n")
        .and_then(|body| body.strip_suffix(b"\n-----END SSH SIGNATURE-----\n"))
        .ok_or_else(invalid)?;
    let encoded: Vec<u8> = armor
        .iter()
        .copied()
        .filter(|byte| !byte.is_ascii_whitespace())
        .collect();
    let blob = STANDARD.decode(encoded).map_err(|_| invalid())?;
    let mut packet = blob.strip_prefix(b"SSHSIG").ok_or_else(invalid)?;
    if take_u32(&mut packet)? != 1 {
        return Err(invalid());
    }
    let public_key = take_string(&mut packet)?;
    let actual_namespace = take_string(&mut packet)?;
    let _reserved = take_string(&mut packet)?;
    let hash_algorithm = take_string(&mut packet)?;
    let signature = take_string(&mut packet)?;
    if !packet.is_empty() || actual_namespace != namespace.as_bytes() {
        return Err(invalid());
    }

    // Policies already pin the file digest and fingerprint. Bind this exact
    // principal and raw key again at the cryptographic verification boundary.
    let allowed = std::str::from_utf8(allowed_signers).map_err(|_| invalid())?;
    let lines: Vec<_> = allowed
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect();
    if lines.len() != 1 {
        return Err(invalid());
    }
    let fields: Vec<_> = lines[0].split_ascii_whitespace().collect();
    if fields.len() != 3 || fields[0] != principal || fields[1] != "ssh-ed25519" {
        return Err(invalid());
    }
    let pinned_key = STANDARD.decode(fields[2]).map_err(|_| invalid())?;
    if public_key != pinned_key {
        return Err(invalid());
    }
    let mut key_packet = public_key;
    if take_string(&mut key_packet)? != b"ssh-ed25519" {
        return Err(invalid());
    }
    let key_bytes: [u8; 32] = take_string(&mut key_packet)?
        .try_into()
        .map_err(|_| invalid())?;
    let key = VerifyingKey::from_bytes(&key_bytes).map_err(|_| invalid())?;
    if !key_packet.is_empty() || key.is_weak() {
        return Err(invalid());
    }
    let mut signature_packet = signature;
    if take_string(&mut signature_packet)? != b"ssh-ed25519" {
        return Err(invalid());
    }
    let signature =
        Signature::from_slice(take_string(&mut signature_packet)?).map_err(|_| invalid())?;
    if !signature_packet.is_empty() {
        return Err(invalid());
    }

    let digest = match hash_algorithm {
        b"sha256" => sha2::Sha256::digest(statement).to_vec(),
        b"sha512" => sha2::Sha512::digest(statement).to_vec(),
        _ => return Err(invalid()),
    };
    let mut signed = b"SSHSIG".to_vec();
    put_string(&mut signed, namespace.as_bytes())?;
    // OpenSSH ignores the envelope's reserved field and verifies an empty
    // reserved string (sshsig.c:sshsig_wrap_verify).
    put_string(&mut signed, b"")?;
    put_string(&mut signed, hash_algorithm)?;
    put_string(&mut signed, &digest)?;
    key.verify_strict(&signed, &signature)
        .map_err(|_| invalid())
}

fn take_u32(packet: &mut &[u8]) -> Result<u32, AcceptanceError> {
    let (prefix, remainder) = packet.split_at_checked(4).ok_or_else(invalid)?;
    *packet = remainder;
    Ok(u32::from_be_bytes(
        prefix.try_into().map_err(|_| invalid())?,
    ))
}

fn take_string<'a>(packet: &mut &'a [u8]) -> Result<&'a [u8], AcceptanceError> {
    let length = usize::try_from(take_u32(packet)?).map_err(|_| invalid())?;
    let (value, remainder) = packet.split_at_checked(length).ok_or_else(invalid)?;
    *packet = remainder;
    Ok(value)
}

fn put_string(packet: &mut Vec<u8>, value: &[u8]) -> Result<(), AcceptanceError> {
    let length = u32::try_from(value.len()).map_err(|_| invalid())?;
    packet.extend_from_slice(&length.to_be_bytes());
    packet.extend_from_slice(value);
    Ok(())
}

fn invalid() -> AcceptanceError {
    AcceptanceError::Invalid("OpenSSH SSHSIG verification failed".into())
}

#[cfg(test)]
#[path = "sshsig_tests.rs"]
mod tests;
