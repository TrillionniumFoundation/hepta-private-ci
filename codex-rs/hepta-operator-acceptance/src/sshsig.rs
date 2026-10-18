//! Bounded verification of the existing externally pinned raw-Ed25519 profile.
//!
//! The caller validates the principal, policy digest, lifetime and revocation.
//! This module only verifies SSHSIG bytes against that already trusted key.
//! Wire behavior follows OpenSSH's PROTOCOL.sshsig and sshsig_wrap_verify;
//! it does not interpret a signature packet as a trust policy.

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use sha2::Digest as _;
use sha2::Sha256;
use sha2::Sha512;

use crate::AcceptanceError;

pub(crate) const MAX_SIGNATURE_BYTES: usize = 4 * 1024;
const HEADER: &[u8] = b"-----BEGIN SSH SIGNATURE-----\n";
const FOOTER: &[u8] = b"\n-----END SSH SIGNATURE-----\n";

pub(crate) fn verify_ed25519(
    statement: &[u8],
    signature_bytes: &[u8],
    expected_fingerprint: &str,
    expected_namespace: &str,
) -> Result<(), AcceptanceError> {
    if signature_bytes.len() > MAX_SIGNATURE_BYTES {
        return Err(invalid("detached signature exceeds its read bound"));
    }
    let body = signature_bytes
        .strip_prefix(HEADER)
        .and_then(|body| body.strip_suffix(FOOTER))
        .ok_or_else(|| invalid("detached signature is not an OpenSSH SSHSIG envelope"))?;
    let encoded: Vec<u8> = body
        .iter()
        .copied()
        .filter(|byte| !byte.is_ascii_whitespace())
        .collect();
    let blob = STANDARD
        .decode(encoded)
        .map_err(|_| invalid("SSHSIG body is not valid base64"))?;
    let mut remaining = blob
        .strip_prefix(b"SSHSIG")
        .ok_or_else(|| invalid("SSHSIG magic is invalid"))?;
    let version: [u8; 4] = remaining
        .get(..4)
        .ok_or_else(|| invalid("SSHSIG version is truncated"))?
        .try_into()
        .map_err(|_| invalid("SSHSIG version is truncated"))?;
    // Preserve OpenSSH's supported-version check, including legacy version 0.
    if u32::from_be_bytes(version) > 1 {
        return Err(invalid("SSHSIG version is unsupported"));
    }
    remaining = &remaining[4..];
    let key_blob = take_string(&mut remaining)?;
    let namespace = take_string(&mut remaining)?;
    let _reserved = take_string(&mut remaining)?;
    let hash_algorithm = take_string(&mut remaining)?;
    let signature_blob = take_string(&mut remaining)?;
    if !remaining.is_empty() {
        return Err(invalid("SSHSIG contains trailing data"));
    }
    if namespace.is_empty() || namespace.contains(&0) || namespace != expected_namespace.as_bytes()
    {
        return Err(invalid("SSHSIG namespace does not match"));
    }

    let mut key_fields = key_blob;
    let key_algorithm = take_string(&mut key_fields)?;
    let key_bytes: [u8; 32] = take_string(&mut key_fields)?
        .try_into()
        .map_err(|_| invalid("SSHSIG Ed25519 public key must be 32 bytes"))?;
    if key_algorithm != b"ssh-ed25519" || !key_fields.is_empty() {
        return Err(invalid("SSHSIG requires one raw Ed25519 public key"));
    }
    let fingerprint = format!(
        "SHA256:{}",
        STANDARD_NO_PAD.encode(Sha256::digest(key_blob))
    );
    if fingerprint != expected_fingerprint {
        return Err(invalid("SSHSIG key differs from the externally pinned key"));
    }
    let key = VerifyingKey::from_bytes(&key_bytes)
        .map_err(|_| invalid("SSHSIG contains an invalid Ed25519 point"))?;
    if key.is_weak() {
        return Err(invalid("SSHSIG contains a weak Ed25519 key"));
    }

    let mut signature_fields = signature_blob;
    let signature_algorithm = take_string(&mut signature_fields)?;
    let signature = Signature::from_slice(take_string(&mut signature_fields)?)
        .map_err(|_| invalid("SSHSIG Ed25519 signature must be 64 bytes"))?;
    if signature_algorithm != b"ssh-ed25519" || !signature_fields.is_empty() {
        return Err(invalid("SSHSIG Ed25519 signature record is malformed"));
    }
    let digest = match hash_algorithm {
        b"sha256" => Sha256::digest(statement).to_vec(),
        b"sha512" => Sha512::digest(statement).to_vec(),
        _ => return Err(invalid("SSHSIG hash algorithm is unsupported")),
    };
    let mut signed = b"SSHSIG".to_vec();
    append_string(&mut signed, namespace)?;
    // OpenSSH ignores the wire reserved field and verifies an empty reserved
    // string. Preserve that behavior; these bytes never acquire authority.
    append_string(&mut signed, b"")?;
    append_string(&mut signed, hash_algorithm)?;
    append_string(&mut signed, &digest)?;
    key.verify_strict(&signed, &signature)
        .map_err(|_| invalid("OpenSSH SSHSIG verification failed"))
}

fn take_string<'a>(input: &mut &'a [u8]) -> Result<&'a [u8], AcceptanceError> {
    let prefix: [u8; 4] = input
        .get(..4)
        .ok_or_else(|| invalid("truncated SSHSIG string length"))?
        .try_into()
        .map_err(|_| invalid("truncated SSHSIG string length"))?;
    let length = usize::try_from(u32::from_be_bytes(prefix))
        .map_err(|_| invalid("SSHSIG string length overflow"))?;
    let (value, rest) = input[4..]
        .split_at_checked(length)
        .ok_or_else(|| invalid("truncated SSHSIG string value"))?;
    *input = rest;
    Ok(value)
}

fn append_string(output: &mut Vec<u8>, value: &[u8]) -> Result<(), AcceptanceError> {
    let length =
        u32::try_from(value.len()).map_err(|_| invalid("SSHSIG signed field length overflow"))?;
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(value);
    Ok(())
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}

#[cfg(test)]
#[path = "sshsig_tests.rs"]
mod tests;
