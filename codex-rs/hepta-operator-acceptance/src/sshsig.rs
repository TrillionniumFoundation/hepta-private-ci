//! Captured-byte Ed25519 SSHSIG verification for the Windows consumer.
//!
//! The framing follows OpenSSH PROTOCOL.sshsig and sshsig_wrap_verify at
//! openssh/openssh-portable ea8b8989cc7a6a27b2ce1797fc6be1988280c036.
//! The existing policy owns the principal, allowed-signer fingerprint, namespace,
//! envelope and byte budget. No pathname or subprocess can replace these bytes.

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use sha2::Digest as _;

use crate::AcceptanceError;

const HEADER: &[u8] = b"-----BEGIN SSH SIGNATURE-----\n";
const FOOTER: &[u8] = b"-----END SSH SIGNATURE-----\n";
const MAX_SIGNATURE_BYTES: usize = 4 * 1024;

pub(crate) fn verify_captured(
    statement: &[u8],
    signature: &[u8],
    namespace: &str,
    fingerprint: &str,
) -> Result<(), AcceptanceError> {
    if signature.len() > MAX_SIGNATURE_BYTES
        || !signature.starts_with(HEADER)
        || !signature.ends_with(FOOTER)
        || namespace.is_empty()
        || namespace.contains('\0')
    {
        return Err(invalid("SSHSIG envelope, namespace or byte bound differs"));
    }
    let body = &signature[HEADER.len()..];
    // OpenSSH consumes the first newline-prefixed footer. The caller's
    // original whole-envelope check above still requires the final footer.
    let footer = b"\n-----END SSH SIGNATURE-----";
    let end = body
        .windows(footer.len())
        .position(|part| part == footer)
        .ok_or_else(|| invalid("SSHSIG footer is missing"))?;
    let encoded = body[..end]
        .iter()
        .copied()
        .filter(|byte| !byte.is_ascii_whitespace())
        .collect::<Vec<_>>();
    let blob = STANDARD
        .decode(encoded)
        .map_err(|_| invalid("SSHSIG body is not base64"))?;
    let mut input = Reader::new(&blob);
    if input.take(6)? != b"SSHSIG" || input.u32()? > 1 {
        return Err(invalid("SSHSIG magic or version differs"));
    }
    let public_key = input.string()?;
    let actual_namespace = input.cstring()?;
    let _reserved = input.string()?;
    let hash_algorithm = input.cstring()?;
    let encoded_signature = input.string()?;
    input.finish()?;
    if actual_namespace != namespace.as_bytes() {
        return Err(invalid(
            "SSHSIG namespace differs from the pinned namespace",
        ));
    }

    let mut key = Reader::new(public_key);
    if key.cstring()? != b"ssh-ed25519" {
        return Err(invalid("SSHSIG public key is not raw Ed25519"));
    }
    let public_bytes: [u8; 32] = key
        .string()?
        .try_into()
        .map_err(|_| invalid("SSHSIG Ed25519 public key must be 32 bytes"))?;
    key.finish()?;
    // OpenSSH fingerprints the parsed key's canonical serialization. Its
    // CString reader permits one terminal NUL in an algorithm field; that
    // spelling does not change the underlying pinned Ed25519 key.
    let mut canonical_key = Vec::new();
    put_string(&mut canonical_key, b"ssh-ed25519")?;
    put_string(&mut canonical_key, &public_bytes)?;
    let actual_fingerprint = format!(
        "SHA256:{}",
        STANDARD_NO_PAD.encode(sha2::Sha256::digest(&canonical_key))
    );
    if actual_fingerprint != fingerprint {
        return Err(invalid("SSHSIG public key differs from the pinned signer"));
    }
    let verifying_key = VerifyingKey::from_bytes(&public_bytes)
        .map_err(|_| invalid("SSHSIG Ed25519 public key is malformed"))?;
    if verifying_key.is_weak() {
        return Err(invalid("SSHSIG Ed25519 public key is weak"));
    }

    let mut encoded = Reader::new(encoded_signature);
    if encoded.cstring()? != b"ssh-ed25519" {
        return Err(invalid("SSHSIG signature algorithm is not Ed25519"));
    }
    let signature_bytes: [u8; 64] = encoded
        .string()?
        .try_into()
        .map_err(|_| invalid("SSHSIG Ed25519 signature must be 64 bytes"))?;
    encoded.finish()?;
    let digest = match hash_algorithm {
        b"sha256" => sha2::Sha256::digest(statement).to_vec(),
        b"sha512" => sha2::Sha512::digest(statement).to_vec(),
        _ => return Err(invalid("SSHSIG hash algorithm is unsupported")),
    };
    let mut signed = b"SSHSIG".to_vec();
    put_string(&mut signed, namespace.as_bytes())?;
    // OpenSSH ignores the outer reserved field and verifies an empty reserved
    // field in the signed payload. Preserve that behavior, including version 0.
    put_string(&mut signed, b"")?;
    put_string(&mut signed, hash_algorithm)?;
    put_string(&mut signed, &digest)?;
    verifying_key
        .verify_strict(&signed, &Signature::from_bytes(&signature_bytes))
        .map_err(|_| invalid("SSHSIG Ed25519 verification failed"))
}

struct Reader<'a> {
    remaining: &'a [u8],
}

impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { remaining: bytes }
    }

    fn take(&mut self, count: usize) -> Result<&'a [u8], AcceptanceError> {
        let (value, remaining) = self
            .remaining
            .split_at_checked(count)
            .ok_or_else(|| invalid("SSHSIG field is truncated"))?;
        self.remaining = remaining;
        Ok(value)
    }

    fn u32(&mut self) -> Result<u32, AcceptanceError> {
        let bytes = self
            .take(4)?
            .try_into()
            .map_err(|_| invalid("SSHSIG integer is truncated"))?;
        Ok(u32::from_be_bytes(bytes))
    }

    fn string(&mut self) -> Result<&'a [u8], AcceptanceError> {
        let count =
            usize::try_from(self.u32()?).map_err(|_| invalid("SSHSIG field length overflows"))?;
        self.take(count)
    }

    fn cstring(&mut self) -> Result<&'a [u8], AcceptanceError> {
        let value = self.string()?;
        let text = value.strip_suffix(&[0]).unwrap_or(value);
        if text.contains(&0) {
            return Err(invalid("SSHSIG text field contains an embedded NUL"));
        }
        Ok(text)
    }

    fn finish(self) -> Result<(), AcceptanceError> {
        if self.remaining.is_empty() {
            Ok(())
        } else {
            Err(invalid("SSHSIG object contains trailing bytes"))
        }
    }
}

fn put_string(out: &mut Vec<u8>, value: &[u8]) -> Result<(), AcceptanceError> {
    let length =
        u32::try_from(value.len()).map_err(|_| invalid("SSHSIG output length overflows"))?;
    out.extend_from_slice(&length.to_be_bytes());
    out.extend_from_slice(value);
    Ok(())
}

fn invalid(message: &'static str) -> AcceptanceError {
    AcceptanceError::Invalid(message.to_string())
}

#[cfg(test)]
#[path = "sshsig_tests.rs"]
mod tests;
