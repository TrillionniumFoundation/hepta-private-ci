//! Bounded SSHSIG verification for Windows, using the already pinned Ed25519 key.
//! Wire and signed-data formats: openssh-portable/PROTOCOL.sshsig, version 1.

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use sha2::Digest as _;

use crate::AcceptanceError;

const BEGIN: &str = "-----BEGIN SSH SIGNATURE-----\n";
const END: &str = "-----END SSH SIGNATURE-----\n";

pub(crate) fn verify(
    statement: &[u8],
    envelope: &[u8],
    allowed_signers: &[u8],
    principal: &str,
    namespace: &str,
) -> Result<(), AcceptanceError> {
    if envelope.len() > 4 * 1024 || allowed_signers.len() > 64 * 1024 || namespace.is_empty() {
        return Err(invalid(
            "SSHSIG input exceeds its bound or has an empty namespace",
        ));
    }
    let text =
        std::str::from_utf8(envelope).map_err(|_| invalid("SSHSIG envelope is not UTF-8"))?;
    let body = text
        .strip_prefix(BEGIN)
        .and_then(|value| value.strip_suffix(END))
        .ok_or_else(|| invalid("invalid SSHSIG envelope"))?
        .replace('\n', "");
    let wire = decode_base64(&body)?;
    let wire = wire
        .strip_prefix(b"SSHSIG\0\0\0\x01")
        .ok_or_else(|| invalid("unsupported SSHSIG magic or version"))?;
    let (public_key, wire) = take_string(wire)?;
    let (signed_namespace, wire) = take_string(wire)?;
    let (_reserved, wire) = take_string(wire)?;
    let (hash_algorithm, wire) = take_string(wire)?;
    let (signature, trailing) = take_string(wire)?;
    if !trailing.is_empty() || signed_namespace != namespace.as_bytes() {
        return Err(invalid("SSHSIG namespace or trailing data differs"));
    }

    let allowed_text = std::str::from_utf8(allowed_signers)
        .map_err(|_| invalid("allowed_signers is not UTF-8"))?;
    let mut lines = allowed_text.lines();
    let line = lines
        .next()
        .ok_or_else(|| invalid("allowed_signers is empty"))?;
    let fields = line.split_ascii_whitespace().collect::<Vec<_>>();
    if !allowed_text.ends_with('\n')
        || allowed_text.contains('\r')
        || lines.next().is_some()
        || fields.len() != 3
        || fields[0] != principal
        || fields[1] != "ssh-ed25519"
    {
        return Err(invalid(
            "SSHSIG requires the exact single pinned Ed25519 principal",
        ));
    }
    let pinned_key = decode_base64(fields[2])?;
    if pinned_key != public_key {
        return Err(invalid("SSHSIG key differs from the pinned signer"));
    }
    let (key_algorithm, key_wire) = take_string(public_key)?;
    let (key_bytes, key_trailing) = take_string(key_wire)?;
    let key_bytes: [u8; 32] = key_bytes
        .try_into()
        .map_err(|_| invalid("SSHSIG Ed25519 key has an invalid length"))?;
    let key = VerifyingKey::from_bytes(&key_bytes)
        .map_err(|_| invalid("SSHSIG Ed25519 key is invalid"))?;
    if key_algorithm != b"ssh-ed25519" || !key_trailing.is_empty() || key.is_weak() {
        return Err(invalid("SSHSIG Ed25519 key is malformed or weak"));
    }
    let (signature_algorithm, signature_wire) = take_string(signature)?;
    let (signature_bytes, signature_trailing) = take_string(signature_wire)?;
    if signature_algorithm != b"ssh-ed25519" || !signature_trailing.is_empty() {
        return Err(invalid(
            "SSHSIG signature algorithm or trailing data differs",
        ));
    }
    let signature = Signature::from_slice(signature_bytes)
        .map_err(|_| invalid("SSHSIG Ed25519 signature has an invalid length"))?;
    let digest = match hash_algorithm {
        b"sha256" => sha2::Sha256::digest(statement).to_vec(),
        b"sha512" => sha2::Sha512::digest(statement).to_vec(),
        _ => return Err(invalid("unsupported SSHSIG message hash")),
    };
    let mut signed = b"SSHSIG".to_vec();
    // OpenSSH ignores the wire reserved field and signs an empty reserved
    // string. Preserve that verifier behavior even for a nonempty wire field.
    for field in [
        signed_namespace,
        b"".as_slice(),
        hash_algorithm,
        digest.as_slice(),
    ] {
        let length =
            u32::try_from(field.len()).map_err(|_| invalid("SSHSIG signed field is too long"))?;
        signed.extend_from_slice(&length.to_be_bytes());
        signed.extend_from_slice(field);
    }
    key.verify_strict(&signed, &signature)
        .map_err(|_| invalid("Ed25519 SSHSIG verification failed"))
}

fn decode_base64(value: &str) -> Result<Vec<u8>, AcceptanceError> {
    let bytes = STANDARD
        .decode(value)
        .map_err(|_| invalid("SSHSIG base64 is malformed"))?;
    if STANDARD.encode(&bytes) != value {
        return Err(invalid("SSHSIG base64 is not canonical"));
    }
    Ok(bytes)
}

fn take_string(wire: &[u8]) -> Result<(&[u8], &[u8]), AcceptanceError> {
    let length: [u8; 4] = wire
        .get(..4)
        .ok_or_else(|| invalid("truncated SSHSIG string length"))?
        .try_into()
        .map_err(|_| invalid("truncated SSHSIG string length"))?;
    let length = usize::try_from(u32::from_be_bytes(length))
        .map_err(|_| invalid("SSHSIG length overflows"))?;
    let end = 4_usize
        .checked_add(length)
        .ok_or_else(|| invalid("SSHSIG length overflows"))?;
    let value = wire
        .get(4..end)
        .ok_or_else(|| invalid("truncated SSHSIG string value"))?;
    Ok((value, &wire[end..]))
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}

#[cfg(test)]
#[path = "sshsig_tests.rs"]
mod tests;
