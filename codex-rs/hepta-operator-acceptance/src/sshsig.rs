//! Bounded verification of the single raw Ed25519 SSHSIG profile pinned by
//! both trust policies. No agent, key lookup, certificates, or signer options.
//!
//! Wire and signed-data layouts follow OpenSSH PROTOCOL.sshsig version 1:
//! https://github.com/openssh/openssh-portable/blob/master/PROTOCOL.sshsig

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use sha2::Digest as _;

use crate::AcceptanceError;
use crate::durable::MAX_SMALL_FILE_BYTES;

const MAGIC: &[u8] = b"SSHSIG";
const BEGIN: &[u8] = b"-----BEGIN SSH SIGNATURE-----\n";
const END: &[u8] = b"-----END SSH SIGNATURE-----\n";
const MAX_SIGNATURE_BYTES: usize = 4 * 1024;
const MAX_ALLOWED_SIGNERS_BYTES: usize = 64 * 1024;

pub(crate) fn verify(
    statement: &[u8],
    signature_bytes: &[u8],
    allowed_signers_bytes: &[u8],
    principal: &str,
    namespace: &str,
) -> Result<(), AcceptanceError> {
    if statement.len() > MAX_SMALL_FILE_BYTES || namespace.is_empty() {
        return Err(invalid("SSHSIG statement bound or namespace is invalid"));
    }
    let pinned_key = allowed_key(allowed_signers_bytes, principal)?;
    let blob = decode_armor(signature_bytes)?;
    let mut fields = Reader::new(&blob);
    if fields.take(MAGIC.len())? != MAGIC || fields.u32()? != 1 {
        return Err(invalid("unsupported SSHSIG preamble or version"));
    }
    let public_key = fields.string()?;
    let signed_namespace = fields.string()?;
    let reserved = fields.string()?;
    let hash_algorithm = fields.string()?;
    let signature_blob = fields.string()?;
    fields.finish()?;
    // Check domain and the exact policy-pinned key before any signature work.
    if public_key != pinned_key || signed_namespace != namespace.as_bytes() {
        return Err(invalid("SSHSIG namespace or pinned public key mismatch"));
    }
    let verifying_key = ed25519_key(public_key)?;
    let mut signature_fields = Reader::new(signature_blob);
    if signature_fields.string()? != b"ssh-ed25519" {
        return Err(invalid("SSHSIG signature algorithm is not raw Ed25519"));
    }
    let signature = Signature::from_slice(signature_fields.string()?)
        .map_err(|_| invalid("SSHSIG Ed25519 signature must be 64 bytes"))?;
    signature_fields.finish()?;

    let digest = match hash_algorithm {
        b"sha256" => sha2::Sha256::digest(statement).to_vec(),
        b"sha512" => sha2::Sha512::digest(statement).to_vec(),
        _ => return Err(invalid("unsupported SSHSIG hash algorithm")),
    };
    let mut signed_data = MAGIC.to_vec();
    // Reserved bytes have no local policy meaning but remain authenticated.
    for value in [
        signed_namespace,
        reserved,
        hash_algorithm,
        digest.as_slice(),
    ] {
        let length = u32::try_from(value.len())
            .map_err(|_| invalid("SSHSIG signed field length overflow"))?;
        signed_data.extend_from_slice(&length.to_be_bytes());
        signed_data.extend_from_slice(value);
    }
    verifying_key
        .verify_strict(&signed_data, &signature)
        .map_err(|_| invalid("OpenSSH SSHSIG verification failed"))
}

