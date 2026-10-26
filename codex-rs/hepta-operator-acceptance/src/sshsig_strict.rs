//! A bounded Ed25519 SSHSIG primitive, never a trust anchor or owner proof.
//! Callers must retain their original pinned-policy/owner admission and native
//! inherited-input verification. Unix also verifies through original OpenSSH.

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use sha2::Digest as _;

use crate::AcceptanceError;

const MAX_SIGNATURE: usize = 4096;
const MAX_ALLOWED_SIGNERS: usize = 16 * 1024;
const MAX_MESSAGE: usize = 1024 * 1024;
const HEADER: &[u8] = b"-----BEGIN SSH SIGNATURE-----\n";
const FOOTER: &[u8] = b"-----END SSH SIGNATURE-----\n";

pub(crate) fn verify_ed25519_sshsig(
    statement: &[u8],
    signature: &[u8],
    allowed_signers: &[u8],
    principal: &str,
    namespace: &str,
) -> Result<(), AcceptanceError> {
    if statement.len() > MAX_MESSAGE
        || signature.len() > MAX_SIGNATURE
        || allowed_signers.len() > MAX_ALLOWED_SIGNERS
        || namespace.is_empty()
    {
        return Err(invalid("SSHSIG input exceeds its admitted bound"));
    }
    let allowed_key = pinned_key(allowed_signers, principal)?;
    let body = signature
        .strip_prefix(HEADER)
        .and_then(|value| value.strip_suffix(FOOTER))
        .ok_or_else(|| invalid("SSHSIG armor differs from the admitted envelope"))?;
    if !body.ends_with(b"\n")
        || body.iter().any(|byte| {
            !byte.is_ascii_alphanumeric() && !matches!(byte, b'+' | b'/' | b'=' | b'\n')
        })
    {
        return Err(invalid("SSHSIG armor is not LF-terminated base64"));
    }
    let encoded: Vec<_> = body.iter().copied().filter(|byte| *byte != b'\n').collect();
    let packet = STANDARD
        .decode(encoded)
        .map_err(|_| invalid("SSHSIG packet base64 is invalid"))?;
    let mut packet = packet.as_slice();
    if take(&mut packet, 6)? != b"SSHSIG" || take(&mut packet, 4)? != 1_u32.to_be_bytes() {
        return Err(invalid("SSHSIG packet magic or version differs from V1"));
    }
    let key = string(&mut packet)?;
    let actual_namespace = string(&mut packet)?;
    let reserved = string(&mut packet)?;
    if !reserved.is_empty() {
        return Err(invalid(
            "SSHSIG V1 admission requires an empty reserved field",
        ));
    }
    let algorithm = string(&mut packet)?;
    let mut signed = string(&mut packet)?;
    if !packet.is_empty() || key != allowed_key || actual_namespace != namespace.as_bytes() {
        return Err(invalid(
            "SSHSIG packet differs from the original pinned key or namespace",
        ));
    }
    let signature_algorithm = string(&mut signed)?;
    let signature_bytes = string(&mut signed)?;
    if signature_algorithm != b"ssh-ed25519" || !signed.is_empty() {
        return Err(invalid("SSHSIG requires exactly one raw Ed25519 signature"));
    }
    let signature = Signature::from_slice(signature_bytes)
        .map_err(|_| invalid("SSHSIG Ed25519 signature length is invalid"))?;
    let hash = match algorithm {
        b"sha256" => sha2::Sha256::digest(statement).to_vec(),
        b"sha512" => sha2::Sha512::digest(statement).to_vec(),
        _ => return Err(invalid("SSHSIG message hash algorithm is unsupported")),
    };
    let mut data = b"SSHSIG".to_vec();
    for part in [actual_namespace, reserved, algorithm, &hash] {
        data.extend(
            u32::try_from(part.len())
                .map_err(|_| invalid("SSHSIG field length overflow"))?
                .to_be_bytes(),
        );
        data.extend(part);
    }
    let mut key = key;
    if string(&mut key)? != b"ssh-ed25519" {
        return Err(invalid("SSHSIG pinned key is not raw Ed25519"));
    }
    let public: [u8; 32] = string(&mut key)?
        .try_into()
        .map_err(|_| invalid("SSHSIG Ed25519 key length is invalid"))?;
    let key_value = VerifyingKey::from_bytes(&public)
        .map_err(|_| invalid("SSHSIG public key is not a valid point"))?;
    if !key.is_empty() || key_value.is_weak() {
        return Err(invalid("SSHSIG public key is malformed or weak"));
    }
    key_value
        .verify_strict(&data, &signature)
        .map_err(|_| invalid("SSHSIG signature does not bind the complete original message"))
}

fn pinned_key(bytes: &[u8], principal: &str) -> Result<Vec<u8>, AcceptanceError> {
    let text =
        std::str::from_utf8(bytes).map_err(|_| invalid("SSHSIG allowed signers is not UTF-8"))?;
    if !text.ends_with('\n') || text.contains('\r') || text.lines().count() != 1 {
        return Err(invalid(
            "SSHSIG requires the original single allowed-signer line",
        ));
    }
    let fields: Vec<_> = text.split_ascii_whitespace().collect();
    if fields.len() != 3 || fields[0] != principal || fields[1] != "ssh-ed25519" {
        return Err(invalid(
            "SSHSIG allowed signer differs from the original principal/key type",
        ));
    }
    STANDARD
        .decode(fields[2])
        .map_err(|_| invalid("SSHSIG allowed key base64 is invalid"))
}

fn string<'a>(packet: &mut &'a [u8]) -> Result<&'a [u8], AcceptanceError> {
    let length = u32::from_be_bytes(
        take(packet, 4)?
            .try_into()
            .map_err(|_| invalid("SSHSIG string length is truncated"))?,
    ) as usize;
    take(packet, length)
}

fn take<'a>(packet: &mut &'a [u8], length: usize) -> Result<&'a [u8], AcceptanceError> {
    if packet.len() < length {
        return Err(invalid("SSHSIG packet is truncated"));
    }
    let (value, rest) = packet.split_at(length);
    *packet = rest;
    Ok(value)
}

fn invalid(message: &str) -> AcceptanceError {
    AcceptanceError::Invalid(message.to_owned())
}