fn allowed_key(bytes: &[u8], principal: &str) -> Result<Vec<u8>, AcceptanceError> {
    if bytes.len() > MAX_ALLOWED_SIGNERS_BYTES
        || principal.is_empty()
        || principal.len() > 128
        || !principal.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'@' | b'-')
        })
    {
        return Err(invalid("SSHSIG signer bound or principal is invalid"));
    }
    let text =
        std::str::from_utf8(bytes).map_err(|_| invalid("SSHSIG allowed_signers is not UTF-8"))?;
    if !text.ends_with('\n') || text.contains('\r') {
        return Err(invalid("SSHSIG allowed_signers must use LF line endings"));
    }
    let mut lines = text.lines();
    let line = lines
        .next()
        .ok_or_else(|| invalid("missing SSHSIG signer"))?;
    if lines.next().is_some() {
        return Err(invalid("SSHSIG requires exactly one pinned signer"));
    }
    let mut fields = line.split_ascii_whitespace();
    if fields.next() != Some(principal) || fields.next() != Some("ssh-ed25519") {
        return Err(invalid(
            "SSHSIG requires one exact principal and raw Ed25519 key",
        ));
    }
    let encoded = fields
        .next()
        .ok_or_else(|| invalid("missing SSHSIG public key"))?;
    if fields.next().is_some() {
        return Err(invalid(
            "SSHSIG signer options and comments are not permitted",
        ));
    }
    let blob = STANDARD
        .decode(encoded)
        .map_err(|_| invalid("invalid SSHSIG allowed_signers base64"))?;
    if STANDARD.encode(&blob) != encoded {
        return Err(invalid("noncanonical SSHSIG allowed_signers base64"));
    }
    ed25519_key(&blob)?;
    Ok(blob)
}

fn ed25519_key(blob: &[u8]) -> Result<VerifyingKey, AcceptanceError> {
    let mut fields = Reader::new(blob);
    if fields.string()? != b"ssh-ed25519" {
        return Err(invalid("SSHSIG public key is not raw Ed25519"));
    }
    let key: &[u8; 32] = fields
        .string()?
        .try_into()
        .map_err(|_| invalid("SSHSIG Ed25519 public key must be 32 bytes"))?;
    fields.finish()?;
    let key =
        VerifyingKey::from_bytes(key).map_err(|_| invalid("invalid SSHSIG Ed25519 public key"))?;
    if key.is_weak() {
        return Err(invalid("weak SSHSIG Ed25519 public key"));
    }
    Ok(key)
}

fn decode_armor(bytes: &[u8]) -> Result<Vec<u8>, AcceptanceError> {
    if bytes.len() > MAX_SIGNATURE_BYTES {
        return Err(invalid("SSHSIG signature exceeds its read bound"));
    }
    let body = bytes
        .strip_prefix(BEGIN)
        .and_then(|body| body.strip_suffix(END))
        .ok_or_else(|| invalid("invalid OpenSSH SSHSIG envelope"))?;
    if !body.ends_with(b"\n") {
        return Err(invalid("SSHSIG footer must begin on a new line"));
    }
    let encoded = body
        .iter()
        .copied()
        .filter(|byte| *byte != b'\n')
        .collect::<Vec<_>>();
    let blob = STANDARD
        .decode(&encoded)
        .map_err(|_| invalid("invalid OpenSSH SSHSIG base64"))?;
    if STANDARD.encode(&blob).as_bytes() != encoded {
        return Err(invalid("noncanonical OpenSSH SSHSIG base64"));
    }
    Ok(blob)
}

struct Reader<'a> {
    rest: &'a [u8],
}

impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { rest: bytes }
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8], AcceptanceError> {
        let (value, rest) = self
            .rest
            .split_at_checked(length)
            .ok_or_else(|| invalid("truncated SSHSIG field"))?;
        self.rest = rest;
        Ok(value)
    }

    fn u32(&mut self) -> Result<u32, AcceptanceError> {
        let bytes = self
            .take(/*length*/ 4)?
            .try_into()
            .map_err(|_| invalid("truncated SSHSIG integer"))?;
        Ok(u32::from_be_bytes(bytes))
    }

    fn string(&mut self) -> Result<&'a [u8], AcceptanceError> {
        let length =
            usize::try_from(self.u32()?).map_err(|_| invalid("SSHSIG field length overflow"))?;
        self.take(length)
    }

    fn finish(self) -> Result<(), AcceptanceError> {
        if self.rest.is_empty() {
            Ok(())
        } else {
            Err(invalid("trailing data in SSHSIG structure"))
        }
    }
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}

#[cfg(test)]
#[path = "sshsig_tests.rs"]
mod tests;
